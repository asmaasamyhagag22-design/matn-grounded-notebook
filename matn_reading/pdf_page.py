"""PDF adapters: everything Matn reads from a PDF page, through pdfplumber (words, chars, images, drawings, tables)
and pypdfium2 (text objects with their render mode, the second text extraction, page labels, rendering).

Coordinates are PDF points with a top-left origin, as pdfplumber gives them (relative to the MediaBox top-left).
pypdfium2 object bounds are bottom-left; ``_to_top_left`` converts them.

Measured facts this module relies on (probe of 2026-10-04, pdfplumber 0.11.9 / pypdfium2 5.13.0):
- pdfplumber chars carry no text render mode; pypdfium2 gives it per text object (``FPDFTextObj_GetTextRenderMode``).
- pdfplumber keeps text outside the CropBox (``page.bbox`` is the MediaBox); pypdfium2 renders the CropBox only.
- both libraries extract text with a font size near zero.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

import numpy as np
import pdfplumber
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

from .layout import Word
from .triage import PageSignals, glyph_issues, text_agreement

_BOLD = re.compile(r"bold|black|heavy|semibold|demi|,b$|-b$|bd$", re.IGNORECASE)
NEAR_ZERO_FONT_PT = 1.0   # a glyph smaller than this is unreadable on paper (baseline count only, no rule yet)
INVISIBLE_RENDER_MODE = pdfium_raw.FPDF_TEXTRENDERMODE_INVISIBLE  # 3

_THRESHOLDS = json.loads((Path(__file__).resolve().parents[1] / "eval" / "reading" / "thresholds.json")
                         .read_text(encoding="utf-8"))
_WORD = _THRESHOLDS["word_segmentation"]
_FOOTNOTE = _THRESHOLDS["footnote_marker"]
_MONTH = re.compile(r"^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?$", re.IGNORECASE)
_VISIBILITY = _THRESHOLDS["visibility"]

EXTRACTOR_VERSION = f"pdfplumber-{pdfplumber.__version__}+pypdfium2-{pdfium.version.PYPDFIUM_INFO.version}"


@dataclass(frozen=True)
class TextObject:
    """One pypdfium2 text object (top-level or inside a Form XObject)."""

    text: str
    bbox: tuple[float, float, float, float]   # top-left origin
    render_mode: int
    font_size: float
    level: int
    index: int
    fill_rgb: tuple[int, int, int]
    clipped: bool


@dataclass(frozen=True)
class PaintObject:
    kind: str
    bbox: tuple[float, float, float, float]
    index: int
    level: int


@dataclass
class PageData:
    page_index: int
    width: float
    height: float
    cropbox: tuple[float, float, float, float]          # top-left origin, pdfplumber coordinates
    page_label: str | None
    words: list[Word]
    chars: list[dict]
    images: list[tuple[float, float, float, float]]
    drawings: list[tuple[float, float, float, float]]
    tables: list[dict]                                   # {"bbox": ..., "rows": [[cell text, ...], ...]}
    text_objects: list[TextObject]
    paint_objects: list[PaintObject]
    plumber_text: str
    pdfium_text: str
    signals: PageSignals | None = None
    edge_cases: dict = field(default_factory=dict)


def _is_bold(fontname: str) -> bool:
    base = fontname.split("+", 1)[-1]  # drop the subset prefix "ABCDEF+"
    return bool(_BOLD.search(base))


def _union_area(boxes: list[tuple[float, float, float, float]], width: float, height: float) -> float:
    """Area covered by the union of boxes, clipped to the page (1-point grid)."""
    if not boxes:
        return 0.0
    w, h = int(np.ceil(width)), int(np.ceil(height))
    mask = np.zeros((h, w), dtype=bool)
    for x0, top, x1, bottom in boxes:
        a, b = max(0, int(np.floor(x0))), min(w, int(np.ceil(x1)))
        c, d = max(0, int(np.floor(top))), min(h, int(np.ceil(bottom)))
        if a < b and c < d:
            mask[c:d, a:b] = True
    return float(mask.sum())


def _overlap_share(inner: tuple[float, float, float, float], outer: tuple[float, float, float, float]) -> float:
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    area = max((inner[2] - inner[0]) * (inner[3] - inner[1]), 1e-9)
    return ix * iy / area


def _object_box(obj, height: float) -> tuple[float, float, float, float]:
    left, bottom, right, top = obj.get_bounds()
    return (left, height - top, right, height - bottom)


def _text_and_paint_objects(page: pdfium.PdfPage, textpage: pdfium.PdfTextPage,
                            height: float) -> tuple[list[TextObject], list[PaintObject]]:
    found, paint = [], []
    objects = list(page.get_objects(max_depth=8))
    for index, obj in enumerate(objects):
        if obj.type in (pdfium_raw.FPDF_PAGEOBJ_IMAGE, pdfium_raw.FPDF_PAGEOBJ_PATH):
            paint.append(PaintObject("image" if obj.type == pdfium_raw.FPDF_PAGEOBJ_IMAGE else "vector",
                                     _object_box(obj, height), index, obj.level))
        if obj.type != pdfium_raw.FPDF_PAGEOBJ_TEXT:
            continue
        n = pdfium_raw.FPDFTextObj_GetText(obj.raw, textpage.raw, None, 0)
        buffer = (ctypes.c_ushort * max(n, 1))()
        pdfium_raw.FPDFTextObj_GetText(obj.raw, textpage.raw, buffer, max(n, 1) * 2)
        text = bytes(buffer).decode("utf-16-le", errors="replace").rstrip("\x00")
        size = ctypes.c_float()
        pdfium_raw.FPDFTextObj_GetFontSize(obj.raw, ctypes.byref(size))
        red, green, blue, alpha = (ctypes.c_uint() for _ in range(4))
        pdfium_raw.FPDFPageObj_GetFillColor(obj.raw, ctypes.byref(red), ctypes.byref(green), ctypes.byref(blue),
                                            ctypes.byref(alpha))
        clip = pdfium_raw.FPDFPageObj_GetClipPath(obj.raw)
        clipped = bool(clip and pdfium_raw.FPDFClipPath_CountPaths(clip) > 0)
        found.append(TextObject(text, _object_box(obj, height),
                                pdfium_raw.FPDFTextObj_GetTextRenderMode(obj.raw), float(size.value), obj.level,
                                index, (red.value, green.value, blue.value), clipped))
    for obj in sorted(objects, key=lambda item: item.level, reverse=True):
        obj.close()
    return found, paint


def _char_box(char: dict) -> tuple[float, float, float, float]:
    return tuple(float(char[key]) for key in ("x0", "top", "x1", "bottom"))  # type: ignore[return-value]


def _box_intersection_share(inner: tuple[float, float, float, float],
                            outer: tuple[float, float, float, float]) -> float:
    return _overlap_share(inner, outer)


def _containing_text_object(char: dict, objects: list[TextObject]) -> TextObject | None:
    box = _char_box(char)
    candidates = [obj for obj in objects if _box_intersection_share(box, obj.bbox) >= 0.5]
    return min(candidates, key=lambda obj: (obj.bbox[2] - obj.bbox[0]) * (obj.bbox[3] - obj.bbox[1])) \
        if candidates else None


def _contrast(rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int]) -> float:
    def luminance(rgb):
        values = [value / 255 for value in rgb]
        values = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
        return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]
    first, second = luminance(rgb_a), luminance(rgb_b)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


def _pixel_box(box, cropbox, scale, width, height):
    x0, top, x1, bottom = box
    cx, cy = cropbox[0], cropbox[1]
    return (max(0, int(np.floor((x0 - cx) * scale))), max(0, int(np.floor((top - cy) * scale))),
            min(width, int(np.ceil((x1 - cx) * scale))), min(height, int(np.ceil((bottom - cy) * scale))))


def _visibility_candidates(data: PageData) -> list[dict]:
    x0, top, x1, bottom = data.cropbox
    candidates = []
    for position, char in enumerate(data.chars):
        if char["text"].isspace():
            continue
        box = _char_box(char)
        centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        obj = _containing_text_object(char, data.text_objects)
        reasons: list[str] = []
        if not (x0 <= centre[0] <= x1 and top <= centre[1] <= bottom):
            reasons.append("outside_cropbox")
        if float(char["size"]) < _VISIBILITY["near_zero_size_pt"]:
            reasons.append("near_zero_size")
        if obj is not None:
            image_under = any(paint.kind == "image" and _box_intersection_share(obj.bbox, paint.bbox) >= 0.5
                              for paint in data.paint_objects)
            if obj.render_mode in (3, 7) and not image_under:
                reasons.append("invisible_render_mode")
            for paint in data.paint_objects:
                if paint.index > obj.index and _box_intersection_share(box, paint.bbox) >= 0.5:
                    reasons.append("covered_by_image" if paint.kind == "image" else "covered_by_vector")
            if obj.clipped:
                reasons.append("clipped")
            # Non-black fills are cheap candidates; the real background comparison happens on the text-free render.
            if max(obj.fill_rgb) > 32:
                char["_fill_rgb"] = obj.fill_rgb
                reasons.append("_check_fill")
        audit_key = f"{_VISIBILITY['audit_seed']}:{data.page_index}:{position}:{char['text']}".encode()
        audited = int.from_bytes(hashlib.sha256(audit_key).digest()[:8], "big") / 2**64 < _VISIBILITY["audit_fraction"]
        if reasons or audited:
            char["_candidate"] = True
            char["_visibility_reasons"] = reasons
            candidates.append(char)
        else:
            char["_visibility"] = "visible"
            char["_visibility_reasons"] = []
    return candidates


def _apply_differential_visibility(data: PageData, path: Path) -> None:
    candidates = _visibility_candidates(data)
    if not candidates:
        return
    scale = float(_VISIBILITY["render_scale"])
    with pdfium.PdfDocument(str(path)) as document:
        page = document[data.page_index]
        full = np.asarray(render_page(page, scale), dtype=np.int16)
        objects = list(page.get_objects(max_depth=8))
        text_objects = [obj for obj in objects if obj.type == pdfium_raw.FPDF_PAGEOBJ_TEXT]
        for obj in text_objects:
            page.remove_obj(obj)
            obj.close()
        page.gen_content()
        no_text = np.asarray(render_page(page, scale), dtype=np.int16)
        for obj in sorted((item for item in objects if item not in text_objects),
                          key=lambda item: item.level, reverse=True):
            obj.close()
    gray_full = np.round(full.mean(axis=2)).astype(np.int16)
    gray_no_text = np.round(no_text.mean(axis=2)).astype(np.int16)
    delta = np.abs(gray_full - gray_no_text)
    image_h, image_w = delta.shape
    for char in candidates:
        box = _char_box(char)
        px = _pixel_box(box, data.cropbox, scale, image_w, image_h)
        x0, y0, x1, y1 = px
        full_region = delta[y0:y1, x0:x1]
        full_changed = int((full_region >= _VISIBILITY["grayscale_delta"]).sum())
        inset = float(_VISIBILITY["bbox_inset_share"])
        dx, dy = (x1 - x0) * inset, (y1 - y0) * inset
        ix0, iy0, ix1, iy1 = int(x0 + dx), int(y0 + dy), int(x1 - dx), int(y1 - dy)
        inner = delta[iy0:iy1, ix0:ix1]
        changed = int((inner >= _VISIBILITY["grayscale_delta"]).sum())
        if inner.size < _VISIBILITY["small_inner_min_pixels"]:
            changed = full_changed
            share = full_changed / max(full_region.size, 1)
        else:
            share = changed / inner.size
        reasons = [reason for reason in char.get("_visibility_reasons", []) if reason != "_check_fill"]
        fill = char.get("_fill_rgb")
        if fill is not None and x0 < x1 and y0 < y1:
            background = tuple(int(value) for value in np.median(no_text[y0:y1, x0:x1], axis=(0, 1)))
            if _contrast(fill, background) < _VISIBILITY["fill_background_contrast"]:
                reasons.append("fill_matches_background")
        if changed >= _VISIBILITY["visible_min_changed_pixels"] and share >= _VISIBILITY["visible_min_changed_share"]:
            visibility = "visible"
            reasons = []
        elif full_changed == 0:
            visibility = "hidden"
            reasons = reasons or ["no_ink_unexplained"]
        else:
            visibility = "uncertain"
            reasons.append("partial_ink")
        char["_visibility"] = visibility
        char["_visibility_reasons"] = list(dict.fromkeys(reasons))


def _words_from_chars(chars: list[dict]) -> list[Word]:
    """Build words from glyph geometry. Spaces are evidence, not the sole delimiter."""
    visible_chars = [char for char in chars if char.get("text")]
    def is_vertical(char: dict) -> bool:
        matrix = char.get("matrix", (1, 0, 0, 1, 0, 0))
        return (float(matrix[0]) < 0 and float(matrix[3]) < 0
                or not char.get("upright", True)
                or abs(float(matrix[1])) + abs(float(matrix[2]))
                > abs(float(matrix[0])) + abs(float(matrix[3])))

    horizontal = [char for char in visible_chars if not is_vertical(char)]
    vertical = [char for char in visible_chars if is_vertical(char)]
    horizontal_nonspace = [char for char in horizontal if not char["text"].isspace()]
    for char in horizontal_nonspace:
        size = float(char["size"])
        nearby_body = [other for other in horizontal_nonspace if other is not char
                       and float(other["size"]) >= size / _FOOTNOTE["max_body_size_ratio"]
                       and max(float(other["x0"]) - float(char["x1"]),
                               float(char["x0"]) - float(other["x1"]), 0.0)
                       <= _FOOTNOTE["link_x_distance_em"] * float(other["size"])
                       and 0.0 < float(other["bottom"]) - float(char["bottom"])
                       <= float(other["size"])]
        char["_footnote_marker"] = bool(
            char["text"].isdigit() and nearby_body
            and max(float(other["bottom"]) - float(char["bottom"]) for other in nearby_body)
            >= _FOOTNOTE["min_baseline_raise_em"] * median(float(other["size"]) for other in nearby_body)
        )
    rows: list[list[dict]] = []
    for char in sorted(horizontal, key=lambda item: ((float(item["top"]) + float(item["bottom"])) / 2,
                                                     float(item["x0"]))):
        centre = (float(char["top"]) + float(char["bottom"])) / 2
        target = next((row for row in reversed(rows[-5:])
                       if abs(centre - median((float(item["top"]) + float(item["bottom"])) / 2 for item in row))
                       <= _WORD["line_center_tolerance_height"] * min(float(char["height"]),
                                                                      median(float(item["height"]) for item in row))),
                      None)
        if target is None:
            rows.append([char])
        else:
            target.append(char)
    words: list[Word] = []
    for row in rows:
        row.sort(key=lambda item: float(item["x0"]))
        nonspace = [char for char in row if not char["text"].isspace()]
        if not nonspace:
            continue
        current: list[dict] = []

        def finish() -> None:
            if not current:
                return
            text = "".join(char["text"] for char in current if not char["text"].isspace())
            if not text:
                current.clear()
                return
            reasons = tuple(dict.fromkeys(reason for char in current for reason in char.get("_visibility_reasons", [])))
            states = {char.get("_visibility", "visible") for char in current}
            state = "hidden" if "hidden" in states else "uncertain" if "uncertain" in states else "visible"
            marker = all(char.get("_footnote_marker", False) for char in current if not char["text"].isspace())
            words.append(Word(text, min(float(char["x0"]) for char in current),
                              min(float(char["top"]) for char in current),
                              max(float(char["x1"]) for char in current),
                              max(float(char["bottom"]) for char in current),
                              round(median(float(char["size"]) for char in current), 2),
                              any(_is_bold(str(char["fontname"])) for char in current),
                              "footnote_marker" if marker else "word", False, state, reasons))
            current.clear()

        previous_nonspace = None
        for index, char in enumerate(row):
            if char["text"].isspace():
                next_char = next((item for item in row[index + 1:] if not item["text"].isspace()), None)
                compact = "".join(item["text"] for item in current if not item["text"].isspace())
                next_nonspace = [item["text"] for item in row[index + 1:] if not item["text"].isspace()]
                date_break = (bool(re.fullmatch(r"\d{1,2}\.", compact)) and words
                              and bool(_MONTH.match(words[-1].text))
                              and bool(re.match(r"^\d{4}(?:\D|$)", "".join(next_nonspace))))
                numeric_bridge = (previous_nonspace is not None and next_char is not None
                                  and previous_nonspace["text"] in "0123456789.%+-"
                                  and next_char["text"] in "0123456789.%+-"
                                  and (previous_nonspace["text"] in ".%"
                                       or next_char["text"] in ".%")
                                  and (any(character.isdigit() for character in compact) or len(compact) <= 1)
                                  and not date_break)
                if not numeric_bridge:
                    finish()
                continue
            if current:
                previous = current[-1]
                gap = float(char["x0"]) - float(previous["x1"])
                em = max(float(char["size"]), float(previous["size"]))
                compact = "".join(item["text"] for item in current if not item["text"].isspace())
                dot_leader_break = ((char["text"] == "." and previous["text"] == "."
                                     and any(character.isdigit() for character in compact))
                                    or (char["text"].isdigit() and len(compact) >= 2
                                        and set(compact) == {"."}))
                if dot_leader_break:
                    finish()
                    compact = ""
                if not current:
                    current.append(char)
                    previous_nonspace = char
                    continue
                previous = current[-1]
                numeric = (previous["text"] in "0123456789.%+-" and char["text"] in "0123456789.%+-"
                           and (any(character.isdigit() for character in compact) or len(compact) <= 1))
                limit = _WORD["tracked_numeric_gap_em"] if numeric else _WORD["gap_em"]
                changed = (char.get("_visibility", "visible"), tuple(char.get("_visibility_reasons", [])),
                           char.get("_footnote_marker", False)) != (
                               previous.get("_visibility", "visible"), tuple(previous.get("_visibility_reasons", [])),
                               previous.get("_footnote_marker", False))
                if gap > limit * em or changed:
                    finish()
            current.append(char)
            previous_nonspace = char
        finish()

    # Preserve the text object's direction for rotated text instead of sorting by top, which reverses it.
    columns: dict[tuple[int, int], list[dict]] = {}
    for char in vertical:
        matrix = char.get("matrix", (0, 1, -1, 0, 0, 0))
        columns.setdefault((round(float(char["x0"])), 1 if float(matrix[1]) >= 0 else -1), []).append(char)
    for (_, direction), column in columns.items():
        column.sort(key=lambda char: float(char["top"]), reverse=direction > 0)
        text = "".join(char["text"] for char in column if not char["text"].isspace())
        if not text:
            continue
        reasons = tuple(dict.fromkeys(reason for char in column for reason in char.get("_visibility_reasons", [])))
        states = {char.get("_visibility", "visible") for char in column}
        state = "hidden" if "hidden" in states else "uncertain" if "uncertain" in states else "visible"
        words.append(Word(text, min(float(char["x0"]) for char in column), min(float(char["top"]) for char in column),
                          max(float(char["x1"]) for char in column), max(float(char["bottom"]) for char in column),
                          round(median(float(char["size"]) for char in column), 2),
                          any(_is_bold(str(char["fontname"])) for char in column), "word", True, state, reasons))
    return sorted(words, key=lambda word: (word.top, word.x0))


def read_page(plumber_page: pdfplumber.page.Page, pdfium_page: pdfium.PdfPage, page_index: int,
              page_label: str | None) -> PageData:
    width, height = float(plumber_page.width), float(plumber_page.height)
    images = [(float(i["x0"]), float(i["top"]), float(i["x1"]), float(i["bottom"])) for i in plumber_page.images]
    page_area = width * height
    drawings = [(float(o["x0"]), float(o["top"]), float(o["x1"]), float(o["bottom"]))
                for o in (*plumber_page.rects, *plumber_page.lines, *plumber_page.curves)
                if (float(o["x1"]) - float(o["x0"])) * (float(o["bottom"]) - float(o["top"])) < 0.5 * page_area]
    tables = []
    for table in plumber_page.find_tables():
        rows = [[cell or "" for cell in row] for row in table.extract()]
        tables.append({"bbox": tuple(float(v) for v in table.bbox), "rows": rows})
    textpage = pdfium_page.get_textpage()
    text_objects, paint_objects = _text_and_paint_objects(pdfium_page, textpage, height)
    crop = plumber_page.cropbox
    chars = list(plumber_page.chars)
    data = PageData(page_index, width, height, (float(crop[0]), float(crop[1]), float(crop[2]), float(crop[3])),
                    page_label, [], chars, images, drawings, tables, text_objects, paint_objects,
                    plumber_page.extract_text() or "", textpage.get_text_range())
    data.words = _words_from_chars(chars)
    data.signals = _signals(data)
    data.edge_cases = edge_case_counts(data)
    return data


def _signals(page: PageData) -> PageSignals:
    chars = [c for c in page.chars if not c["text"].isspace()]
    invisible = sum(len(o.text.replace(" ", "")) for o in page.text_objects if o.render_mode == INVISIBLE_RENDER_MODE)
    total = len(chars)
    char_boxes = [(float(c["x0"]), float(c["top"]), float(c["x1"]), float(c["bottom"])) for c in chars]
    issues = glyph_issues("".join(c["text"] for c in chars))
    return PageSignals(
        chars=total,
        visible_chars=max(total - invisible, 0),
        invisible_chars=min(invisible, total),
        broken_glyphs=sum(issues.values()),
        text_coverage=_union_area(char_boxes, page.width, page.height) / (page.width * page.height),
        image_coverage=_union_area(page.images, page.width, page.height) / (page.width * page.height),
        agreement=text_agreement(page.plumber_text, page.pdfium_text),
    )


def edge_case_counts(page: PageData) -> dict:
    """Baseline counts for the three cases the owner asked about (no rule acts on them yet):
    - render mode 3 text with no image under it (an OCR layer sits over a page image; this does not);
    - characters whose centre lies outside the CropBox;
    - characters with a font size below NEAR_ZERO_FONT_PT."""
    mode3_no_image = sum(
        len(o.text.replace(" ", "")) for o in page.text_objects
        if o.render_mode == INVISIBLE_RENDER_MODE and not any(_overlap_share(o.bbox, img) >= 0.5 for img in page.images))
    x0, top, x1, bottom = page.cropbox
    outside = sum(1 for c in page.chars if not c["text"].isspace() and not (
        x0 <= (float(c["x0"]) + float(c["x1"])) / 2 <= x1 and top <= (float(c["top"]) + float(c["bottom"])) / 2 <= bottom))
    tiny = sum(1 for c in page.chars if not c["text"].isspace() and float(c["size"]) < NEAR_ZERO_FONT_PT)
    return {"mode3_without_image": mode3_no_image, "outside_cropbox": outside, "near_zero_font": tiny}


def render_page(pdfium_page: pdfium.PdfPage, scale: float):
    """PIL RGB image of the CropBox at ``scale`` (1.0 = 72 DPI)."""
    return pdfium_page.render(scale=scale).to_pil().convert("RGB")


class OpenPdf:
    """Both libraries open on the same file; use as a context manager."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.plumber = pdfplumber.open(self.path)
        self.pdfium = pdfium.PdfDocument(str(self.path))
        return self

    def __exit__(self, *exc):
        self.plumber.close()
        self.pdfium.close()

    def __len__(self) -> int:
        return len(self.plumber.pages)

    def page(self, index: int) -> PageData:
        label = self.pdfium.get_page_label(index) or None
        data = read_page(self.plumber.pages[index], self.pdfium[index], index, label)
        _apply_differential_visibility(data, Path(self.path))
        data.words = _words_from_chars(data.chars)
        return data
