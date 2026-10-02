from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from matn_contracts.domain import (
    Block,
    BlockStyle,
    ChartSpec,
    DeckPlan,
    EvidenceRef,
    ExtractorInfo,
    Fact,
    KeyNumber,
    NumberFactValue,
    PageRange,
    PromptVersion,
    RunManifest,
    SamplingParameters,
    Section,
    SectionCoverage,
    SectionSummary,
    Slide,
    SlideItem,
    Summary,
    SummarySentence,
    Table,
    TableCell,
)
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
from matn_contracts.schema_export import CONTRACT_MODELS, render_schema_files


DOC_ID = "sha256-" + "a" * 64


def _samples() -> tuple[object, ...]:
    style = BlockStyle(font_size_pt=11.0, is_bold=False)
    extractor = ExtractorInfo(name="fixture", version="1.0")
    block = Block.create(
        doc_id=DOC_ID,
        page_index=0,
        page_label="1",
        bbox=(10.0, 20.0, 110.0, 40.0),
        block_type=BlockType.TEXT,
        text="The reported value is 64 percent.",
        reading_order=0,
        style=style,
        extractor=extractor,
        route=ExtractionRoute.TEXT_LAYER,
        visibility=Visibility.VISIBLE,
    )
    cell = TableCell(
        row=0,
        col=0,
        text="Year",
        bbox=(10.0, 50.0, 40.0, 60.0),
        is_header=True,
    )
    table = Table.create(
        doc_id=DOC_ID,
        page_index=0,
        bbox=(10.0, 50.0, 110.0, 90.0),
        header_rows=(0,),
        cells=(cell,),
    )
    page_range = PageRange(first_page_index=0, last_page_index=0)
    section = Section.create(
        doc_id=DOC_ID,
        title="Overview",
        level=1,
        heading_path=("Overview",),
        block_ids=(block.block_id,),
        page_range=page_range,
    )
    coverage = SectionCoverage(missing_block_ids=(), duplicated_block_ids=())
    evidence = EvidenceRef(
        block_id=block.block_id,
        quote="reported value is 64 percent",
        char_start=None,
        char_end=None,
    )
    number_value = NumberFactValue(
        label="Reported value",
        value_as_written="64",
        unit="percent",
        page_label="1",
    )
    fact = Fact.create(
        kind=FactKind.NUMBER,
        statement="The reported value is 64 percent.",
        attributed_to=None,
        evidence=(evidence,),
        importance=Importance.HEADLINE,
        status=FactStatus.RAW,
        reject_reasons=(),
        number_value=number_value,
    )
    sentence = SummarySentence(
        text="The reported value is available.",
        type=SentenceType.EXTRACTION,
        fact_ids=(fact.fact_id,),
    )
    section_summary = SectionSummary(section_id=section.section_id, sentences=(sentence,))
    key_number = KeyNumber(
        fact_id=fact.fact_id,
        label="Reported value",
        value_as_written="64",
        unit="percent",
        page_label="1",
    )
    summary = Summary(
        doc_id=DOC_ID,
        tldr=(sentence,),
        key_findings=(sentence,),
        section_summaries=(section_summary,),
        key_numbers=(key_number,),
    )
    slide_item = SlideItem(text="Reported value", fact_ids=(fact.fact_id,))
    chart = ChartSpec(
        table_id=table.table_id,
        x_column=0,
        y_columns=(1,),
        chart_type=ChartType.LINE,
    )
    slide = Slide(
        slide_type=SlideType.CHART,
        title="Reported trend",
        items=(slide_item,),
        kpi_fact_ids=(),
        chart=chart,
        notes=None,
    )
    deck = DeckPlan(doc_id=DOC_ID, slides=(slide,))
    prompt = PromptVersion(name="facts", version="v1")
    sampling = SamplingParameters(
        temperature=0,
        seed=7,
        top_p=None,
        num_ctx=4096,
        num_predict=512,
    )
    manifest = RunManifest(
        commit="a" * 40,
        model_name="local-model",
        model_digest="sha256:" + "b" * 64,
        prompt_versions=(prompt,),
        sampling_parameters=sampling,
        extractor=extractor,
        started_at=datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 10, 2, 10, 1, tzinfo=timezone.utc),
    )

    evidence_draft = EvidenceRefDraft(block_ref="b1", quote=evidence.quote)
    number_draft = NumberFactValueDraft(
        label=number_value.label,
        value_as_written=number_value.value_as_written,
        unit=number_value.unit,
    )
    fact_draft = FactDraft(
        kind=FactKind.NUMBER,
        statement=fact.statement,
        attributed_to=None,
        importance=Importance.HEADLINE,
        evidence=(evidence_draft,),
        number_value=number_draft,
    )
    sentence_draft = SummarySentenceDraft(
        text=sentence.text,
        type=sentence.type,
        fact_ids=sentence.fact_ids,
    )
    section_draft = SectionSummaryDraft(sentences=(sentence_draft,))
    item_draft = SlideItemDraft(text=slide_item.text, fact_ids=slide_item.fact_ids)
    chart_draft = ChartSpecDraft(
        table_id=chart.table_id,
        x_column=chart.x_column,
        y_columns=chart.y_columns,
        chart_type=chart.chart_type,
    )
    slide_draft = SlideDraft(
        slide_type=SlideType.CHART,
        title=slide.title,
        items=(item_draft,),
        kpi_fact_ids=(),
        chart=chart_draft,
        notes=None,
    )
    deck_draft = DeckPlanDraft(slides=(slide_draft,))
    return (
        style,
        extractor,
        block,
        cell,
        table,
        page_range,
        section,
        coverage,
        evidence,
        number_value,
        fact,
        sentence,
        section_summary,
        key_number,
        summary,
        slide_item,
        chart,
        slide,
        deck,
        prompt,
        sampling,
        manifest,
        evidence_draft,
        number_draft,
        fact_draft,
        sentence_draft,
        section_draft,
        item_draft,
        chart_draft,
        slide_draft,
        deck_draft,
    )


def test_registry_contains_every_public_model() -> None:
    samples = _samples()
    assert set(CONTRACT_MODELS.values()) == {type(sample) for sample in samples}


def test_every_public_model_survives_json_round_trip() -> None:
    for value in _samples():
        assert type(value).model_validate_json(value.model_dump_json()) == value


def test_every_public_model_carries_schema_version() -> None:
    for value in _samples():
        assert value.schema_version == 1


def test_exported_schema_snapshots_match() -> None:
    schema_dir = Path("schemas/contracts")
    rendered = render_schema_files()
    assert {path.name for path in schema_dir.glob("*.schema.json")} == set(rendered)
    for filename, expected in rendered.items():
        assert (schema_dir / filename).read_text(encoding="utf-8") == expected
