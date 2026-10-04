from __future__ import annotations

import pytest
from pydantic import ValidationError

from matn_contracts.domain import (
    Block,
    BlockStyle,
    ExtractorInfo,
    PageRange,
    Section,
    Table,
    TableCell,
    check_section_coverage,
)
from matn_contracts.enums import BlockType, ExtractionRoute, HiddenReason, Visibility


DOC_ID = "sha256-" + "a" * 64
EXTRACTOR = ExtractorInfo(name="fixture", version="1.0")
STYLE = BlockStyle(font_size_pt=11.0, is_bold=False)


def block(
    text: str,
    *,
    page_index: int = 0,
    block_type: BlockType = BlockType.TEXT,
    visibility: Visibility = Visibility.VISIBLE,
    visibility_reasons: tuple[HiddenReason, ...] = (),
) -> Block:
    return Block.create(
        doc_id=DOC_ID,
        page_index=page_index,
        page_label=None,
        bbox=(1.0, 2.0, 100.0, 20.0),
        block_type=block_type,
        text=text,
        reading_order=0,
        style=STYLE,
        extractor=EXTRACTOR,
        route=ExtractionRoute.TEXT_LAYER,
        visibility=visibility,
        visibility_reasons=visibility_reasons,
    )


def section(*blocks: Block, title: str = "Heading") -> Section:
    return Section.create(
        doc_id=DOC_ID,
        title=title,
        level=1,
        heading_path=(title,),
        block_ids=tuple(item.block_id for item in blocks),
        page_range=PageRange(first_page_index=0, last_page_index=0),
    )


def test_negative_page_index_is_rejected() -> None:
    payload = block("text").model_dump(mode="json")
    payload["page_index"] = -1
    with pytest.raises(ValidationError):
        Block.model_validate(payload)


def test_inverted_bbox_is_rejected() -> None:
    payload = block("text").model_dump(mode="json")
    payload["bbox"] = [10.0, 2.0, 1.0, 20.0]
    with pytest.raises(ValidationError):
        Block.model_validate(payload)


def test_unknown_enum_and_extra_field_are_rejected() -> None:
    payload = block("text").model_dump(mode="json")
    payload["block_type"] = "unknown"
    with pytest.raises(ValidationError):
        Block.model_validate(payload)
    payload = block("text").model_dump(mode="json")
    payload["surprise"] = True
    with pytest.raises(ValidationError):
        Block.model_validate(payload)


def test_table_header_rows_are_sorted_unique_indices() -> None:
    cell = TableCell(
        row=0,
        col=0,
        text="Header",
        bbox=(1.0, 2.0, 20.0, 10.0),
        is_header=True,
    )
    table = Table.create(
        doc_id=DOC_ID,
        page_index=0,
        bbox=(1.0, 2.0, 100.0, 100.0),
        header_rows=(1, 0, 1),
        cells=(cell,),
    )
    assert table.header_rows == (0, 1)


def test_section_coverage_reports_missing_and_duplicates_separately() -> None:
    first = block("first")
    second = block("second")
    first_section = section(first, title="One")
    duplicate_section = section(first, title="Two")
    result = check_section_coverage((first, second), (first_section, duplicate_section))
    assert result.missing_block_ids == (second.block_id,)
    assert result.duplicated_block_ids == (first.block_id,)


def test_section_coverage_ignores_non_prose_and_hidden_blocks() -> None:
    visible = block("visible")
    table_block = block("table", block_type=BlockType.TABLE)
    hidden = block("hidden", visibility=Visibility.HIDDEN,
                   visibility_reasons=(HiddenReason.COVERED_BY_IMAGE,))
    result = check_section_coverage((visible, table_block, hidden), (section(visible),))
    assert result.missing_block_ids == ()
    assert result.duplicated_block_ids == ()


def test_white_on_white_text_has_a_reason_and_stays_out_of_prose() -> None:
    visible = block("visible")
    white_on_white = block("white on white", visibility=Visibility.HIDDEN,
                           visibility_reasons=(HiddenReason.FILL_MATCHES_BACKGROUND,))
    result = check_section_coverage((visible, white_on_white), (section(visible),))
    assert result.missing_block_ids == ()


def test_visibility_state_and_reasons_are_consistent_and_canonical() -> None:
    hidden = block("hidden", visibility=Visibility.HIDDEN,
                   visibility_reasons=(HiddenReason.OUTSIDE_CROPBOX, HiddenReason.COVERED_BY_IMAGE,
                                       HiddenReason.OUTSIDE_CROPBOX))
    assert hidden.schema_version == 2
    assert hidden.visibility_reasons == (HiddenReason.COVERED_BY_IMAGE, HiddenReason.OUTSIDE_CROPBOX)
    payload = hidden.model_dump(mode="json")
    payload["visibility"] = "visible"
    with pytest.raises(ValidationError, match="visible blocks"):
        Block.model_validate(payload)
    payload = block("visible").model_dump(mode="json")
    payload["visibility"] = "uncertain"
    with pytest.raises(ValidationError, match="at least one"):
        Block.model_validate(payload)


def test_domain_models_are_frozen() -> None:
    value = block("text")
    with pytest.raises(ValidationError):
        value.text = "changed"  # type: ignore[misc]
