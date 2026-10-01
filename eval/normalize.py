"""Text normalization for verifying gold items against PDF page text.

The same normalization is applied to the page and to the quote:
  soft hyphens removed -> NFKC -> unified quotes and dashes -> hyphenated line breaks handled -> whitespace collapsed.

A hyphen at a line end is ambiguous ("trans-\\nformer" vs "state-of-the-\\nart"), so a page is matched in two variants:
one with the word rejoined and one with the hyphen kept. Matches must sit on word boundaries.

Values (key numbers) are checked on the RAW quote as well as the normalized one, because NFKC can change a value
(10⁶ becomes 106; audit finding F-06).
"""
from __future__ import annotations

import re
import unicodedata

_QUOTES = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
})
_DASHES = str.maketrans({c: "-" for c in "‐‑‒–—―−﹣－"})
_LINE_BREAK_HYPHEN = re.compile(r"(\w)-[ \t]*\r?\n\s*(\w)")


def normalize_text(text: str, *, rejoin_hyphens: bool = True) -> str:
    text = text.replace("­", "")
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_QUOTES).translate(_DASHES)
    if rejoin_hyphens:
        text = _LINE_BREAK_HYPHEN.sub(r"\1\2", text)
    else:
        text = _LINE_BREAK_HYPHEN.sub(r"\1-\2", text)
    return re.sub(r"\s+", " ", text).strip()


def _on_boundary(needle: str, haystack: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None


def quote_on_page(quote: str, page_text: str) -> bool:
    """True if the normalized quote occurs, on word boundaries, in either normalized variant of the page."""
    needle = normalize_text(quote)
    if not needle:
        return False
    return any(_on_boundary(needle, normalize_text(page_text, rejoin_hyphens=v)) for v in (True, False))


def count_on_page(quote: str, page_text: str) -> int:
    """Occurrences of the normalized quote on word boundaries, overlapping ones included; max over both variants."""
    needle = normalize_text(quote)
    if not needle:
        return 0
    pattern = re.compile(r"(?=(?<!\w)" + re.escape(needle) + r"(?!\w))")
    return max(len(pattern.findall(normalize_text(page_text, rejoin_hyphens=v))) for v in (True, False))


def _value_boundary(value: str, text: str) -> bool:
    # Not glued to a word character or to another number ("45" in "145", "1" in "1,024", "024" in "1,024").
    pattern = r"(?<![\w.,])" + re.escape(value) + r"(?![\w]|[.,]\d)"
    return re.search(pattern, text) is not None


def value_in_quote(value: str, quote: str) -> bool:
    """value_as_written must appear in the raw quote AND in the normalized quote, as a whole token."""
    if not value.strip():
        return False
    return _value_boundary(value, quote) and _value_boundary(normalize_text(value), normalize_text(quote))
