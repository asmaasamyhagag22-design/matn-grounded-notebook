"""Read a born-digital PDF into matn_contracts Blocks, one route per page, with every uncertainty flagged.

Fail loud: a page whose route is not digital_healthy, figure text and words holding broken glyphs are flagged in
``PageReading.flags``; nothing is dropped silently. Hidden-text detection is NOT implemented yet (it waits for the
owner's approval of the visibility contract), so every block is ``Visibility.VISIBLE`` in this baseline.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from matn_contracts.domain import Block, BlockStyle, ExtractorInfo
from matn_contracts.enums import BlockType, ExtractionRoute, HiddenReason, Visibility

from .classify import body_size, block_type, figure_regions, prose_box
from .layout import LayoutBlock, Line, Word, detect_furniture, group_blocks, group_lines, order_blocks
from .pdf_page import EXTRACTOR_VERSION, OpenPdf, PageData
from .triage import Route, decide_route, glyph_issues

BBox = tuple[float, float, float, float]
_FOOTNOTE_PREFIX = re.compile(r"^(\d{1,3})(?=\D)")
_CODE_ASSIGNMENT = re.compile(r"\b[A-Za-z_]\w*\s*=\s*[^=]")
_CODE_CALL = re.compile(r"\b(?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*\(")
_CODE_KEYWORD = re.compile(r"(?:^|\s)(?:def|class|import|from|return|with|for|if|else|elif)\b")


@dataclass
class ReadBlock:
    """A block as read, before and alongside its contract form."""

    layout: LayoutBlock
    block_type: str
    flagged: bool
    bbox: BBox                     # padded so x0 < x1 and y0 < y1 (contract rule); raw box is layout.bbox
    contract: Block | None = None


@dataclass
class PageReading:
    page_index: int
    page_label: str | None
    width: float
    height: float
    cropbox: BBox
    route: Route
    reasons: list[str]
    blocks: list[ReadBlock]
    flags: list[dict]
    figure_regions: list[BBox]
    tables: list[BBox]
    edge_cases: dict
    signals: dict
    footnote_markers: list[dict] = field(default_factory=list)
    ocr: dict | None = None              # OCR route only: tokens, second reads, preprocessing record


@dataclass
class DocumentReading:
    doc_id: str
    path: str
    body_size: float
    pages: list[PageReading] = field(default_factory=list)


def doc_id_for(path: Path) -> str:
    return "sha256-" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _padded(box: BBox) -> BBox:
    x0, y0, x1, y1 = box
    return (x0, y0, x1 if x1 > x0 else x0 + 0.01, y1 if y1 > y0 else y0 + 0.01)


def _centre_in(box: BBox, regions: list[BBox]) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in regions)


def _line_box(line: Line) -> BBox:
    return (line.x0, line.top, line.x1, line.bottom)


def _table_block(lines: list[Line], rows: list[list[str]]) -> LayoutBlock:
    # Cell extraction is a structure observation, never a source-word ledger.
    # Some cells already took the prose/visibility branch; copying all rows
    # here duplicates them and invents local provenance (P1 M3).
    return LayoutBlock(sorted(lines, key=lambda l: (l.top, l.x0)), digital=True).finish()


def _looks_like_code(block: LayoutBlock) -> bool:
    text = block.raw_text
    signals = (
        bool(_CODE_ASSIGNMENT.search(text)),
        bool(_CODE_CALL.search(text)),
        bool(_CODE_KEYWORD.search(text)),
        any(line.lstrip().startswith("#") for line in text.splitlines()),
        len(re.findall(r"\b[A-Za-z]\w*_[A-Za-z]\w*\b", text)) >= 2,
    )
    return sum(signals) >= 2


def _split_footnote_prefix(block: LayoutBlock) -> Word | None:
    if not block.lines or not block.lines[0].words:
        return None
    first = block.lines[0].words[0]
    match = _FOOTNOTE_PREFIX.match(first.text)
    if not match:
        return None
    marker_text = match.group(1)
    split_x = first.x0 + (first.x1 - first.x0) * len(marker_text) / max(len(first.text), 1)
    marker = replace(first, text=marker_text, x1=split_x, kind="footnote_marker")
    remainder = replace(first, text=first.text[len(marker_text):], x0=split_x)
    block.lines[0].words[:1] = [marker, remainder]
    block.finish()
    return marker


def _read_page(page: PageData, lines: list[Line], furniture: dict[int, str], body: float,
               footnote_markers: list[Word]) -> PageReading:
    route, reasons = decide_route(page.signals)
    tables = [t["bbox"] for t in page.tables]
    regions = figure_regions(page.images, page.drawings, tables, page.width, page.height, page.words)
    filled=[r for r in page.filled_boxes if r[2]-r[0]>30 and r[3]-r[1]>30]
    prose_regions=[r for r in filled if prose_box(r,lines,body,page.drawings)]
    regions=[r for r in regions if not _centre_in(r,prose_regions)]
    possible=[r for r in filled if r not in prose_regions and any(len(l.words)>=4 and _centre_in(_line_box(l),[r]) for l in lines)]
    read: list[ReadBlock] = []
    flags: list[dict] = [{"kind":"possible_prose_in_figure","bbox":r} for r in possible]

    furniture_blocks, table_lines, figure_lines, marginalia_lines, prose_lines = [], {
        i: [] for i in range(len(tables))}, [], [], []
    for index, line in enumerate(lines):
        if line.vertical:
            marginalia_lines.append(line)
            continue
        if index in furniture:
            furniture_blocks.append((LayoutBlock([line]).finish(), furniture[index]))
            continue
        if _centre_in(_line_box(line), prose_regions):
            prose_lines.append(line)
        elif _centre_in(_line_box(line), regions):
            figure_lines.append(line)
        else:
            table_index = next((i for i, t in enumerate(tables) if _centre_in(_line_box(line), [t])), None)
            if table_index is not None:
                table_lines[table_index].append(line)
            else:
                prose_lines.append(line)

    body_blocks: list[tuple[LayoutBlock, str]] = []
    for index, collected in table_lines.items():
        if collected:
            body_blocks.append((_table_block(collected, page.tables[index]["rows"]), "table"))
    for block in group_blocks(figure_lines, digital_body=body):
        body_blocks.append((block, block_type(block, body, page.height, in_figure=True)))
    for block in group_blocks(marginalia_lines, digital_body=body):
        body_blocks.append((block, "figure"))  # contract figure = non-prose; the flag records the marginalia role
    for block in group_blocks(prose_lines, digital_body=body):
        body_blocks.append((block, block_type(block, body, page.height, in_figure=False)))

    ordered = order_blocks([b for b, _ in body_blocks], page.width)
    types = {id(b): t for b, t in body_blocks}
    headers = sorted((b for b, t in furniture_blocks if t == "header"), key=lambda b: (b.top, b.x0))
    footers = sorted((b for b, t in furniture_blocks if t == "footer"), key=lambda b: (b.top, b.x0))
    sequence = [(b, "header") for b in headers] + [(b, types[id(b)]) for b in ordered] + [(b, "footer") for b in footers]

    page_not_clean = route is not Route.DIGITAL_HEALTHY
    if page_not_clean:
        flags.append({"kind": "page_route", "route": route.value, "bbox": (0.0, 0.0, page.width, page.height)})
    if page.edge_cases.get("outside_cropbox", 0):
        flags.append({"kind": "outside_cropbox", "bbox": (0.0, 0.0, page.width, page.height),
                      "chars": page.edge_cases["outside_cropbox"], "severity": "warning"})
    for block, kind in sequence:
        broken = sum(glyph_issues(block.raw_text).values())
        hidden = block.visibility != "visible"
        marginalia = block.vertical
        code = kind == "text" and _looks_like_code(block)
        flagged = page_not_clean or kind == "figure" or broken > 0 or hidden or code
        if kind == "figure":
            flag_kind = "marginalia" if marginalia else "figure_text"
            flags.append({"kind": flag_kind, "bbox": block.bbox, "chars": len(block.text)})
        if hidden:
            reasons = list(block.visibility_reasons)
            severity = "error" if "covered_by_image" in reasons else "warning"
            flags.append({"kind": "hidden_text", "bbox": block.bbox, "chars": len(block.text),
                          "visibility": block.visibility, "reasons": reasons, "severity": severity})
        if code:
            flags.append({"kind": "code_text", "bbox": block.bbox, "chars": len(block.text),
                          "severity": "warning"})
        if broken:
            flags.append({"kind": "broken_glyph", "bbox": block.bbox, "count": broken})
        read.append(ReadBlock(block, kind, flagged, _padded(block.bbox)))

    for region in regions:
        flags.append({"kind": "figure_region", "bbox": region})
    marker_records = [{"text": marker.text, "bbox": (marker.x0, marker.top, marker.x1, marker.bottom),
                       "linked_footnote_order": None} for marker in footnote_markers]
    footnotes = [(index, block) for index, block in enumerate(read) if block.block_type == "footnote"]
    for index, block in footnotes:
        marker = _split_footnote_prefix(block.layout)
        if marker is not None:
            marker_records.append({"text": marker.text,
                                   "bbox": (marker.x0, marker.top, marker.x1, marker.bottom),
                                   "linked_footnote_order": index})
    for marker in marker_records:
        match = next((index for index, block in footnotes
                      if block.layout.text.lstrip().startswith(marker["text"])), None)
        if marker["linked_footnote_order"] is None:
            marker["linked_footnote_order"] = match
    marker_records = list({(marker["text"], tuple(round(value, 2) for value in marker["bbox"])): marker
                           for marker in marker_records}.values())
    return PageReading(page.page_index, page.page_label, page.width, page.height, page.cropbox, route, reasons, read, flags,
                       regions, tables, page.edge_cases, page.signals.__dict__.copy(), marker_records)


def read_document(path: Path, *, pages: list[int] | None = None) -> DocumentReading:
    path = Path(path)
    doc_id = doc_id_for(path)
    with OpenPdf(path) as pdf:
        indices = list(range(len(pdf))) if pages is None else pages
        page_data = [pdf.page(i) for i in indices]
    markers = [[word for word in page.words if word.kind == "footnote_marker"] for page in page_data]
    preliminary_body=body_size(w for p in page_data for w in p.words if not w.vertical)
    page_lines = [group_lines([word for word in page.words if word.kind != "footnote_marker"],digital_body=preliminary_body) for page in page_data]
    height = page_data[0].height if page_data else 792.0
    furniture = detect_furniture(page_lines, height)
    body = body_size(w for p, marks, lines in zip(page_data, furniture, page_lines)
                     for i, line in enumerate(lines) if i not in marks for w in line.words)
    reading = DocumentReading(doc_id, str(path), body)
    extractor = ExtractorInfo(name="matn_reading", version=EXTRACTOR_VERSION)
    for page, lines, marks, page_markers in zip(page_data, page_lines, furniture, markers):
        page_reading = _read_page(page, lines, marks, body, page_markers)
        for order, block in enumerate(page_reading.blocks):
            block.contract = Block.create(
                doc_id=doc_id, page_index=page.page_index, page_label=page.page_label, bbox=block.bbox,
                block_type=BlockType(block.block_type), text=block.layout.text, reading_order=order,
                style=BlockStyle(font_size_pt=block.layout.size if block.layout.size > 0 else None,
                                 is_bold=block.layout.bold),
                extractor=extractor, route=ExtractionRoute.TEXT_LAYER, visibility=Visibility(block.layout.visibility),
                visibility_reasons=tuple(HiddenReason(reason) for reason in block.layout.visibility_reasons))
        reading.pages.append(page_reading)
    return reading


def words_out(page: PageReading) -> list[tuple[Word, bool]]:
    """Every word the reader produced, with its flag (for the number metric)."""
    marker_texts = {marker["text"] for marker in page.footnote_markers}
    output = []
    for block in page.blocks:
        if block.block_type == "figure" or block.contract.visibility is not Visibility.VISIBLE:
            continue
        words = [word for line in block.layout.lines for word in line.words if word.kind != "footnote_marker"]
        if block.block_type == "footnote" and words:
            marker = next((text for text in marker_texts if words[0].text.startswith(text)), None)
            if marker:
                remainder = words[0].text[len(marker):]
                words = ([replace(words[0], text=remainder)] if remainder else []) + words[1:]
        output.extend((word, block.flagged) for word in words)
    return output
