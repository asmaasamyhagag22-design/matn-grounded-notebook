"""Number tokens for the OCR route: exactly the frozen reader/metric tokenizer (docs/reading_eval_rules.md section 2).

The pattern and the normalization are copies of ``eval.reading.metrics`` so pipeline code does not import eval
tooling; ``tests/reading/ocr/test_consensus.py`` fails if they ever drift apart. Only N1 (NFC), N3 (invisible
characters), N5 (dashes and minus) and N7 (whitespace) are applied: no change ever touches a digit.
"""
from __future__ import annotations

import re
import unicodedata

NUMBER_PATTERN = re.compile(
    r"(?<![\d.,])[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?!\d|[.,]\d)"
    r"|(?<![\w.,])[+-]?\.\d+(?!\d|[.,]\d)"
)
_INVISIBLE = {"­": "", "​": "", "‌": "", "‍": "", "⁠": "", "﻿": ""}
_DASHES = {"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-",
           "−": "-"}
_MAP = str.maketrans({**_INVISIBLE, **_DASHES})


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).translate(_MAP).split())


def number_spans(text: str) -> list[tuple[str, int, int]]:
    """(token, start, end) in the normalized text."""
    return [(m.group(0), m.start(), m.end()) for m in NUMBER_PATTERN.finditer(normalize(text))]


def number_tokens(text: str) -> list[str]:
    return [token for token, _, _ in number_spans(text)]
