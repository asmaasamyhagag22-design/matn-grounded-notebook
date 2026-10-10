"""Layout on word boxes: lines, blocks, columns, reading order, hyphenation, repeated headers/footers.

Coordinates are PDF points with a top-left origin (pdfplumber's ``x0, top, x1, bottom``). Everything here is pure
Python on boxes, so the rules are unit-tested on synthetic layouts and then checked by the owner on real pages
(``reports/step4-reading-review.md``).

Reading order (column method, not plain XY-cut, which interleaves columns whose paragraph gaps line up):
1. gutters are found from the x-projection of the *narrow* blocks only (a full-width caption must not hide the
   gutter it crosses);
2. a block that crosses a gutter is "spanning"; the spanning blocks cut the page into vertical segments;
3. inside a segment, column blocks are read column by column, top to bottom; a narrow margin column of short blocks
   (side headings) is interleaved with its neighbour by vertical position instead of being read as its own column.
4. with no gutter (the side headings are then often the only narrow blocks), plain top-to-bottom order is kept, and
   only a heading-like block in the left margin moves in front of the body paragraph it sits beside
   (``lead_side_headings``).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from statistics import median

LINE_SPLIT_GAP_EM = 1.5        # a horizontal gap wider than this (in font sizes) splits a line (column gutter, cell)
PARA_GAP_EM = 0.6              # a vertical gap wider than this between lines starts a new block
SIZE_TOLERANCE_PT = 0.6        # lines whose font sizes differ more than this never share a block
NARROW_SHARE = 0.55            # a block narrower than this share of the content width can define a gutter
MIN_GUTTER_PT = 12.0
MARGIN_COLUMN_SHARE = 0.30     # a column narrower than this share of the page and than half its right neighbour,
MARGIN_COLUMN_MAX_LINES = 3    # whose blocks have at most this many lines, is a margin column (side headings)
SIDE_HEADING_TOP_TOLERANCE = 0.50
FURNITURE_BAND_SHARE = 0.08    # top/bottom band where running headers and footers live
FURNITURE_MIN_PAGES = 3
FURNITURE_MIN_SHARE = 0.30
_BULLET = re.compile(r"^(?:[•▪●◦‣⁃∙\-–—*]|\(?[0-9]{1,2}[.)]|\(?[a-z][.)])$")


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    size: float = 10.0
    bold: bool = False
    kind: str = "word"
    vertical: bool = False
    visibility: str = "visible"
    visibility_reasons: tuple[str, ...] = ()
    font_face: str = ""


@dataclass
class Line:
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def size(self) -> float:
        return round(median(w.size for w in self.words), 2)

    @property
    def bold(self) -> bool:
        weight = sum(len(w.text) for w in self.words if w.bold)
        return weight * 2 > sum(len(w.text) for w in self.words)

    @property
    def starts_with_bullet(self) -> bool:
        return bool(_BULLET.match(self.words[0].text))

    @property
    def vertical(self) -> bool:
        return all(word.vertical for word in self.words)

    @property
    def visibility(self) -> str:
        return self.words[0].visibility

    @property
    def visibility_reasons(self) -> tuple[str, ...]:
        return self.words[0].visibility_reasons


@dataclass
class LayoutBlock:
    lines: list[Line] = field(default_factory=list)
    text: str = ""
    raw_text: str = ""

    @property
    def x0(self) -> float:
        return min(line.x0 for line in self.lines)

    @property
    def x1(self) -> float:
        return max(line.x1 for line in self.lines)

    @property
    def top(self) -> float:
        return min(line.top for line in self.lines)

    @property
    def bottom(self) -> float:
        return max(line.bottom for line in self.lines)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.x0, self.top, self.x1, self.bottom)

    @property
    def size(self) -> float:
        return round(median(line.size for line in self.lines), 2)

    @property
    def bold(self) -> bool:
        return all(line.bold for line in self.lines)

    @property
    def vertical(self) -> bool:
        return all(line.vertical for line in self.lines)

    @property
    def visibility(self) -> str:
        return self.lines[0].visibility

    @property
    def visibility_reasons(self) -> tuple[str, ...]:
        return self.lines[0].visibility_reasons

    def finish(self) -> "LayoutBlock":
        self.text, self.raw_text = join_hyphenation([line.text for line in self.lines])
        return self


# ---- lines -------------------------------------------------------------------------------------------------------

def group_lines(words: Sequence[Word], *, digital_body: float | None = None) -> list[Line]:
    """Words whose vertical centres fall within half a line height form a row; a wide horizontal gap splits the row."""
    rows: list[list[Word]] = []
    for word in sorted(words, key=lambda w: ((w.top + w.bottom) / 2, w.x0)):
        centre = (word.top + word.bottom) / 2
        if rows:
            row = rows[-1]
            row_centre = median((w.top + w.bottom) / 2 for w in row)
            height = median(w.bottom - w.top for w in row)
            if abs(centre - row_centre) <= 0.5 * max(height, word.bottom - word.top):
                row.append(word)
                continue
        rows.append([word])
    lines: list[Line] = []
    for row in rows:
        row.sort(key=lambda w: w.x0)
        current = [row[0]]
        for previous, word in zip(row, row[1:]):
            state_changed = (word.visibility, word.visibility_reasons, word.vertical) != (
                previous.visibility, previous.visibility_reasons, previous.vertical)
            inline_face = (digital_body is not None and previous.font_face != word.font_face
                           and abs(previous.size-digital_body)<=SIZE_TOLERANCE_PT
                           and abs(word.size-digital_body)<=SIZE_TOLERANCE_PT
                           and abs(previous.bottom-word.bottom)<=0.2*digital_body
                           and word.x0-previous.x1<=2.0*digital_body)
            if state_changed or (word.x0 - previous.x1 > LINE_SPLIT_GAP_EM * max(previous.size, word.size) and not inline_face):
                lines.append(Line(current))
                current = []
            current.append(word)
        lines.append(Line(current))
    return sorted(lines, key=lambda line: (line.top, line.x0))


# ---- blocks ------------------------------------------------------------------------------------------------------

def _x_overlap(a: Line, b: Line) -> float:
    overlap = min(a.x1, b.x1) - max(a.x0, b.x0)
    return overlap / max(min(a.x1 - a.x0, b.x1 - b.x0), 1e-6)


def _continues(block: LayoutBlock, line: Line, digital_body: float | None = None) -> bool:
    last = block.lines[-1]
    gap = line.top - last.bottom
    if gap < -0.5 * line.size or gap > PARA_GAP_EM * max(line.size, last.size):
        return False
    if abs(line.size - last.size) > SIZE_TOLERANCE_PT:
        return False
    if line.bold != last.bold:
        bold_lead = block.lines[0].bold and not line.bold and block.lines[-1].text.rstrip().endswith((".", ":"))
        body_run = digital_body is not None and abs(line.size-digital_body)<=SIZE_TOLERANCE_PT and abs(last.size-digital_body)<=SIZE_TOLERANCE_PT
        if not bold_lead and not body_run:
            return False
    if (line.visibility, line.visibility_reasons, line.vertical) != (
            last.visibility, last.visibility_reasons, last.vertical):
        return False
    if line.starts_with_bullet:
        return False
    return _x_overlap(last, line) >= 0.5 or abs(line.x0 - last.x0) <= 2.0


def group_blocks(lines: Sequence[Line], *, digital_body: float | None = None) -> list[LayoutBlock]:
    """Consecutive lines that sit directly under each other with the same style form a block."""
    blocks: list[LayoutBlock] = []
    for line in sorted(lines, key=lambda line: (line.top, line.x0)):
        target = None
        for block in reversed(blocks[-8:]):  # only recent blocks can be directly above
            if _continues(block, line, digital_body):
                target = block
                break
        if target is None:
            blocks.append(LayoutBlock([line]))
        else:
            target.lines.append(line)
    return [block.finish() for block in blocks]


# ---- reading order -----------------------------------------------------------------------------------------------

def find_gutters(blocks: Sequence[LayoutBlock]) -> list[tuple[float, float]]:
    if len(blocks) < 2:
        return []
    left, right = min(b.x0 for b in blocks), max(b.x1 for b in blocks)
    narrow = sorted((b for b in blocks if b.x1 - b.x0 < NARROW_SHARE * (right - left)), key=lambda b: b.x0)
    if len(narrow) < 2:
        return []
    merged: list[list[float]] = []
    for block in narrow:
        if merged and block.x0 <= merged[-1][1] + 1.0:
            merged[-1][1] = max(merged[-1][1], block.x1)
        else:
            merged.append([block.x0, block.x1])
    return [(a[1], b[0]) for a, b in zip(merged, merged[1:]) if b[0] - a[1] >= MIN_GUTTER_PT]


def lead_side_headings(ordered: Sequence[LayoutBlock], page_width: float) -> list[LayoutBlock]:
    """Move each side heading in front of the paragraph it labels; every other block keeps its place.

    A side heading starts at the left edge, is short and narrow, and is larger or bolder than a body block that starts
    right of it (past a gutter) with a top within the side-heading tolerance. Without a gutter the column rule above
    never sees the margin column, so a heading whose top sits a few points below its paragraph's top would follow it.
    """
    result = list(ordered)
    if len(result) < 2:
        return result
    left = min(b.x0 for b in result)
    sides = [b for b in result if b.x0 <= left + 2.0 and len(b.lines) <= MARGIN_COLUMN_MAX_LINES
             and b.x1 - b.x0 < MARGIN_COLUMN_SHARE * page_width]
    for side in sides:
        peers = [b for b in result if b is not side and b.x0 >= side.x1 + MIN_GUTTER_PT
                 and abs(b.top - side.top) <= SIDE_HEADING_TOP_TOLERANCE * max(b.size, side.size)
                 and (side.size > b.size + SIZE_TOLERANCE_PT or (side.bold and not b.bold))]
        if not peers:
            continue
        body = min(peers, key=lambda b: (abs(b.top - side.top), b.x0))
        if result.index(side) > result.index(body):
            result.remove(side)
            result.insert(result.index(body), side)
    return result


def order_blocks(blocks: Sequence[LayoutBlock], page_width: float) -> list[LayoutBlock]:
    gutters = find_gutters(blocks)
    if not gutters:
        return lead_side_headings(sorted(blocks, key=lambda b: (b.top, b.x0)), page_width)

    def crosses(block: LayoutBlock, gutter: tuple[float, float]) -> bool:
        return block.x0 < gutter[0] - 1.0 and block.x1 > gutter[1] + 1.0

    edges = [-math.inf] + [(g[0] + g[1]) / 2 for g in gutters] + [math.inf]
    spanning = sorted((b for b in blocks if any(crosses(b, g) for g in gutters)), key=lambda b: b.top)
    columns: dict[int, list[LayoutBlock]] = {}
    for block in blocks:
        if block in spanning:
            continue
        centre = (block.x0 + block.x1) / 2
        index = next(i for i in range(len(edges) - 1) if edges[i] <= centre < edges[i + 1])
        columns.setdefault(index, []).append(block)

    # Margin columns (side headings) are merged into their right-hand neighbour and read by vertical position.
    merged_into = {}
    margin_blocks: set[int] = set()
    for index in sorted(columns):
        members = columns[index]
        width = max(b.x1 for b in members) - min(b.x0 for b in members)
        short = all(len(b.lines) <= MARGIN_COLUMN_MAX_LINES for b in members)
        neighbour = index + 1 if index + 1 in columns else None
        if neighbour is None:
            continue
        neighbour_width = max(b.x1 for b in columns[neighbour]) - min(b.x0 for b in columns[neighbour])
        if width < MARGIN_COLUMN_SHARE * page_width and width < 0.5 * neighbour_width and short:
            merged_into[index] = neighbour
            margin_blocks.update(id(block) for block in members)
    for index, target in sorted(merged_into.items(), reverse=True):
        while target in merged_into:
            target = merged_into[target]
        columns.setdefault(target, []).extend(columns.pop(index))

    def segment(block: LayoutBlock) -> int:
        return sum(1 for s in spanning if s.bottom <= block.top + 1.0)

    ordered: list[LayoutBlock] = []
    for seg in range(len(spanning) + 1):
        for index in sorted(columns):
            members = sorted((b for b in columns[index] if segment(b) == seg), key=lambda b: (b.top, b.x0))
            # A side heading may sit a few points lower than the paragraph it labels. Within half a line height,
            # semantic order wins over the raw top coordinate.
            for side in [b for b in members if id(b) in margin_blocks]:
                peers = [b for b in members if id(b) not in margin_blocks
                         and abs(b.top - side.top) <= SIDE_HEADING_TOP_TOLERANCE * max(b.size, side.size)]
                if peers:
                    body = min(peers, key=lambda b: (abs(b.top - side.top), b.x0))
                    members.remove(side)
                    members.insert(members.index(body), side)
            ordered += members
        if seg < len(spanning):
            ordered.append(spanning[seg])
    return ordered


# ---- hyphenation -------------------------------------------------------------------------------------------------

def join_hyphenation(lines: Sequence[str]) -> tuple[str, str]:
    """Join lines into one text. A line-end hyphen after a letter, followed by a lowercase letter, is a word break and
    is removed ("govern-" + "ment"). Before a digit or capital it is kept and joined without a space ("2019-2021",
    "COVID-19"). Returns (joined, raw) where raw keeps the original line breaks."""
    raw = "\n".join(lines)
    out = ""
    for index, line in enumerate(lines):
        line = line.strip()
        if index == 0:
            out = line
            continue
        if out.endswith("-") and len(out) >= 2 and line:
            before, after = out[-2], line[0]
            if before.isalpha() and after.islower():
                out = out[:-1] + line
                continue
            if before.isalnum() and (after.isdigit() or after.isupper()):
                out = out + line
                continue
        out = f"{out} {line}" if out else line
    return out, raw


# ---- running headers and footers ---------------------------------------------------------------------------------

def _furniture_key(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", text.lower())).strip()


def detect_furniture(pages: Sequence[Sequence[Line]], page_height: float) -> list[dict[int, str]]:
    """For each page, {line index: "header" | "footer"} for lines in the top/bottom band whose digit-normalized text
    repeats on enough pages. A bare page number in the band is furniture even when it is the only repeat."""
    band = FURNITURE_BAND_SHARE * page_height

    def zone(line: Line) -> str | None:
        if line.bottom <= band:
            return "header"
        if line.top >= page_height - band:
            return "footer"
        return None

    counts: Counter[tuple[str, str]] = Counter()
    for lines in pages:
        counts.update({(z, _furniture_key(line.text)) for line in lines if (z := zone(line))})
    needed = max(FURNITURE_MIN_PAGES, math.ceil(FURNITURE_MIN_SHARE * len(pages)))
    result: list[dict[int, str]] = []
    for lines in pages:
        marks: dict[int, str] = {}
        for index, line in enumerate(lines):
            z = zone(line)
            if z is None:
                continue
            key = _furniture_key(line.text)
            if counts[(z, key)] >= needed or re.fullmatch(r"(?:page )?[-– ]*#[-– ]*|[ivxlc]+", key):
                marks[index] = z
        result.append(marks)
    return result
