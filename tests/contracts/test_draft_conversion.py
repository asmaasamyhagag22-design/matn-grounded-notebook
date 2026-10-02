from __future__ import annotations

import pytest
from pydantic import ValidationError

from matn_contracts.conversion import (
    deck_plan_from_draft,
    fact_from_draft,
    section_summary_from_draft,
)
from matn_contracts.domain import Block, BlockStyle, Fact
from matn_contracts.drafts import (
    ChartSpecDraft,
    DeckPlanDraft,
    EvidenceRefDraft,
    FactDraft,
    NumberFactValueDraft,
    SectionSummaryDraft,
    SlideDraft,
    SlideItemDraft,
    SummarySentenceDraft,
)
from matn_contracts.enums import (
    BlockType,
    ChartType,
    ExtractionRoute,
    FactKind,
    FactStatus,
    Importance,
    SentenceType,
    SlideType,
    Visibility,
)
from matn_contracts.domain import ExtractorInfo


DOC_ID = "sha256-" + "a" * 64


def block(*, text: str = "The reported value is 64 percent.", page_label: str | None = "1") -> Block:
    return Block.create(
        doc_id=DOC_ID,
        page_index=0,
        page_label=page_label,
        bbox=(10.0, 20.0, 110.0, 40.0),
        block_type=BlockType.TEXT,
        text=text,
        reading_order=0,
        style=BlockStyle(font_size_pt=11.0, is_bold=False),
        extractor=ExtractorInfo(name="fixture", version="1.0"),
        route=ExtractionRoute.TEXT_LAYER,
        visibility=Visibility.VISIBLE,
    )


def finding_draft(**changes: object) -> FactDraft:
    values: dict[str, object] = {
        "kind": FactKind.FINDING,
        "statement": "The reported value is 64 percent.",
        "attributed_to": None,
        "importance": Importance.HEADLINE,
        "evidence": (
            EvidenceRefDraft(block_ref="b1", quote="reported value is 64 percent"),
        ),
        "number_value": None,
    }
    values.update(changes)
    return FactDraft(**values)


def test_fact_draft_rejects_code_owned_and_offset_fields() -> None:
    payload = finding_draft().model_dump(mode="json")
    for field, value in (
        ("fact_id", "fact:" + "a" * 16),
        ("status", "raw"),
        ("reject_reasons", []),
    ):
        with pytest.raises(ValidationError):
            FactDraft.model_validate({**payload, field: value})

    evidence_payload = EvidenceRefDraft(block_ref="b1", quote="exact quote").model_dump(mode="json")
    with pytest.raises(ValidationError):
        EvidenceRefDraft.model_validate({**evidence_payload, "char_start": 0})


def test_draft_uses_short_section_local_refs_not_full_block_ids() -> None:
    with pytest.raises(ValidationError):
        EvidenceRefDraft(block_ref=block().block_id, quote="exact quote")
    assert EvidenceRefDraft(block_ref="b12", quote="exact quote").block_ref == "b12"


def test_fact_conversion_assigns_identity_and_raw_status() -> None:
    source = block()
    converted = fact_from_draft(finding_draft(), {"b1": source})
    assert converted == Fact.create(
        kind=FactKind.FINDING,
        statement="The reported value is 64 percent.",
        attributed_to=None,
        evidence=(
            {
                "block_id": source.block_id,
                "quote": "reported value is 64 percent",
                "char_start": None,
                "char_end": None,
            },
        ),
        importance=Importance.HEADLINE,
        status=FactStatus.RAW,
        reject_reasons=(),
        number_value=None,
    )
    assert converted.status is FactStatus.RAW


def test_fact_conversion_rejects_unknown_ref_and_non_source_quote() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_BLOCK_REF:b1"):
        fact_from_draft(finding_draft(), {})
    with pytest.raises(ValueError, match="QUOTE_NOT_FOUND:b1"):
        fact_from_draft(finding_draft(), {"b1": block(text="Different text.")})


def test_number_conversion_checks_exact_token_and_unit_and_derives_page_label() -> None:
    draft = finding_draft(
        kind=FactKind.NUMBER,
        number_value=NumberFactValueDraft(
            label="Reported value",
            value_as_written="64",
            unit="percent",
        ),
    )
    converted = fact_from_draft(draft, {"b1": block(page_label="iv")})
    assert converted.number_value is not None
    assert converted.number_value.page_label == "iv"

    with pytest.raises(ValueError, match="NUMBER_NOT_IN_EVIDENCE"):
        fact_from_draft(
            draft.model_copy(
                update={
                    "number_value": NumberFactValueDraft(
                        label="Reported value",
                        value_as_written="6",
                        unit="percent",
                    )
                }
            ),
            {"b1": block()},
        )
    with pytest.raises(ValueError, match="UNIT_NOT_IN_EVIDENCE"):
        fact_from_draft(
            draft.model_copy(
                update={
                    "number_value": NumberFactValueDraft(
                        label="Reported value",
                        value_as_written="64",
                        unit="USD",
                    )
                }
            ),
            {"b1": block()},
        )


def test_fact_draft_requires_number_value_if_and_only_if_number() -> None:
    with pytest.raises(ValidationError):
        finding_draft(kind=FactKind.NUMBER)
    with pytest.raises(ValidationError):
        finding_draft(
            number_value=NumberFactValueDraft(
                label="Reported value",
                value_as_written="64",
                unit=None,
            )
        )


def test_section_summary_conversion_uses_code_supplied_section_id() -> None:
    source_fact = fact_from_draft(finding_draft(), {"b1": block()})
    draft = SectionSummaryDraft(
        sentences=(
            SummarySentenceDraft(
                text="The value is reported.",
                type=SentenceType.EXTRACTION,
                fact_ids=(source_fact.fact_id,),
            ),
        )
    )
    converted = section_summary_from_draft(draft, section_id="section-1")
    assert converted.section_id == "section-1"
    assert converted.sentences[0].fact_ids == (source_fact.fact_id,)


def test_deck_draft_conversion_keeps_only_references_and_validates_fact_kinds() -> None:
    numeric = fact_from_draft(
        finding_draft(
            kind=FactKind.NUMBER,
            number_value=NumberFactValueDraft(
                label="Reported value",
                value_as_written="64",
                unit="percent",
            ),
        ),
        {"b1": block()},
    )
    draft = DeckPlanDraft(
        slides=(
            SlideDraft(
                slide_type=SlideType.KPI,
                title="Headline metrics",
                items=(SlideItemDraft(text="Reported value", fact_ids=(numeric.fact_id,)),),
                kpi_fact_ids=(numeric.fact_id, numeric.fact_id),
                chart=None,
                notes=None,
            ),
            SlideDraft(
                slide_type=SlideType.CHART,
                title="Reported trend",
                items=(),
                kpi_fact_ids=(),
                chart=ChartSpecDraft(
                    table_id=DOC_ID + ":p0000:table:" + "b" * 16,
                    x_column=0,
                    y_columns=(1,),
                    chart_type=ChartType.LINE,
                ),
                notes=None,
            ),
        )
    )
    converted = deck_plan_from_draft(draft, doc_id=DOC_ID, facts=(numeric,))
    assert converted.doc_id == DOC_ID
    assert converted.slides[1].chart is not None

    payload = draft.model_dump(mode="json")
    payload["slides"][1]["chart"]["data_values"] = [64]
    with pytest.raises(ValidationError):
        DeckPlanDraft.model_validate(payload)
