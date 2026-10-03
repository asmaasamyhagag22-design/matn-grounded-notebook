"""Title typography (tricks 18 and sentence case): text is never changed, only where it breaks and how it is cased.

- Sentence case: a theme that sets cap="all" on titles keeps it only for short labels; titles longer than
  `CAPS_MAX_CHARS` are shown as written.
- Balanced breaks: a title that wraps keeps the same number of lines, but the breaks are chosen to minimize the width
  difference between lines (real font metrics), never leaving one word alone on the last line when another break fits.
"""
from __future__ import annotations

from itertools import combinations
from typing import Callable

CAPS_MAX_CHARS = 30
_MAX_WORDS = 40  # titles are at most 90 characters; this only bounds the search


def keep_caps(text: str, theme_caps: bool) -> bool:
    """True when the theme's all-caps style should stay on this text."""
    return theme_caps and len(text) <= CAPS_MAX_CHARS


def balanced_lines(text: str, max_width: float, width: Callable[[str], float], greedy: list[str]) -> list[str]:
    """Lines for `text` with the same count as the greedy wrap `greedy`, balanced by measured width.

    Returns `greedy` unchanged when it is a single line, when a word had to be cut, or when no balanced
    break fits `max_width`.
    """
    words = text.split(" ")
    n = len(greedy)
    if n <= 1 or len(words) > _MAX_WORDS or " ".join(greedy).split(" ") != words:
        return greedy
    best_key, best_lines = None, None
    for cuts in combinations(range(1, len(words)), n - 1):
        bounds = (0, *cuts, len(words))
        lines = [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:])]
        widths = [width(line) for line in lines]
        if max(widths) > max_width:
            continue
        orphan = bounds[-1] - bounds[-2] == 1
        key = (orphan, round(max(widths) - min(widths), 3), cuts)
        if best_key is None or key < best_key:
            best_key, best_lines = key, lines
    return best_lines or greedy
