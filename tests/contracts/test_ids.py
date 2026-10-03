from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from matn_contracts.ids import make_block_id, make_fact_id, make_section_id, make_table_id


DOC_ID = "sha256-" + "a" * 64
BBOX = (10.04, 20.04, 110.04, 220.04)


def test_block_id_has_fixed_expected_value() -> None:
    assert make_block_id(DOC_ID, 7, BBOX, "Raw\ntext") == (
        DOC_ID + ":p0007:93971511c4f81f88"
    )


def test_table_id_has_fixed_expected_value() -> None:
    assert make_table_id(DOC_ID, 7, BBOX) == (
        DOC_ID + ":p0007:table:4497fa96193d9373"
    )


def test_section_id_has_fixed_expected_value() -> None:
    first_block_id = DOC_ID + ":p0007:93971511c4f81f88"
    assert make_section_id(DOC_ID, ("Top", "Child"), first_block_id) == (
        DOC_ID + ":section:915aaee74ade93ae"
    )


def test_fact_id_has_fixed_expected_value_after_statement_normalization() -> None:
    first_block_id = DOC_ID + ":p0007:93971511c4f81f88"
    assert make_fact_id(first_block_id, "  A  finding\nHERE. ") == "fact:facf4b66a9d42d7a"


def test_block_id_changes_when_each_identity_input_changes() -> None:
    baseline = make_block_id(DOC_ID, 7, BBOX, "Raw\ntext")
    assert make_block_id("sha256-" + "b" * 64, 7, BBOX, "Raw\ntext") != baseline
    assert make_block_id(DOC_ID, 8, BBOX, "Raw\ntext") != baseline
    assert make_block_id(DOC_ID, 7, (10.06, 20.04, 110.04, 220.04), "Raw\ntext") != baseline
    assert make_block_id(DOC_ID, 7, BBOX, "Raw text") != baseline


def test_bbox_change_below_rounding_precision_does_not_change_id() -> None:
    assert make_block_id(DOC_ID, 7, BBOX, "Raw\ntext") == make_block_id(
        DOC_ID,
        7,
        (10.049, 20.049, 110.049, 220.049),
        "Raw\ntext",
    )


def test_raw_text_is_not_normalized_for_block_identity() -> None:
    assert make_block_id(DOC_ID, 7, BBOX, "raw  text") != make_block_id(
        DOC_ID, 7, BBOX, "raw text"
    )


@settings(deadline=None)  # the property holds regardless of speed; a slow machine is not a failure (M-6)
@given(
    page_index=st.integers(min_value=0, max_value=9999),
    x0=st.integers(min_value=0, max_value=1000).map(lambda value: value / 10),
    y0=st.integers(min_value=0, max_value=1000).map(lambda value: value / 10),
    width=st.integers(min_value=1, max_value=1000).map(lambda value: value / 10),
    height=st.integers(min_value=1, max_value=1000).map(lambda value: value / 10),
    text=st.text(max_size=100),
)
def test_block_id_is_stable_for_repeated_inputs(
    page_index: int,
    x0: float,
    y0: float,
    width: float,
    height: float,
    text: str,
) -> None:
    bbox = (x0, y0, x0 + width, y0 + height)
    assert make_block_id(DOC_ID, page_index, bbox, text) == make_block_id(
        DOC_ID, page_index, bbox, text
    )
