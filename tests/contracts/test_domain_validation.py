from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from matn_contracts.domain import (
    ChartSpec,
    DeckPlan,
    EvidenceRef,
    ExtractorInfo,
    Fact,
    KeyNumber,
    NumberFactValue,
    PromptVersion,
    RunManifest,
    SamplingParameters,
    SectionSummary,
    Slide,
    SlideItem,
    Summary,
    SummarySentence,
    validate_deck_plan_against_facts,
)
from matn_contracts.enums import (
    ChartType,
    FactKind,
    FactStatus,
    Importance,
    RejectReason,
    SentenceType,
    SlideType,
)


DOC_ID = "sha256-" + "a" * 64
BLOCK_ID = DOC_ID + ":p0000:0123456789abcdef"


def evidence(**changes: object) -> EvidenceRef:
    values: dict[str, object] = {
        "block_id": BLOCK_ID,
        "quote": "The value is 64 percent.",
        "char_start": None,
        "char_end": None,
    }
    values.update(changes)
    return EvidenceRef(**values)


def fact(
    *,
    kind: FactKind = FactKind.FINDING,
    status: FactStatus = FactStatus.RAW,
    number_value: NumberFactValue | None = None,
    reject_reasons: tuple[RejectReason, ...] = (),
) -> Fact:
    return Fact.create(
        kind=kind,
        statement="The value is 64 percent.",
        attributed_to=None,
        evidence=(evidence(),),
        importance=Importance.HEADLINE,
        status=status,
        reject_reasons=reject_reasons,
        number_value=number_value,
    )


def number_fact() -> Fact:
    return fact(
        kind=FactKind.NUMBER,
        number_value=NumberFactValue(
            label="Reported value",
            value_as_written="64",
            unit="percent",
            page_label="1",
        ),
    )


def test_fact_requires_evidence_and_nonempty_quote() -> None:
    with pytest.raises(ValidationError):
        Fact.create(
            kind=FactKind.FINDING,
            statement="Statement.",
            attributed_to=None,
            evidence=(),
            importance=Importance.IMPORTANT,
            status=FactStatus.RAW,
            reject_reasons=(),
            number_value=None,
        )
    with pytest.raises(ValidationError):
        evidence(quote="")


def test_evidence_offsets_are_both_null_or_a_valid_pair() -> None:
    with pytest.raises(ValidationError):
        evidence(char_start=0, char_end=None)
    with pytest.raises(ValidationError):
        evidence(char_start=5, char_end=5)
    assert evidence(char_start=0, char_end=2).char_end == 2


def test_reject_reasons_are_empty_unless_fact_is_rejected() -> None:
    with pytest.raises(ValidationError):
        fact(reject_reasons=(RejectReason.QUOTE_NOT_FOUND,))
    rejected = fact(
        status=FactStatus.REJECTED,
        reject_reasons=(RejectReason.QUOTE_NOT_FOUND,),
    )
    assert rejected.reject_reasons == (RejectReason.QUOTE_NOT_FOUND,)


def test_number_value_is_required_if_and_only_if_kind_is_number() -> None:
    with pytest.raises(ValidationError):
        fact(kind=FactKind.NUMBER)
    with pytest.raises(ValidationError):
        fact(
            number_value=NumberFactValue(
                label="Reported value",
                value_as_written="64",
                unit=None,
                page_label=None,
            )
        )
    assert number_fact().number_value is not None


def test_unknown_fact_enum_and_extra_fields_are_rejected() -> None:
    payload = fact().model_dump(mode="json")
    payload["kind"] = "unknown"
    with pytest.raises(ValidationError):
        Fact.model_validate(payload)
    payload = fact().model_dump(mode="json")
    payload["extra"] = "forbidden"
    with pytest.raises(ValidationError):
        Fact.model_validate(payload)


def test_summary_sentence_and_slide_item_require_fact_ids() -> None:
    with pytest.raises(ValidationError):
        SummarySentence(text="Grounded.", type=SentenceType.EXTRACTION, fact_ids=())
    with pytest.raises(ValidationError):
        SlideItem(text="Grounded", fact_ids=())


def test_slide_title_and_item_length_limits() -> None:
    with pytest.raises(ValidationError):
        Slide(slide_type=SlideType.FINDING, title="x" * 91, items=(), notes=None)
    with pytest.raises(ValidationError):
        SlideItem(text="x" * 121, fact_ids=(fact().fact_id,))


def test_kpi_slide_rejects_digits_and_non_number_facts() -> None:
    numeric = number_fact()
    with pytest.raises(ValidationError):
        Slide(
            slide_type=SlideType.KPI,
            title="Headline metrics",
            items=(SlideItem(text="Value 64", fact_ids=(numeric.fact_id,)),),
            kpi_fact_ids=(numeric.fact_id, numeric.fact_id),
            notes=None,
        )
    plan = DeckPlan(
        doc_id=DOC_ID,
        slides=(
            Slide(
                slide_type=SlideType.KPI,
                title="Headline metrics",
                items=(SlideItem(text="Reported value", fact_ids=(numeric.fact_id,)),),
                kpi_fact_ids=(numeric.fact_id, fact().fact_id),
                notes=None,
            ),
        ),
    )
    with pytest.raises(ValueError, match="KPI_FACT_NOT_NUMBER"):
        validate_deck_plan_against_facts(plan, (numeric, fact()))


def test_chart_slide_holds_references_but_rejects_data_values() -> None:
    slide = Slide(
        slide_type=SlideType.CHART,
        title="Trend changes over time",
        items=(),
        chart=ChartSpec(
            table_id=DOC_ID + ":p0000:table:0123456789abcdef",
            x_column=0,
            y_columns=(1,),
            chart_type=ChartType.LINE,
        ),
        notes=None,
    )
    payload = slide.model_dump(mode="json")
    payload["chart"]["data_values"] = [1, 2, 3]
    with pytest.raises(ValidationError):
        Slide.model_validate(payload)


def test_summary_uses_tuple_collections() -> None:
    item = SummarySentence(
        text="Grounded.",
        type=SentenceType.EXTRACTION,
        fact_ids=(fact().fact_id,),
    )
    value = Summary(
        doc_id=DOC_ID,
        tldr=(item,),
        key_findings=(item,),
        section_summaries=(SectionSummary(section_id="section-1", sentences=(item,)),),
        key_numbers=(
            KeyNumber(
                fact_id=number_fact().fact_id,
                label="Reported value",
                value_as_written="64",
                unit="percent",
                page_label="1",
            ),
        ),
    )
    assert isinstance(value.key_findings, tuple)
    assert isinstance(value.section_summaries, tuple)


def test_run_manifest_requires_utc_timestamps() -> None:
    values = {
        "commit": "a" * 40,
        "model_name": "local-model",
        "model_digest": "sha256:" + "b" * 64,
        "prompt_versions": (PromptVersion(name="facts", version="v1"),),
        "sampling_parameters": SamplingParameters(
            temperature=0,
            seed=7,
            top_p=None,
            num_ctx=4096,
            num_predict=512,
        ),
        "extractor": ExtractorInfo(name="fixture", version="1.0"),
        "started_at": datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
        "completed_at": datetime(2026, 10, 2, 10, 1, tzinfo=timezone.utc),
    }
    assert RunManifest(**values).completed_at > RunManifest(**values).started_at
    values["started_at"] = datetime(2026, 10, 2, 10, 0)
    with pytest.raises(ValidationError):
        RunManifest(**values)
