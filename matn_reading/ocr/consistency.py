"""Free internal consistency checks on OCR pages (frozen in docs/ocr_rules.md). A mismatch flags every number involved.

1. Table totals: a row whose label starts with "Total" (or "Totals", "Grand total", "All", "Sum") must equal the sum
   of the numbers above it in the same column, back to the previous total row; a column headed "Total" must equal
   the numbers to its left in the same row. Equality is within the rounding the printed numbers allow: half a unit
   of the finest shown decimal place per summed number. Year-like integers (1800-2100, no separator) are labels, not
   parts.
2. Text against tables: a number in the prose that differs from a table number on the same page by exactly one
   digit, or by one swap of adjacent digits (same length and same punctuation), is a likely misread of one of them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .numbers import number_tokens

BBox = tuple[float, float, float, float]
_TOTAL_LABEL = re.compile(r"^\s*(?:grand\s+)?(?:totals?|all|sum)\b", re.IGNORECASE)
_DECORATION = re.compile(r"[\s$%()*†‡§€£]+")
MIN_TEXT_TABLE_DIGITS = 3


@dataclass(frozen=True)
class Cell:
    text: str
    box: BBox
    ref: object = None             # caller's handle (e.g. the word), carried into issues


@dataclass
class Issue:
    kind: str                      # "table_total_mismatch" | "text_table_mismatch"
    cells: list[Cell] = field(default_factory=list)
    detail: str = ""


def cell_value(cell: Cell) -> tuple[float, int] | None:
    """(value, decimals) when the cell holds exactly one number and nothing but decoration around it."""
    tokens = number_tokens(cell.text)
    if len(tokens) != 1:
        return None
    rest = cell.text.replace(tokens[0], "", 1) if tokens[0] in cell.text else None
    if rest is None or _DECORATION.sub("", rest):
        return None
    token = tokens[0]
    decimals = len(token.split(".", 1)[1]) if "." in token else 0
    value = float(token.replace(",", ""))
    if "(" in cell.text and ")" in cell.text:
        value = -abs(value)         # accounting negative
    return value, decimals


def _is_year(cell: Cell) -> bool:
    tokens = number_tokens(cell.text)
    return len(tokens) == 1 and re.fullmatch(r"(?:18|19|20)\d\d|2100", tokens[0]) is not None


def _part(cell: Cell) -> tuple[float, int] | None:
    return None if _is_year(cell) else cell_value(cell)


def _same_column(a: BBox, b: BBox) -> bool:
    overlap = min(a[2], b[2]) - max(a[0], b[0])
    return overlap > 0.5 * min(a[2] - a[0], b[2] - b[0])


def _adds_up(total: tuple[float, int], parts: list[tuple[float, int]]) -> bool:
    decimals = max([total[1]] + [p[1] for p in parts])
    tolerance = 0.5 * 10 ** -decimals * len(parts) + 1e-9
    return abs(sum(p[0] for p in parts) - total[0]) <= tolerance


def check_table_totals(rows: list[list[Cell]]) -> list[Issue]:
    """``rows``: one table, top to bottom, cells left to right."""
    issues: list[Issue] = []
    start = 0
    for index, row in enumerate(rows):
        if not row or not _TOTAL_LABEL.match(row[0].text):
            continue
        for total_cell in row[1:]:
            total = cell_value(total_cell)
            if total is None:
                continue
            parts = [(cell, value) for above in rows[start:index] for cell in above[1:]
                     if _same_column(cell.box, total_cell.box) and (value := _part(cell)) is not None]
            if len(parts) >= 2 and not _adds_up(total, [v for _, v in parts]):
                issues.append(Issue("table_total_mismatch", [total_cell] + [c for c, _ in parts],
                                    f"column sum {sum(v[0] for _, v in parts):g} != {total_cell.text}"))
        start = index + 1
    headers = [cell for row in rows if row and all(_part(c) is None for c in row[1:])
               for cell in row[1:] if _TOTAL_LABEL.match(cell.text)]
    for header in headers:
        for row in rows:
            if not row or _TOTAL_LABEL.match(row[0].text):
                continue
            total_cell = next((c for c in row[1:] if _same_column(c.box, header.box)), None)
            total = cell_value(total_cell) if total_cell else None
            if total is None:
                continue
            parts = [(c, v) for c in row[1:] if c.box[2] <= total_cell.box[0] and (v := _part(c)) is not None]
            if len(parts) >= 2 and not _adds_up(total, [v for _, v in parts]):
                issues.append(Issue("table_total_mismatch", [total_cell] + [c for c, _ in parts],
                                    f"row sum {sum(v[0] for _, v in parts):g} != {total_cell.text}"))
    return issues


def _near_miss(a: str, b: str) -> bool:
    if a == b or len(a) != len(b) or re.sub(r"\d", "9", a) != re.sub(r"\d", "9", b):
        return False
    da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    if len(da) < MIN_TEXT_TABLE_DIGITS:
        return False
    diffs = [i for i, (x, y) in enumerate(zip(da, db)) if x != y]
    if len(diffs) == 1:
        return True
    return len(diffs) == 2 and diffs[1] == diffs[0] + 1 and da[diffs[0]] == db[diffs[1]] and da[diffs[1]] == db[diffs[0]]


def check_text_against_tables(prose: list[Cell], table: list[Cell]) -> list[Issue]:
    issues = []
    for p in prose:
        for p_token in number_tokens(p.text):
            for t in table:
                if any(_near_miss(p_token, t_token) for t_token in number_tokens(t.text)):
                    issues.append(Issue("text_table_mismatch", [p, t], f"{p_token} in text vs {t.text} in a table"))
    return issues
