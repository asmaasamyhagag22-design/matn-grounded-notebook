"""TEDS is pinned to the PubTabNet reference implementation (ibm-aur-nlp/PubTabNet src/metric.py, commit 8ffde90,
file sha256 a9aedd31...f9f9, run with apted 1.0.3, Distance 0.1.3 and lxml 6.1.3 in a temporary venv outside the
repository on 2026-10-04). Those values were computed once and are copied here; no dependency was added to Matn."""
from __future__ import annotations

import pytest

from eval.reading.metrics import Cell, teds

CASES = [
    ("identical", [["Year", "GDP"], ["2020", "3.6"], ["2021", "3.3"]],
     [["Year", "GDP"], ["2020", "3.6"], ["2021", "3.3"]], 1.0, 1.0),
    ("one_cell_changed", [["Year", "GDP"], ["2020", "3.6"], ["2021", "3.3"]],
     [["Year", "GDP"], ["2020", "3.6"], ["2021", "3.8"]], 0.962962962962963, 1.0),
    ("missing_row", [["Year", "GDP"], ["2020", "3.6"], ["2021", "3.3"]],
     [["Year", "GDP"], ["2020", "3.6"]], 0.6666666666666667, 0.6666666666666667),
    ("colspan_split", [[Cell("Total revenue", colspan=2)], ["Tax", "1,234.5"], ["Non-tax", "210.0"]],
     [["Total revenue", ""], ["Tax", "1,234.5"], ["Non-tax", "210.0"]], 0.7777777777777778, 0.7777777777777778),
    ("rowspan_extra_column",
     [[Cell("Item", rowspan=2), "FY2020", "FY2021"], ["Actual", "Budget"], ["Wages", "45.2", "47.9"],
      ["Interest", "30.1", "33.0"]],
     [["Item", "FY2020", "FY2021", "Change"], ["", "Actual", "Budget", ""], ["Wages", "45.2", "47.6", "2.4"],
      ["Interst", "30.1", "33.0", "2.9"]], 0.68125, 0.7),
]


@pytest.mark.parametrize("name, gt, pred, expected, expected_struct", CASES, ids=[c[0] for c in CASES])
def test_teds_matches_the_pubtabnet_reference(name, gt, pred, expected, expected_struct):
    assert teds(gt, pred) == pytest.approx(expected, abs=1e-12)
    assert teds(gt, pred, structure_only=True) == pytest.approx(expected_struct, abs=1e-12)
