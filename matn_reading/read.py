"""Read a born-digital PDF into matn_contracts Blocks, one route per page, with every uncertainty flagged.

Fail loud: a page whose route is not digital_healthy, figure text and words holding broken glyphs are flagged in
``PageReading.flags``; nothing is dropped silently. Hidden-text detection is NOT implemented yet (it waits for the
owner's approval of the visibility contract), so every block is ``Visibility.VISIBLE`` in this baseline.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from matn_contracts.domain import Block, BlockStyle, ExtractorInfo
from matn_contracts.enums import BlockType, ExtractionRoute, Visibility

from .classify import body_size, block_type, figure_regions
from .layout import LayoutBlock, Line, Word, detect_furniture, group_blocks, group_lines, order_blocks
from .pdf_page import EXTRACTOR_VERSION, OpenPdf, PageData
from .triage import Route, decide_route, glyph_issues

BBox = tuple[float, float, float, float]


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
    route: Route
    reasons: list[str]
    blocks: list[ReadBlock]
    flags: list[dict]
    figure_regions: list[BBox]
    tables: list[BBox]
    edge_cases: dict
    signals: dict


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
    block = LayoutBlock(sorted(lines, key=lambda l: (l.top, l.x0))).finish()
    block.text = "\n".join(" | ".join(cell.replace("\n", " ") for cell in row) for row in rows)
    return block


def _read_page(page: PageData, lines: list[Line], furniture: dict[int, str], body: float) -> PageReading:
    route, reasons = decide_route(page.signals)
    tables = [t["bbox"] for t in page.tables]
    regions = figure_regions(page.images, page.drawings, tables, page.width, page.height)
    read: list[ReadBlock] = []
    flags: list[dict] = []

    furniture_blocks, table_lines, figure_lines, prose_lines = [], {i: [] for i in range(len(tables))}, [], []
    for index, line in enumerate(lines):
        if index in furniture:
            furniture_blocks.append((LayoutBlock([line]).finish(), furniture[index]))
            continue
        table_index = next((i for i, t in enumerate(tables) if _centre_in(_line_box(line), [t])), None)
        if table_index is not None:
            table_lines[table_index].append(line)
        elif _centre_in(_line_box(line), regions):
            figure_lines.append(line)
        else:
            prose_lines.append(line)

    body_blocks: list[tuple[LayoutBlock, str]] = []
    for index, collected in table_lines.items():
        if collected:
            body_blocks.append((_table_block(collected, page.tables[index]["rows"]), "table"))
    for block in group_blocks(figure_lines):
        body_blocks.append((block, block_type(block, body, page.height, in_figure=True)))
    for block in group_blocks(prose_lines):
        body_blocks.append((block, block_type(block, body, page.height, in_figure=False)))

    ordered = order_blocks([b for b, _ in body_blocks], page.width)
    types = {id(b): t for b, t in body_blocks}
    headers = sorted((b for b, t in furniture_blocks if t == "header"), key=lambda b: (b.top, b.x0))
    footers = sorted((b for b, t in furniture_blocks if t == "footer"), key=lambda b: (b.top, b.x0))
    sequence = [(b, "header") for b in headers] + [(b, types[id(b)]) for b in ordered] + [(b, "footer") for b in footers]

    page_not_clean = route is not Route.DIGITAL_HEALTHY
    if page_not_clean:
        flags.append({"kind": "page_route", "route": route.value, "bbox": (0.0, 0.0, page.width, page.height)})
    for block, kind in sequence:
        broken = sum(glyph_issues(block.raw_text).values())
        flagged = page_not_clean or kind == "figure" or broken > 0
        if kind == "figure":
            flags.append({"kind": "figure_text", "bbox": block.bbox, "chars": len(block.text)})
        if broken:
            flags.append({"kind": "broken_glyph", "bbox": block.bbox, "count": broken})
        read.append(ReadBlock(block, kind, flagged, _padded(block.bbox)))

    for region in regions:
        flags.append({"kind": "figure_region", "bbox": region})
    return PageReading(page.page_index, page.page_label, page.width, page.height, route, reasons, read, flags,
                       regions, tables, page.edge_cases, page.signals.__dict__.copy())


def read_document(path: Path, *, pages: list[int] | None = None) -> DocumentReading:
    path = Path(path)
    doc_id = doc_id_for(path)
    with OpenPdf(path) as pdf:
        indices = list(range(len(pdf))) if pages is None else pages
        page_data = [pdf.page(i) for i in indices]
    page_lines = [group_lines(p.words) for p in page_data]
    height = page_data[0].height if page_data else 792.0
    furniture = detect_furniture(page_lines, height)
    body = body_size(w for p, marks, lines in zip(page_data, furniture, page_lines)
                     for i, line in enumerate(lines) if i not in marks for w in line.words)
    reading = DocumentReading(doc_id, str(path), body)
    extractor = ExtractorInfo(name="matn_reading", version=EXTRACTOR_VERSION)
    for page, lines, marks in zip(page_data, page_lines, furniture):
        page_reading = _read_page(page, lines, marks, body)
        for order, block in enumerate(page_reading.blocks):
            block.contract = Block.create(
                doc_id=doc_id, page_index=page.page_index, page_label=page.page_label, bbox=block.bbox,
                block_type=BlockType(block.block_type), text=block.layout.text, reading_order=order,
                style=BlockStyle(font_size_pt=block.layout.size if block.layout.size > 0 else None,
                                 is_bold=block.layout.bold),
                extractor=extractor, route=ExtractionRoute.TEXT_LAYER, visibility=Visibility.VISIBLE)
        reading.pages.append(page_reading)
    return reading


def words_out(page: PageReading) -> list[tuple[Word, bool]]:
    """Every word the reader produced, with its flag (for the number metric)."""
    return [(word, block.flagged) for block in page.blocks for line in block.layout.lines for word in line.words]
