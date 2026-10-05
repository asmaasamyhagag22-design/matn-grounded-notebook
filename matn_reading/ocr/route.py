"""OCR route for one scanned page: image -> reader 1 -> targeted second reads -> flags -> contract Blocks (route ocr).

Fail loud, never silent (docs/ocr_rules.md):
- reader 1 (RapidOCR PP-OCRv5) reads every line; nothing is dropped for low confidence;
- whole lines holding target numbers are second-read by GLM-OCR (one call per line). A number is accepted only when
  both readers agree exactly; otherwise it is ``uncertain_number`` with both readings and the crop kept;
- a number on a line that is not second-read is accepted on reader 1 alone only at or above the frozen confidence bar;
- table totals and text-vs-table repeats are checked, and an embedded OCR layer (render mode 3) is compared;
- an inked page where reader 1 finds no text is flagged as a whole.
Layout reuses the 4b logic (lines, blocks, gutters, side headings) on the OCR word boxes in page points.
"""
from __future__ import annotations

import io
import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

import numpy as np
from PIL import Image

from matn_contracts.domain import Block, BlockStyle, ExtractorInfo
from matn_contracts.enums import BlockType, ExtractionRoute, Visibility

from ..classify import block_type
from ..layout import Word, group_blocks, group_lines, order_blocks
from ..read import PageReading, ReadBlock
from ..triage import Route
from .consensus import compare_line
from .consistency import Cell, cell_value, check_table_totals, check_text_against_tables
from .numbers import normalize, number_spans
from .preprocess import PreprocessConfig, preprocess

RULES = json.loads(Path(__file__).with_name("ocr_rules.json").read_text(encoding="utf-8"))
EXTRACTOR = ExtractorInfo(name="matn_reading.ocr", version="rapidocr-3.9.2+PP-OCRv5-mobile-onnx+glm-ocr-bf16")
BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class OcrConfig:
    preprocess: PreprocessConfig = PreprocessConfig()
    second_read: bool = True
    targets: frozenset[str] = frozenset(RULES["second_read_targets_laptop"])
    confidence_bar: float | None = RULES["confidence_bar"]
    dpi: int = RULES["render_dpi"]


@dataclass
class _Word:
    text: str
    score: float
    box_px: BBox
    box: BBox
    line: int


@dataclass
class _Line:
    index: int
    text: str
    score: float
    box_px: BBox
    box: BBox
    words: list[_Word] = field(default_factory=list)

    @property
    def height(self) -> float:
        return self.box_px[3] - self.box_px[1]


def _axis_box(quad) -> BBox:
    xs, ys = [p[0] for p in quad], [p[1] for p in quad]
    return (float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys)))


def _overlap(a: BBox, b: BBox) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return 0.0 if smaller <= 0 else ix * iy / smaller


def _union(boxes) -> BBox:
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _lines(reply: dict, to_pt) -> list[_Line]:
    lines = []
    for index, raw in enumerate(reply["lines"]):
        box_px = _axis_box(raw["box"])
        line = _Line(index, raw["text"], float(raw["score"]), box_px, to_pt(box_px))
        words = raw.get("words") or [{"text": raw["text"], "score": raw["score"], "box": raw["box"]}]
        for word in words:
            if not word["text"].strip():
                continue
            wbox = _axis_box(word["box"])
            line.words.append(_Word(word["text"], float(word["score"]), wbox, to_pt(wbox), index))
        lines.append(line)
    return lines


def _token_box(word: _Word, start: int, end: int) -> BBox:
    length = max(len(normalize(word.text)), 1)
    x0, top, x1, bottom = word.box
    return (x0 + (x1 - x0) * start / length, top, x0 + (x1 - x0) * end / length, bottom)


def _rows(lines: list[_Line]) -> list[list[_Line]]:
    heights = [line.height for line in lines] or [1.0]
    tolerance = RULES["row_center_tolerance_height"] * median(heights)
    rows: list[list[_Line]] = []
    for line in sorted(lines, key=lambda l: ((l.box_px[1] + l.box_px[3]) / 2, l.box_px[0])):
        centre = (line.box_px[1] + line.box_px[3]) / 2
        if rows and abs(centre - median((l.box_px[1] + l.box_px[3]) / 2 for l in rows[-1])) <= tolerance:
            rows[-1].append(line)
        else:
            rows.append([line])
    return [sorted(row, key=lambda l: l.box_px[0]) for row in rows]


def _segments(line: _Line) -> list[list[_Word]]:
    """Words split at wide gaps (a table row read as one line keeps its cells apart)."""
    words = sorted(line.words, key=lambda w: w.box_px[0])
    if not words:
        return []
    gap = RULES["cell_split_gap_height"] * max(line.height, 1.0)
    segments = [[words[0]]]
    for previous, word in zip(words, words[1:]):
        if word.box_px[0] - previous.box_px[2] > gap:
            segments.append([])
        segments[-1].append(word)
    return segments


def _cell(words: list[_Word]) -> Cell:
    return Cell(" ".join(w.text for w in words), _union(w.box for w in words), ref=tuple(id(w) for w in words))


def _row_cells(row: list[_Line]) -> list[Cell]:
    """Cells of a table row: gap-separated segments, further split where numeric and label words meet."""
    cells = []
    for line in row:
        for segment in _segments(line):
            run: list[_Word] = []
            for word in segment:
                numeric = cell_value(Cell(word.text, word.box)) is not None
                if run and numeric != (cell_value(Cell(run[-1].text, run[-1].box)) is not None):
                    cells.append(_cell(run))
                    run = []
                run.append(word)
            if run:
                cells.append(_cell(run))
    return cells


def _tables(rows: list[list[_Line]]) -> list[list[list[_Line]]]:
    def table_like(row: list[_Line]) -> bool:
        segments = [segment for line in row for segment in _segments(line)]
        numeric = any(cell_value(_cell(segment)) is not None or
                      any(cell_value(Cell(w.text, w.box)) is not None for w in segment) for segment in segments)
        return len(segments) >= RULES["table_row_min_cells"] and numeric

    tables, current = [], []
    for row in rows:
        if table_like(row):
            if current:
                gap = min(l.box_px[1] for l in row) - max(l.box_px[3] for l in current[-1])
                if gap > RULES["table_max_row_gap_height"] * median(l.height for l in row):
                    if len(current) >= RULES["table_min_rows"]:
                        tables.append(current)
                    current = []
            current.append(row)
        else:
            if len(current) >= RULES["table_min_rows"]:
                tables.append(current)
            current = []
    if len(current) >= RULES["table_min_rows"]:
        tables.append(current)
    return tables


def _kpi(word: _Word, next_word: _Word | None, line: _Line, median_height: float) -> bool:
    if any(symbol in word.text for symbol in RULES["kpi_symbols"]):
        return True
    if next_word is not None and next_word.text.lower().strip(".,;:") in RULES["kpi_units"]:
        return True
    return line.height >= RULES["kpi_large_line_height_ratio"] * median_height


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def read_scan_page(image: Image.Image, *, page_index: int, page_label: str | None, cropbox: BBox, route: Route,
                   reasons: list[str], doc_id: str, worker, glm, config: OcrConfig = OcrConfig(),
                   crop_dir: Path | None = None, summary_regions: list[BBox] = (),
                   text_layer: list[tuple[str, BBox]] = ()) -> PageReading:
    if config.confidence_bar is None:
        raise ValueError("the OCR confidence bar is not calibrated (matn_reading/ocr/ocr_rules.json)")
    bar = config.confidence_bar
    started = time.perf_counter()
    processed, record = preprocess(image, config.preprocess)
    preprocess_seconds = time.perf_counter() - started
    scale = 72.0 / config.dpi

    def to_pt(box: BBox) -> BBox:
        return (cropbox[0] + box[0] * scale, cropbox[1] + box[1] * scale,
                cropbox[0] + box[2] * scale, cropbox[1] + box[3] * scale)

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "page.png"
        processed.save(path)
        started = time.perf_counter()
        reply = worker.read(path)
        reader1_wall = time.perf_counter() - started
    lines = _lines(reply, to_pt)
    median_height = median([l.height for l in lines]) if lines else 1.0
    flags: list[dict] = []

    # Every number token with its place, score and the reasons it is (or is not) trusted.
    tokens: list[dict] = []
    by_line: dict[int, list[dict]] = {}
    for line in lines:
        words = sorted(line.words, key=lambda w: w.box_px[0])
        for position, word in enumerate(words):
            following = words[position + 1] if position + 1 < len(words) else None
            for token, start, end in number_spans(word.text):
                entry = {"token": token, "line": line.index, "word": word.text, "score": word.score,
                         "bbox": _token_box(word, start, end), "status": "reader1_only", "reader2": None,
                         "flagged": False, "reasons": [], "targets": [],
                         "kpi": _kpi(word, following, line, median_height), "_word": id(word)}
                tokens.append(entry)
                by_line.setdefault(line.index, []).append(entry)
        line.words = words

    rows = _rows(lines)
    tables = _tables(rows)
    table_lines = {line.index for table in tables for row in table for line in row}
    for entry in tokens:
        line = lines[entry["line"]]
        if "all" in config.targets:
            entry["targets"].append("all")
        if "low_confidence" in config.targets and entry["score"] < bar:
            entry["targets"].append("low_confidence")
        if "table" in config.targets and entry["line"] in table_lines:
            entry["targets"].append("table")
        if "kpi" in config.targets and entry["kpi"]:
            entry["targets"].append("kpi")
        if "summary" in config.targets and any(_overlap(line.box, region) > 0 for region in summary_regions):
            entry["targets"].append("summary")

    second_reads = {"lines": 0, "calls": 0, "cached": 0, "seconds": 0.0}
    for line in lines:
        entries = by_line.get(line.index, [])
        if not entries or not config.second_read or glm is None or not any(e["targets"] for e in entries):
            continue
        pad = RULES["crop_pad_px"]
        x0, y0, x1, y1 = line.box_px
        crop = processed.crop((max(0, int(x0) - pad), max(0, int(y0) - pad),
                               min(processed.width, int(x1) + pad), min(processed.height, int(y1) + pad)))
        png = _png(crop)
        result = glm.read_line(png)
        second_reads["lines"] += 1
        second_reads["calls"] += not result.cached
        second_reads["cached"] += result.cached
        second_reads["seconds"] += result.seconds
        verdict = compare_line([{"text": w.text, "score": w.score} for w in line.words], result.text)
        crop_name = None
        if any(v.status != "agreed" for v in verdict.tokens) or verdict.extra_in_reader2:
            if crop_dir is not None:
                crop_name = f"crops/{result.key}.png"
                (Path(crop_dir) / "crops").mkdir(parents=True, exist_ok=True)
                (Path(crop_dir) / crop_name).write_bytes(png)
        for entry, judged in zip(entries, verdict.tokens):
            entry["status"], entry["reader2"] = judged.status, judged.reader2
            if judged.status != "agreed":
                reason = "second_read_failed" if result.text is None else "readers_disagree"
                entry["flagged"] = True
                entry["reasons"].append(reason)
                flags.append({"kind": "uncertain_number", "bbox": entry["bbox"], "reader1": entry["token"],
                              "reader2": judged.reader2, "reason": reason, "crop": crop_name,
                              "reader2_line": result.text, "error": result.error})
        if verdict.extra_in_reader2:
            flags.append({"kind": "possible_drop", "bbox": line.box, "reader2": verdict.extra_in_reader2,
                          "reader1_line": line.text, "reader2_line": result.text, "crop": crop_name})

    for entry in tokens:
        if entry["status"] == "reader1_only" and entry["score"] < bar:
            entry["flagged"] = True
            entry["reasons"].append("low_confidence")
            flags.append({"kind": "uncertain_number", "bbox": entry["bbox"], "reader1": entry["token"],
                          "reader2": None, "reason": "low_confidence", "score": entry["score"], "crop": None})
    number_words = {entry["_word"] for entry in tokens}
    for line in lines:
        for word in line.words:
            if id(word) not in number_words and word.score < bar:
                flags.append({"kind": "low_confidence", "bbox": word.box, "text": word.text, "score": word.score})

    # Free internal checks.
    def flag_cells(cells: list[Cell], kind: str, detail: str) -> None:
        refs = {ref for cell in cells for ref in (cell.ref or ())}
        for entry in tokens:
            if entry["_word"] in refs:
                entry["flagged"] = True
                if kind not in entry["reasons"]:
                    entry["reasons"].append(kind)
        flags.append({"kind": kind, "bbox": _union(c.box for c in cells), "detail": detail})

    table_cells: list[Cell] = []
    for table in tables:
        cells_by_row = [_row_cells(row) for row in table]
        table_cells += [cell for row in cells_by_row for cell in row]
        for issue in check_table_totals(cells_by_row):
            flag_cells(issue.cells, issue.kind, issue.detail)
    prose_cells = [_cell([w]) for line in lines if line.index not in table_lines for w in line.words
                   if number_spans(w.text)]
    for issue in check_text_against_tables(prose_cells, [c for c in table_cells if number_spans(c.text)]):
        flag_cells(issue.cells, issue.kind, issue.detail)

    # An embedded OCR layer (render mode 3) is a third, independent reading of the same page.
    for entry in tokens:
        layer = [text for text, box in text_layer if _overlap(box, entry["bbox"]) > 0.3]
        if not layer:
            continue
        layer_tokens = [t for text in layer for t, _, _ in number_spans(text)]
        if entry["token"] not in layer_tokens:
            entry["flagged"] = True
            entry["reasons"].append("ocr_layer_disagreement")
            flags.append({"kind": "ocr_layer_disagreement", "bbox": entry["bbox"], "reader1": entry["token"],
                          "layer": " ".join(layer)})
    for text, box in text_layer:
        if number_spans(text) and not any(_overlap(box, entry["bbox"]) > 0.3 for entry in tokens):
            flags.append({"kind": "possible_drop", "bbox": box, "layer": text, "reader2": None})

    pixels = np.asarray(processed)
    ink_share = float((pixels < RULES["ink_threshold_gray"]).mean())
    width, height = cropbox[2] - cropbox[0], cropbox[3] - cropbox[1]
    if not lines and ink_share > RULES["empty_page_ink_share"]:
        flags.append({"kind": "ocr_no_text", "bbox": tuple(cropbox), "ink_share": round(ink_share, 4)})

    # Layout with the 4b logic, on OCR words in page points.
    layout_words = [Word(w.text, *w.box, size=max(w.box[3] - w.box[1], 0.1)) for line in lines for w in line.words]
    blocks = order_blocks(group_blocks(group_lines(layout_words)), width) if layout_words else []
    body = median(w.size for w in layout_words) if layout_words else 10.0
    flagged_boxes = [entry["bbox"] for entry in tokens if entry["flagged"]] + [
        f["bbox"] for f in flags if f["kind"] in ("low_confidence", "possible_drop")]
    read: list[ReadBlock] = []
    for order, block in enumerate(blocks):
        kind = block_type(block, body, height, in_figure=False)
        flagged = any(_overlap(block.bbox, box) > 0.5 for box in flagged_boxes) or bool(
            any(f["kind"] == "ocr_no_text" for f in flags))
        x0, top, x1, bottom = block.bbox
        padded = (x0, top, x1 if x1 > x0 else x0 + 0.01, bottom if bottom > top else top + 0.01)
        item = ReadBlock(block, kind, flagged, padded)
        item.contract = Block.create(
            doc_id=doc_id, page_index=page_index, page_label=page_label, bbox=padded, block_type=BlockType(kind),
            text=block.text, reading_order=order, style=BlockStyle(font_size_pt=None, is_bold=None),
            extractor=EXTRACTOR, route=ExtractionRoute.OCR, visibility=Visibility.VISIBLE)
        read.append(item)

    for entry in tokens:
        entry.pop("_word")
    scores = [w.score for line in lines for w in line.words]
    details = {
        "preprocess": record, "preprocess_seconds": round(preprocess_seconds, 3), "reader1_seconds": reply.get("seconds"),
        "reader1_wall_seconds": round(reader1_wall, 3), "second_reads": second_reads,
        "targets": sorted(config.targets), "second_read": config.second_read, "confidence_bar": bar,
        "mean_confidence": round(sum(scores) / len(scores), 4) if scores else None, "ink_share": round(ink_share, 4),
        "tokens": tokens, "lines": [{"index": l.index, "text": l.text, "score": l.score, "bbox": l.box,
                                      "words": [{"text": w.text, "score": w.score, "bbox": w.box} for w in l.words]}
                                     for l in lines],
        "tables": [_union(l.box for row in table for l in row) for table in tables],
    }
    return PageReading(page_index, page_label, width, height, tuple(cropbox), route, list(reasons), read, flags,
                       [], details["tables"], {}, {}, [], ocr=details)
