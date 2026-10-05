"""Reading metrics for Step 4: CER, WER, exact numbers, silent errors, TEDS, reading order, block types.

The key metric is ``silent_errors``: a number that the reader got wrong (substituted, or invented where the source
has none) and did NOT flag. Its target is 0. A number the reader dropped without a flag is counted separately as a
``silent_drop`` (an omission, not a wrong value). A wrong number that the reader flagged is ``flagged_wrong``: it
costs accuracy, but nothing downstream will trust it.

Numbers are tokenized with ``matn_contracts.conversion.numeric_tokens``, the same tokenizer that verifies number facts
against quotes, so "exact" here means exactly what the fact check will see.

Everything is pure Python with no dependency: the tree edit distance behind TEDS (Zhang-Shasha) is implemented here.
"""
from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import re
from typing import Any

BBox = tuple[float, float, float, float]
PAGE_TYPES = ("digital", "synthetic_scan", "real_scan")


# ---- edit distance, CER, WER -------------------------------------------------------------------------------------

def levenshtein(a: Sequence[Any], b: Sequence[Any]) -> int:
    """Unit-cost edit distance between two sequences (strings or lists)."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, item_a in enumerate(a, start=1):
        current = [i]
        for j, item_b in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (item_a != item_b)))
        previous = current
    return previous[-1]


def _ratio(edits: int, length: int) -> float:
    if length == 0:
        return 0.0 if edits == 0 else 1.0
    return edits / length


# Frozen normalization table (docs/reading_eval_rules.md section 1). Its sha256 is pinned by
# eval/tests/test_reading_rules_frozen.py; changing it needs the owner's approval.
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st",
             "ﬆ": "st"}                                                                   # N2
INVISIBLE = {"­": "", "​": "", "‌": "", "‍": "", "⁠": "", "﻿": ""}  # N3
QUOTES = {"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
          "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"', "«": '"',
          "»": '"'}                                                                      # N4
DASHES = {"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
          "−": "-"}                                                                      # N5
ELLIPSIS = {"…": "..."}                                                                   # N6
NORMALIZATION_TABLE = {"N2": LIGATURES, "N3": INVISIBLE, "N4": QUOTES, "N5": DASHES, "N6": ELLIPSIS}
_CER_MAP = str.maketrans({**LIGATURES, **INVISIBLE, **QUOTES, **DASHES, **ELLIPSIS})
_NUMBER_MAP = str.maketrans({**INVISIBLE, **DASHES})


def normalize_whitespace(text: str) -> str:
    return " ".join(text.split())                                                              # N7


def normalize_for_cer(text: str) -> str:
    """N1 NFC, N2-N6 character maps, N7 whitespace; N8 case kept."""
    return normalize_whitespace(unicodedata.normalize("NFC", text).translate(_CER_MAP))


def normalize_for_numbers(text: str) -> str:
    """Only N1, N3, N5, N7 before number tokenizing: no change ever touches a digit."""
    return normalize_whitespace(unicodedata.normalize("NFC", text).translate(_NUMBER_MAP))


def cer(reference: str, hypothesis: str) -> float:
    """Character error rate after the frozen normalization: edits / reference characters."""
    ref, hyp = normalize_for_cer(reference), normalize_for_cer(hypothesis)
    return _ratio(levenshtein(ref, hyp), len(ref))


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate after the frozen normalization: edits over tokens / reference tokens."""
    ref, hyp = normalize_for_cer(reference).split(), normalize_for_cer(hypothesis).split()
    return _ratio(levenshtein(ref, hyp), len(ref))


# ---- numbers -----------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Word:
    """One word as read. ``bbox`` is optional (hand ground truth may have none); ``flagged`` = the reader marked it
    (or the region holding it) as uncertain."""

    text: str
    bbox: BBox | None = None
    flagged: bool = False


@dataclass
class NumberReport:
    total: int = 0            # numeric tokens in the ground truth
    correct: int = 0
    wrong: int = 0            # substituted (a different number at the same place)
    missing: int = 0          # no number at the place
    inserted: int = 0         # a number where the ground truth has none
    silent_errors: int = 0    # wrong or inserted, and not flagged  -> target 0
    silent_drops: int = 0     # missing and not flagged
    flagged_wrong: int = 0    # wrong or inserted, but flagged
    flagged_total: int = 0    # reference numbers inside a region the reader flagged
    unflagged_total: int = 0  # reference numbers outside flagged regions (the accuracy denominator, rules section 2)
    unflagged_correct: int = 0
    details: list[dict] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return 1.0 if self.total == 0 else self.correct / self.total

    @property
    def unflagged_accuracy(self) -> float:
        return 1.0 if self.unflagged_total == 0 else self.unflagged_correct / self.unflagged_total

    def add(self, other: "NumberReport") -> None:
        for name in ("total", "correct", "wrong", "missing", "inserted", "silent_errors", "silent_drops",
                     "flagged_wrong", "flagged_total", "unflagged_total", "unflagged_correct"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.details.extend(other.details)


_READER_NUMBER = re.compile(
    r"(?<![\d.,])[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?!\d|[.,]\d)"
    r"|(?<![\w.,])[+-]?\.\d+(?!\d|[.,]\d)"
)


def reader_numeric_tokens(text: str) -> list[re.Match[str]]:
    """Reader/metric numbers start at digit transitions, even when glued to letters.

    The fact verifier's stricter exact-token tokenizer is intentionally unchanged.
    """
    return list(_READER_NUMBER.finditer(text))


def _numbers(text: str) -> list[str]:
    return [match.group(0) for match in reader_numeric_tokens(normalize_for_numbers(text))]


def _overlap(a: BBox, b: BBox) -> float:
    """Intersection over the smaller box: a word read slightly larger or smaller still matches its place."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return 0.0 if smaller <= 0 else ix * iy / smaller


def _record(report: NumberReport, status: str, expected: str | None, got: str | None, flagged: bool,
            where: Any) -> None:
    if status == "correct":
        report.correct += 1
    elif status == "missing":
        report.missing += 1
        report.silent_drops += not flagged
    else:
        setattr(report, status, getattr(report, status) + 1)  # "wrong" or "inserted"
        if flagged:
            report.flagged_wrong += 1
        else:
            report.silent_errors += 1
    if status != "correct":
        report.details.append({"status": status, "expected": expected, "got": got, "flagged": flagged,
                               "where": where})


def _compare_tokens(report: NumberReport, expected: list[str], got: list[tuple[str, bool]], where: Any,
                    region_flagged: bool = False) -> None:
    """Multiset comparison inside one place (a word): exact matches first, then pair the rest as substitutions.
    ``region_flagged``: the place lies in a region the reader flagged, so a drop there is not silent."""
    remaining = Counter(token for token, _ in got)
    leftovers_expected = []
    if region_flagged:
        report.flagged_total += len(expected)
    else:
        report.unflagged_total += len(expected)
    for token in expected:
        if remaining[token] > 0:
            remaining[token] -= 1
            report.unflagged_correct += not region_flagged
            _record(report, "correct", token, token, False, where)
        else:
            leftovers_expected.append(token)
    leftovers_got = []
    for token, flagged in got:
        if remaining[token] > 0:
            remaining[token] -= 1
            leftovers_got.append((token, flagged))
    for index, token in enumerate(leftovers_expected):
        if index < len(leftovers_got):
            _record(report, "wrong", token, leftovers_got[index][0],
                    region_flagged or leftovers_got[index][1], where)
        else:
            _record(report, "missing", token, None, region_flagged, where)
    for token, flagged in leftovers_got[len(leftovers_expected):]:
        _record(report, "inserted", None, token, region_flagged or flagged, where)


def _in_regions(box: BBox, regions: Sequence[BBox]) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in regions)


def _score_spatial(gt: Sequence[Word], hyp: Sequence[Word], flagged_regions: Sequence[BBox] = ()) -> NumberReport:
    report = NumberReport(total=sum(len(_numbers(w.text)) for w in gt))
    assigned: dict[int, list[Word]] = {}
    for word in hyp:
        best, best_overlap = None, 0.3
        for index, target in enumerate(gt):
            overlap = _overlap(word.bbox, target.bbox)  # type: ignore[arg-type]
            if overlap > best_overlap:
                best, best_overlap = index, overlap
        if best is None:
            for token in _numbers(word.text):
                _record(report, "inserted", None, token, word.flagged, word.bbox)
        else:
            assigned.setdefault(best, []).append(word)
    for index, target in enumerate(gt):
        words = sorted(assigned.get(index, []), key=lambda w: (w.bbox[0], w.bbox[1]))  # type: ignore[index]
        got = [(token, w.flagged) for w in words for token in _numbers(w.text)]
        expected = _numbers(target.text)
        if expected or got:
            _compare_tokens(report, expected, got, target.bbox,
                            _in_regions(target.bbox, flagged_regions))  # type: ignore[arg-type]
    return report


def _score_sequence(gt: Sequence[Word], hyp: Sequence[Word]) -> NumberReport:
    expected = [token for w in gt for token in _numbers(w.text)]
    got = [(token, w.flagged) for w in hyp for token in _numbers(w.text)]
    report = NumberReport(total=len(expected), unflagged_total=len(expected))
    n, m = len(expected), len(got)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        cost[i][0] = i
    for j in range(m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost[i][j] = min(cost[i - 1][j] + 1, cost[i][j - 1] + 1,
                             cost[i - 1][j - 1] + (expected[i - 1] != got[j - 1][0]))
    i, j, steps = n, m, []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and cost[i][j] == cost[i - 1][j - 1] + (expected[i - 1] != got[j - 1][0]):
            steps.append(("correct" if expected[i - 1] == got[j - 1][0] else "wrong", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and cost[i][j] == cost[i - 1][j] + 1:
            steps.append(("missing", i - 1, None))
            i -= 1
        else:
            steps.append(("inserted", None, j - 1))
            j -= 1
    for status, a, b in reversed(steps):
        token_expected = expected[a] if a is not None else None
        token_got, flagged = got[b] if b is not None else (None, False)
        report.unflagged_correct += status == "correct"
        _record(report, status, token_expected, token_got, flagged, a if a is not None else b)
    return report


def score_numbers(gt: Sequence[Word], hyp: Sequence[Word], *, flagged_regions: Sequence[BBox] = ()) -> NumberReport:
    """Exact number accuracy and silent errors. With boxes on every word, numbers are matched by place (so a swap of
    two numbers is caught); otherwise the two number sequences are aligned in reading order. ``flagged_regions`` are
    the regions the reader flagged (figure text, pages not passed as clean): numbers there leave the accuracy
    denominator and a drop there is not silent (docs/reading_eval_rules.md section 2)."""
    if all(w.bbox is not None for w in (*gt, *hyp)):
        return _score_spatial(gt, hyp, flagged_regions)
    return _score_sequence(gt, hyp)


# ---- tables: TEDS (tree edit distance based similarity, Zhong et al. 2020) ---------------------------------------

@dataclass(frozen=True)
class Cell:
    text: str
    colspan: int = 1
    rowspan: int = 1


@dataclass
class _Node:
    tag: str
    text: str = ""
    colspan: int = 1
    rowspan: int = 1
    children: list["_Node"] = field(default_factory=list)


def _table_tree(rows: Sequence[Sequence[Cell | str]], structure_only: bool) -> _Node:
    root = _Node("table")
    for row in rows:
        tr = _Node("tr")
        for cell in row:
            cell = Cell(cell) if isinstance(cell, str) else cell
            tr.children.append(_Node("td", "" if structure_only else normalize_for_cer(cell.text),
                                     cell.colspan, cell.rowspan))
        root.children.append(tr)
    return root


def _rename_cost(a: _Node, b: _Node) -> float:
    if a.tag != b.tag:
        return 1.0
    if a.tag != "td":
        return 0.0
    if (a.colspan, a.rowspan) != (b.colspan, b.rowspan):
        return 1.0
    if a.text == b.text:
        return 0.0
    return levenshtein(a.text, b.text) / max(len(a.text), len(b.text))


def _postorder(root: _Node) -> tuple[list[_Node], list[int], list[int]]:
    """Nodes in post-order, the leftmost-leaf index of each node, and the keyroots (Zhang-Shasha)."""
    nodes: list[_Node] = []
    leftmost: list[int] = []

    def visit(node: _Node) -> int:
        first_leaf = None
        for child in node.children:
            leaf = visit(child)
            if first_leaf is None:
                first_leaf = leaf
        nodes.append(node)
        index = len(nodes) - 1
        leftmost.append(index if first_leaf is None else first_leaf)
        return leftmost[index]

    visit(root)
    seen: dict[int, int] = {}
    for index, leaf in enumerate(leftmost):
        seen[leaf] = index  # the highest node with this leftmost leaf
    return nodes, leftmost, sorted(seen.values())


def tree_edit_distance(a: _Node, b: _Node) -> float:
    """Zhang-Shasha tree edit distance; insert and delete cost 1, rename cost from ``_rename_cost``."""
    nodes_a, left_a, keys_a = _postorder(a)
    nodes_b, left_b, keys_b = _postorder(b)
    distance = [[0.0] * len(nodes_b) for _ in nodes_a]
    for i in keys_a:
        for j in keys_b:
            li, lj = left_a[i], left_b[j]
            rows, cols = i - li + 2, j - lj + 2
            forest = [[0.0] * cols for _ in range(rows)]
            for x in range(1, rows):
                forest[x][0] = forest[x - 1][0] + 1
            for y in range(1, cols):
                forest[0][y] = forest[0][y - 1] + 1
            for x in range(1, rows):
                for y in range(1, cols):
                    node_i, node_j = li + x - 1, lj + y - 1
                    if left_a[node_i] == li and left_b[node_j] == lj:
                        forest[x][y] = min(forest[x - 1][y] + 1, forest[x][y - 1] + 1,
                                           forest[x - 1][y - 1] + _rename_cost(nodes_a[node_i], nodes_b[node_j]))
                        distance[node_i][node_j] = forest[x][y]
                    else:
                        px, py = left_a[node_i] - li, left_b[node_j] - lj
                        forest[x][y] = min(forest[x - 1][y] + 1, forest[x][y - 1] + 1,
                                           forest[px][py] + distance[node_i][node_j])
    return distance[-1][-1]


def _size(node: _Node) -> int:
    return 1 + sum(_size(child) for child in node.children)


def teds(gt: Sequence[Sequence[Cell | str]], pred: Sequence[Sequence[Cell | str]], *,
         structure_only: bool = False) -> float:
    """1 - TED / max(nodes). Cells are strings or ``Cell`` (for spans). ``structure_only`` ignores cell text
    (TEDS-S). A table with no rows on exactly one side scores 0."""
    if not gt or not pred:
        return 1.0 if not gt and not pred else 0.0
    tree_gt, tree_pred = _table_tree(gt, structure_only), _table_tree(pred, structure_only)
    # Nodes are counted below the table root, as in the PubTabNet reference (len(table.xpath(".//*"))).
    return 1.0 - tree_edit_distance(tree_gt, tree_pred) / max(_size(tree_gt) - 1, _size(tree_pred) - 1)


# ---- reading order and block types -------------------------------------------------------------------------------

def reading_order_accuracy(gt_order: Sequence[str], pred_order: Sequence[str]) -> float:
    """1 - normalized edit distance between the two block orders (ids already matched to the ground truth)."""
    longest = max(len(gt_order), len(pred_order))
    return 1.0 if longest == 0 else 1.0 - levenshtein(list(gt_order), list(pred_order)) / longest


def _iou(a: BBox, b: BBox) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return 0.0 if union <= 0 else inter / union


def match_blocks(gt: Iterable[tuple[str, BBox]], pred: Iterable[tuple[str, BBox]], *,
                 min_iou: float = 0.5) -> dict[str, str]:
    """Greedy one-to-one matching by IoU (best pairs first). Returns {pred_id: gt_id}."""
    gt, pred = list(gt), list(pred)
    candidates = sorted(((_iou(pb, gb), pi, gi) for pi, pb in pred for gi, gb in gt), reverse=True)
    pairs: dict[str, str] = {}
    used: set[str] = set()
    for score, pred_id, gt_id in candidates:
        if score < min_iou:
            break
        if pred_id not in pairs and gt_id not in used:
            pairs[pred_id] = gt_id
            used.add(gt_id)
    return pairs


def block_type_accuracy(gt_types: Mapping[str, str], pred_types: Mapping[str, str],
                        pairs: Mapping[str, str]) -> tuple[float, int, int]:
    """Share of ground-truth blocks matched by a predicted block of the same type (unmatched blocks count as wrong).
    Returns (accuracy, correct, total)."""
    correct = sum(1 for pred_id, gt_id in pairs.items() if pred_types[pred_id] == gt_types[gt_id])
    total = len(gt_types)
    return (1.0 if total == 0 else correct / total), correct, total


# ---- aggregation per page type -----------------------------------------------------------------------------------

def aggregate(rows: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Micro-averaged metrics per page type. Each row is one page with counts (char_edits, chars, word_edits, words,
    numbers, numbers_correct, silent_errors, silent_drops) and optional ratios (teds, reading_order, block_type)."""
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["page_type"], []).append(row)
    table: dict[str, dict[str, Any]] = {}
    for page_type, items in grouped.items():
        total = lambda key: sum(item.get(key, 0) for item in items)  # noqa: E731
        entry: dict[str, Any] = {
            "pages": len(items),
            "cer": _ratio(total("char_edits"), total("chars")),
            "wer": _ratio(total("word_edits"), total("words")),
            "numbers": total("numbers"),
            "number_accuracy": 1.0 if total("numbers") == 0 else total("numbers_correct") / total("numbers"),
            "silent_errors": total("silent_errors"),
            "silent_drops": total("silent_drops"),
        }
        for ratio in ("teds", "reading_order", "block_type"):
            values = [item[ratio] for item in items if item.get(ratio) is not None]
            entry[ratio] = sum(values) / len(values) if values else None
        table[page_type] = entry
    return table


def markdown_table(table: Mapping[str, Mapping[str, Any]]) -> str:
    def fmt(value: Any) -> str:
        if value is None:
            return "n/a"
        return f"{value:.4f}" if isinstance(value, float) else str(value)

    columns = ("pages", "cer", "wer", "numbers", "number_accuracy", "silent_errors", "silent_drops", "teds",
               "reading_order", "block_type")
    lines = ["| page type | " + " | ".join(columns) + " |", "|---" * (len(columns) + 1) + "|"]
    for page_type in [p for p in PAGE_TYPES if p in table] + [p for p in table if p not in PAGE_TYPES]:
        lines.append(f"| {page_type} | " + " | ".join(fmt(table[page_type].get(c)) for c in columns) + " |")
    return "\n".join(lines)
