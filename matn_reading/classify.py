"""Block types and figure regions from measured features.

Rules (each one is a named constant or regex so it can be reviewed on the overlays):
- header / footer: running lines found by ``layout.detect_furniture``;
- table: the lines inside a pdfplumber table (ruled tables only for now);
- figure: lines whose centre falls in an image region or in a dense vector-drawing region (figure text is excluded
  from prose and flagged); captions stay captions even when they touch the figure;
- caption: starts like "Figure 3", "Table 2.1", "Box 1", or "Source:" / "Note:";
- list_item: starts with a bullet or an enumerator;
- heading: font size >= HEADING_SIZE_RATIO x body size, or a short bold block that does not end like a sentence;
- footnote: smaller than the body by FOOTNOTE_SIZE_DELTA_PT and in the bottom part of the page;
- text: everything else.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

import numpy as np

from .layout import LayoutBlock, Word

HEADING_SIZE_RATIO = 1.15
HEADING_MAX_CHARS = 150
HEADING_MAX_LINES = 3
FOOTNOTE_SIZE_DELTA_PT = 1.0
FOOTNOTE_TOP_SHARE = 0.70
FIGURE_MIN_IMAGE_SHARE = 0.02         # an image smaller than 2% of the page is a logo/icon, not a figure region
VECTOR_CELL_PT = 20.0
VECTOR_CELL_MIN_OBJECTS = 4
VECTOR_REGION_MIN_OBJECTS = 25
VECTOR_REGION_MIN_AREA_PT2 = 6000.0
CAPTION = re.compile(r"^(?:(?:Figure|Fig\.|Table|Box|Chart|Exhibit|Map)\s+[A-Z]?\d+(?:[.\-]\d+)*\b|"
                     r"(?:Sources?|Notes?)\s*:)")

BBox = tuple[float, float, float, float]


def body_size(words: Iterable[Word]) -> float:
    """The font size that carries the most characters (the body text size of the document)."""
    weight: Counter[float] = Counter()
    for word in words:
        weight[round(word.size * 2) / 2] += len(word.text)
    return weight.most_common(1)[0][0] if weight else 10.0


def _centre_in(box: BBox, regions: Iterable[BBox]) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in regions)


def _overlap_share(inner: BBox, outer: BBox) -> float:
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    return ix * iy / max((inner[2] - inner[0]) * (inner[3] - inner[1]), 1e-9)


def figure_regions(images: list[BBox], drawings: list[BBox], tables: list[BBox], width: float,
                   height: float) -> list[BBox]:
    """Image regions above FIGURE_MIN_IMAGE_SHARE plus connected clusters of dense vector drawing, minus tables."""
    regions = [img for img in images if (img[2] - img[0]) * (img[3] - img[1]) >= FIGURE_MIN_IMAGE_SHARE * width * height]
    cols, rows = int(np.ceil(width / VECTOR_CELL_PT)), int(np.ceil(height / VECTOR_CELL_PT))
    counts = np.zeros((rows, cols), dtype=int)
    for x0, top, x1, bottom in drawings:
        cx, cy = (x0 + x1) / 2, (top + bottom) / 2
        if 0 <= cx < width and 0 <= cy < height:
            counts[int(cy // VECTOR_CELL_PT), int(cx // VECTOR_CELL_PT)] += 1
    dense = counts >= VECTOR_CELL_MIN_OBJECTS
    seen = np.zeros_like(dense)
    for r in range(rows):
        for c in range(cols):
            if not dense[r, c] or seen[r, c]:
                continue
            stack, cells = [(r, c)], []
            seen[r, c] = True
            while stack:
                y, x = stack.pop()
                cells.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < rows and 0 <= nx < cols and dense[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            objects = sum(counts[y, x] for y, x in cells)
            ys, xs = [y for y, _ in cells], [x for _, x in cells]
            box = (min(xs) * VECTOR_CELL_PT, min(ys) * VECTOR_CELL_PT, (max(xs) + 1) * VECTOR_CELL_PT,
                   (max(ys) + 1) * VECTOR_CELL_PT)
            if objects >= VECTOR_REGION_MIN_OBJECTS and (box[2] - box[0]) * (box[3] - box[1]) >= VECTOR_REGION_MIN_AREA_PT2:
                regions.append(box)
    return [r for r in regions if not any(_overlap_share(r, t) > 0.5 for t in tables)]


def block_type(block: LayoutBlock, body: float, page_height: float, in_figure: bool) -> str:
    text = block.text.strip()
    if CAPTION.match(text):
        return "caption"
    if in_figure:
        return "figure"
    if block.lines[0].starts_with_bullet:
        return "list_item"
    if block.size >= HEADING_SIZE_RATIO * body and len(text) <= 3 * HEADING_MAX_CHARS:
        return "heading"
    if (block.bold and len(text) <= HEADING_MAX_CHARS and len(block.lines) <= HEADING_MAX_LINES
            and not text.endswith((".", ",", ";", ":"))):
        return "heading"
    if block.size <= body - FOOTNOTE_SIZE_DELTA_PT and block.top >= FOOTNOTE_TOP_SHARE * page_height:
        return "footnote"
    return "text"
