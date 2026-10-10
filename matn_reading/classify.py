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
VECTOR_CELL_MIN_OBJECTS = 3
VECTOR_REGION_MIN_OBJECTS = 12
VECTOR_REGION_MIN_AREA_PT2 = 3000.0
FIGURE_MIN_SHORT_NUMERIC_LABELS = 4
FIGURE_MAX_SHORT_LABEL_CHARS = 12
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
                   height: float, words: list[Word] | None = None) -> list[BBox]:
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
    # Sparse charts often have only axes, bars/curves and labels, so a density-only rule misses them.
    long_objects = [box for box in drawings if max(box[2] - box[0], box[3] - box[1]) >= 30]
    if words:
        remaining = set(range(len(long_objects)))
        while remaining:
            seed = remaining.pop()
            component, stack = [long_objects[seed]], [seed]
            while stack:
                index = stack.pop()
                current = long_objects[index]
                nearby = [other for other in remaining
                          if not (long_objects[other][2] + 12 < current[0]
                                  or current[2] + 12 < long_objects[other][0]
                                  or long_objects[other][3] + 12 < current[1]
                                  or current[3] + 12 < long_objects[other][1])]
                for other in nearby:
                    remaining.remove(other)
                    stack.append(other)
                    component.append(long_objects[other])
            if len(component) < 2:
                continue
            box = (max(0.0, min(item[0] for item in component) - 20),
                   max(0.0, min(item[1] for item in component) - 20),
                   min(width, max(item[2] for item in component) + 20),
                   min(height, max(item[3] for item in component) + 20))
            labels = [word for word in words if len(word.text) <= FIGURE_MAX_SHORT_LABEL_CHARS
                      and re.search(r"\d", word.text)
                      and _centre_in((word.x0, word.top, word.x1, word.bottom), [box])]
            axis_labels = any(word.vertical and _centre_in((word.x0, word.top, word.x1, word.bottom), [box])
                              for word in words)
            if axis_labels or len(labels) >= FIGURE_MIN_SHORT_NUMERIC_LABELS:
                regions.append(box)
    return [r for r in regions if (any(w.vertical and _centre_in((w.x0,w.top,w.x1,w.bottom),[r]) for w in (words or []))
                                   or not any(_overlap_share(r, t) > 0.5 for t in tables))]


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


# R-lite.1: precision-first prose-box thresholds fixed by synthetic fixtures.
PROSE_MIN_LINES=3
PROSE_MIN_WORDS_PER_LINE=4
PROSE_MULTIWORD_SHARE=0.8
PROSE_MIN_SENTENCE_ENDINGS=2
PROSE_MAX_NUMERIC_LABEL_LINES=3
PROSE_SIZE_TOLERANCE=0.6

def prose_box(region,lines,body,drawings=()):
    """No chart recovery: uncertain boxes remain figures with an explicit issue."""
    axes=[r for r in drawings if all((r[0]>=region[0],r[1]>=region[1],r[2]<=region[2],r[3]<=region[3])) and
          ((r[2]-r[0]<=1 and r[3]-r[1]>=30 and region[0]+3<r[0]<region[2]-3) or
           (r[3]-r[1]<=1 and r[2]-r[0]>=30 and region[1]+3<r[1]<region[3]-3))]
    if axes:return False
    members=[l for l in lines if _centre_in((l.x0,l.top,l.x1,l.bottom),[region])]
    if len(members)<PROSE_MIN_LINES or any(l.vertical for l in members):return False
    multi=[l for l in members if len(l.words)>=PROSE_MIN_WORDS_PER_LINE and abs(l.size-body)<=PROSE_SIZE_TOLERANCE]
    labels=[l for l in members if len(l.words)<=2 and re.search(r'\d',l.text)]
    endings=sum(bool(re.search(r'[.!?](?:[\"\']?)$',l.text.strip())) for l in members)
    return (len(multi)/len(members)>=PROSE_MULTIWORD_SHARE and endings>=PROSE_MIN_SENTENCE_ENDINGS
            and len(labels)<=PROSE_MAX_NUMERIC_LABEL_LINES)
