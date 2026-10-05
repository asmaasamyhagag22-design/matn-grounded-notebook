"""Consensus rule (frozen in docs/ocr_rules.md before any measurement).

A reader-1 number is accepted only when reader 2 read the same token at the aligned place, exactly, after the
number normalization (N1, N3, N5, N7). Otherwise it becomes ``uncertain_number`` and keeps both readings. There is
no silent choice between readers: reader 2 never replaces reader 1's value, it only confirms or flags it. A number
that only reader 2 sees is reported as a possible reader-1 drop, and a failed second read flags the whole line.
Tokens are aligned in reading order (longest common subsequence), so two swapped numbers do not both agree.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .numbers import number_tokens


@dataclass(frozen=True)
class TokenVerdict:
    token: str
    word_index: int
    score: float
    status: str                    # "agreed" | "uncertain_number"
    reader2: str | None            # reader 2's token at the aligned place (None: nothing there, or no read)


@dataclass
class LineVerdict:
    tokens: list[TokenVerdict] = field(default_factory=list)
    extra_in_reader2: list[str] = field(default_factory=list)
    reader2_text: str | None = None


def _align(a: list[str], b: list[str]) -> list[tuple[int | None, int | None]]:
    n, m = len(a), len(b)
    lcs = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            lcs[i][j] = lcs[i + 1][j + 1] + 1 if a[i] == b[j] else max(lcs[i + 1][j], lcs[i][j + 1])
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if a[i] == b[j]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif lcs[i + 1][j] >= lcs[i][j + 1]:
            pairs.append((i, None))
            i += 1
        else:
            pairs.append((None, j))
            j += 1
    pairs += [(k, None) for k in range(i, n)] + [(None, k) for k in range(j, m)]
    return pairs


def compare_line(words: list[dict], reader2_text: str | None) -> LineVerdict:
    """``words``: reader-1 words of one line ({"text", "score"}); ``reader2_text``: GLM-OCR's line, or None."""
    first = [(token, index, float(word.get("score", 0.0)))
             for index, word in enumerate(words) for token in number_tokens(word["text"])]
    verdict = LineVerdict(reader2_text=reader2_text)
    if reader2_text is None:
        verdict.tokens = [TokenVerdict(t, i, s, "uncertain_number", None) for t, i, s in first]
        return verdict
    second = number_tokens(reader2_text)
    pairs = _align([t for t, _, _ in first], second)
    # Inside a gap between agreements, pair the leftovers by position so each flag shows reader 2's competing value.
    pending_first: list[int] = []
    pending_second: list[int] = []
    results: dict[int, TokenVerdict] = {}

    def flush() -> None:
        for k, a in enumerate(pending_first):
            token, index, score = first[a]
            other = second[pending_second[k]] if k < len(pending_second) else None
            results[a] = TokenVerdict(token, index, score, "uncertain_number", other)
        verdict.extra_in_reader2.extend(second[b] for b in pending_second[len(pending_first):])
        pending_first.clear()
        pending_second.clear()

    for a, b in pairs:
        if a is not None and b is not None:
            flush()
            token, index, score = first[a]
            results[a] = TokenVerdict(token, index, score, "agreed", second[b])
        elif a is not None:
            pending_first.append(a)
        else:
            pending_second.append(b)
    flush()
    verdict.tokens = [results[a] for a in range(len(first))]
    return verdict
