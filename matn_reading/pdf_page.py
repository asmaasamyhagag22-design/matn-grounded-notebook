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
import re
from dataclasses import dataclass, field

import numpy as np
import pdfplumber
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw

from .layout import Word
from .triage import PageSignals, glyph_issues, text_agreement

_BOLD = re.compile(r"bold|black|heavy|semibold|demi|,b$|-b$|bd$", re.IGNORECASE)
NEAR_ZERO_FONT_PT = 1.0   # a glyph smaller than this is unreadable on paper (baseline count only, no rule yet)
INVISIBLE_RENDER_MODE = pdfium_raw.FPDF_TEXTRENDERMODE_INVISIBLE  # 3

EXTRACTOR_VERSION = f"pdfplumber-{pdfplumber.__version__}+pypdfium2-{pdfium.version.PYPDFIUM_INFO.version}"


@dataclass(frozen=True)
class TextObject:
    """One pypdfium2 text object (top-level or inside a Form XObject)."""

    text: str
    bbox: tuple[float, float, float, float]   # top-left origin
    render_mode: int
    font_size: float
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


def _text_objects(page: pdfium.PdfPage, textpage: pdfium.PdfTextPage, height: float) -> list[TextObject]:
    found = []
    for obj in page.get_objects(max_depth=8):
        if obj.type != pdfium_raw.FPDF_PAGEOBJ_TEXT:
            continue
        n = pdfium_raw.FPDFTextObj_GetText(obj.raw, textpage.raw, None, 0)
        buffer = (ctypes.c_ushort * max(n, 1))()
        pdfium_raw.FPDFTextObj_GetText(obj.raw, textpage.raw, buffer, max(n, 1) * 2)
        text = bytes(buffer).decode("utf-16-le", errors="replace").rstrip("\x00")
        size = ctypes.c_float()
        pdfium_raw.FPDFTextObj_GetFontSize(obj.raw, ctypes.byref(size))
        left, bottom, right, top = obj.get_bounds()
        found.append(TextObject(text, (left, height - top, right, height - bottom),
                                pdfium_raw.FPDFTextObj_GetTextRenderMode(obj.raw), float(size.value), obj.level))
    return found


def read_page(plumber_page: pdfplumber.page.Page, pdfium_page: pdfium.PdfPage, page_index: int,
              page_label: str | None) -> PageData:
    width, height = float(plumber_page.width), float(plumber_page.height)
    raw_words = plumber_page.extract_words(extra_attrs=["size", "fontname"], keep_blank_chars=False,
                                           use_text_flow=False)
    words = [Word(w["text"], float(w["x0"]), float(w["top"]), float(w["x1"]), float(w["bottom"]),
                  round(float(w["size"]), 2), _is_bold(w["fontname"])) for w in raw_words]
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
    text_objects = _text_objects(pdfium_page, textpage, height)
    crop = plumber_page.cropbox
    data = PageData(page_index, width, height, (float(crop[0]), float(crop[1]), float(crop[2]), float(crop[3])),
                    page_label, words, list(plumber_page.chars), images, drawings, tables, text_objects,
                    plumber_page.extract_text() or "", textpage.get_text_range())
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
        return read_page(self.plumber.pages[index], self.pdfium[index], index, label)
