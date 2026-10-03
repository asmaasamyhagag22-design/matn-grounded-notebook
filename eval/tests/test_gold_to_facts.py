"""Demo adapter (eval/gold_to_facts.py): dev-only document list, verification reasons, units and the table rule."""
from __future__ import annotations

import gold_to_facts as g
from matn_contracts.enums import RejectReason

PAGE = "Unemployment declined to 7.5 percent by Q1-FY2021/22, compared to 9.6 percent at the height of the shock."
QUOTE = "Unemployment declined to 7.5 percent by Q1-FY2021/22, compared to 9.6 percent"


def test_demo_documents_are_the_dev_split_only():
    assert set(g.DEMO_DOCS) == {"wb-eem-2021-12", "gao-21-519sp", "2601-14525v1"}
    assert not any("nist" in k or "egypt" in k for k in g.DEMO_DOCS)


def test_check_item_verifies_quote_numbers_and_value():
    assert g.check_item("7.5", QUOTE, PAGE, "", "7.5") == []
    assert RejectReason.QUOTE_NOT_FOUND in g.check_item("x", "not on this page at all, clearly", PAGE, "")
    assert RejectReason.NUMBER_NOT_IN_EVIDENCE in g.check_item("rose to 8.1", QUOTE, PAGE, "")
    assert RejectReason.NUMBER_NOT_IN_EVIDENCE in g.check_item("7", QUOTE, PAGE, "", "7")  # "7" only inside 7.5
    assert RejectReason.EVIDENCE_HIDDEN in g.check_item("7.5", QUOTE, PAGE, QUOTE)


def test_display_unit_and_statement():
    assert g.display_unit("69.4%", "%") is None
    assert g.display_unit("103", "count") is None and g.display_unit("2020", "year") is None
    assert g.number_statement("Unemployment rate", "7.5", "%") == "Unemployment rate: 7.5%"
    assert g.number_statement("Reserves", "40.8", "USD bn") == "Reserves: 40.8 USD bn"


def test_clean_table_rule():
    good = [["Year", "Value"], ["A", "1.0"], ["B", "2.5"], ["C", "3"]]
    assert g.clean_table(good)
    assert not g.clean_table(good[:3])  # fewer than 3 data rows
    assert not g.clean_table([["Year", "Value"], ["2020", "1"], ["2021", "2"], ["2022", "3"]])  # numeric labels
    assert not g.clean_table([["H", "V"], ["A", "x"], ["B", "y"], ["C", "z"]])  # no numeric column
    assert not g.clean_table([["H", "V"], ["A", None], ["B", "2"], ["C", "3"]])  # empty cell
