"""Free internal checks on OCR pages: table totals must add up; a number repeated in text and a table must match."""
from __future__ import annotations

from matn_reading.ocr.consistency import Cell, check_table_totals, check_text_against_tables


def _row(top: float, *cells: tuple[str, float]) -> list[Cell]:
    return [Cell(text, (x, top, x + 60, top + 10)) for text, x in cells]


def _table(*rows: tuple[str, ...]) -> list[list[Cell]]:
    return [_row(20.0 * i, *((text, 40.0 + 100 * j) for j, text in enumerate(row))) for i, row in enumerate(rows)]


def test_a_total_row_that_adds_up_raises_nothing():
    rows = _table(("Region", "1989", "1990"), ("North", "1,240", "13.5"), ("South", "760", "6.5"),
                  ("Total", "2,000", "20.0"))
    assert check_table_totals(rows) == []


def test_a_total_row_that_does_not_add_up_flags_the_column():
    rows = _table(("Region", "Amount"), ("North", "1,248"), ("South", "760"), ("Total", "2,000"))
    issues = check_table_totals(rows)
    assert len(issues) == 1 and issues[0].kind == "table_total_mismatch"
    assert sorted(cell.text for cell in issues[0].cells) == ["1,248", "2,000", "760"]


def test_rounding_within_the_shown_decimals_is_accepted():
    rows = _table(("Item", "Share"), ("A", "33.3"), ("B", "33.3"), ("C", "33.3"), ("Total", "100.0"))
    assert check_table_totals(rows) == []


def test_a_total_column_must_equal_its_row_parts():
    rows = _table(("Item", "Federal", "State", "Total"), ("Roads", "120", "80", "200"), ("Schools", "50", "40", "95"))
    issues = check_table_totals(rows)
    assert len(issues) == 1 and sorted(c.text for c in issues[0].cells) == ["40", "50", "95"]


def test_year_labels_are_not_summed():
    rows = _table(("Year", "Amount"), ("1989", "10"), ("1990", "15"), ("Total", "25"))
    assert check_table_totals(rows) == []


def test_text_number_one_digit_off_a_table_number_is_flagged():
    issues = check_text_against_tables([Cell("1,240", (0, 0, 10, 10))], [Cell("1,248", (0, 50, 10, 60))])
    assert len(issues) == 1 and issues[0].kind == "text_table_mismatch"
    assert check_text_against_tables([Cell("1,240", (0, 0, 10, 10))], [Cell("1,240", (0, 50, 10, 60))]) == []
    assert check_text_against_tables([Cell("1,240", (0, 0, 10, 10))], [Cell("1,204", (0, 50, 10, 60))])  # adjacent swap
    assert check_text_against_tables([Cell("12", (0, 0, 10, 10))], [Cell("13", (0, 50, 10, 60))]) == []  # too short
