"""Data rules for number visuals (Step 2c, tricks 14 and 15). A visual is drawn only when the fact's own value
supports it exactly; a value is never rounded to fit a visual. Labels always show `value_as_written`, copied by code.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

from matn_contracts.domain import NumberFactValue

_PLAIN = re.compile(r"\d+(?:\.\d+)?")
_RATIO = re.compile(r"(\d+)\s+(?:in|of|out of)\s+(\d+)")
PICTOGRAM_MAX = 10


def percentage(value: NumberFactValue) -> Decimal | None:
    """The value as a Decimal when the fact is a percentage between 0 and 100, written as a plain number."""
    if (value.unit or "").strip() != "%" or not _PLAIN.fullmatch(value.value_as_written.strip()):
        return None
    try:
        number = Decimal(value.value_as_written.strip())
    except InvalidOperation:
        return None
    return number if 0 <= number <= 100 else None


def progress_fraction(value: NumberFactValue) -> Decimal | None:
    """Share of a 100% track the bar fills: only for percentage facts between 0 and 100."""
    number = percentage(value)
    return None if number is None else number / 100


def pictogram(value: NumberFactValue) -> tuple[int, int] | None:
    """(filled, total) icons: an explicit "X in Y" fact with Y <= 10, or a percentage that is an exact multiple of
    10 (out of 10 icons). Anything else gets no pictogram."""
    ratio = _RATIO.fullmatch(value.value_as_written.strip())
    if ratio is not None:
        filled, total = int(ratio.group(1)), int(ratio.group(2))
        return (filled, total) if 2 <= total <= PICTOGRAM_MAX and 0 <= filled <= total else None
    number = percentage(value)
    if number is not None and number % 10 == 0:
        return int(number / 10), PICTOGRAM_MAX
    return None
