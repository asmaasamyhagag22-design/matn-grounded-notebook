from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator

from .base import VersionedContract
from .enums import (
    BlockType,
    ChartType,
    ExtractionRoute,
    FactKind,
    FactStatus,
    Importance,
    RejectReason,
    SentenceType,
    SlideType,
    Visibility,
)
from .ids import make_block_id, make_fact_id, make_section_id, make_table_id, validate_bbox


DocId = Annotated[str, Field(pattern=r"^sha256-[0-9a-f]{64}$")]
BBox = tuple[float, float, float, float]


class BlockStyle(VersionedContract):
    font_size_pt: Annotated[float, Field(gt=0)] | None
    is_bold: bool | None


class ExtractorInfo(VersionedContract):
    name: Annotated[str, Field(min_length=1)]
    version: Annotated[str, Field(min_length=1)]


class Block(VersionedContract):
    block_id: str
    doc_id: DocId
    page_index: Annotated[int, Field(ge=0)]
    page_label: str | None
    bbox: BBox
    block_type: BlockType
    text: str
    reading_order: Annotated[int, Field(ge=0)]
    style: BlockStyle
    extractor: ExtractorInfo
    route: ExtractionRoute
    visibility: Visibility

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        validate_bbox(self.bbox)
        expected = make_block_id(self.doc_id, self.page_index, self.bbox, self.text)
        if self.block_id != expected:
            raise ValueError("block_id does not match the deterministic identity inputs")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        block_id = make_block_id(
            str(values["doc_id"]),
            int(values["page_index"]),
            values["bbox"],  # type: ignore[arg-type]
            str(values["text"]),
        )
        return cls(block_id=block_id, **values)


class TableCell(VersionedContract):
    row: Annotated[int, Field(ge=0)]
    col: Annotated[int, Field(ge=0)]
    text: str
    bbox: BBox
    is_header: bool

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        validate_bbox(self.bbox)
        return self


class Table(VersionedContract):
    table_id: str
    doc_id: DocId
    page_index: Annotated[int, Field(ge=0)]
    bbox: BBox
    header_rows: tuple[Annotated[int, Field(ge=0)], ...]
    cells: tuple[TableCell, ...]

    @field_validator("header_rows", mode="before")
    @classmethod
    def normalize_header_rows(cls, value: object) -> tuple[int, ...]:
        return tuple(sorted(set(value)))  # type: ignore[arg-type]

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        validate_bbox(self.bbox)
        expected = make_table_id(self.doc_id, self.page_index, self.bbox)
        if self.table_id != expected:
            raise ValueError("table_id does not match the deterministic identity inputs")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        table_id = make_table_id(
            str(values["doc_id"]),
            int(values["page_index"]),
            values["bbox"],  # type: ignore[arg-type]
        )
        return cls(table_id=table_id, **values)


class PageRange(VersionedContract):
    first_page_index: Annotated[int, Field(ge=0)]
    last_page_index: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.first_page_index > self.last_page_index:
            raise ValueError("first_page_index must not exceed last_page_index")
        return self


class Section(VersionedContract):
    section_id: str
    doc_id: DocId
    title: Annotated[str, Field(min_length=1)]
    level: Annotated[int, Field(ge=1)]
    heading_path: Annotated[tuple[Annotated[str, Field(min_length=1)], ...], Field(min_length=1)]
    block_ids: Annotated[tuple[str, ...], Field(min_length=1)]
    page_range: PageRange

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = make_section_id(self.doc_id, self.heading_path, self.block_ids[0])
        if self.section_id != expected:
            raise ValueError("section_id does not match the deterministic identity inputs")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        block_ids = tuple(values["block_ids"])  # type: ignore[arg-type]
        if not block_ids:
            raise ValueError("a section needs at least one block_id")
        section_id = make_section_id(
            str(values["doc_id"]),
            values["heading_path"],  # type: ignore[arg-type]
            block_ids[0],
        )
        return cls(section_id=section_id, **{**values, "block_ids": block_ids})


class SectionCoverage(VersionedContract):
    missing_block_ids: tuple[str, ...]
    duplicated_block_ids: tuple[str, ...]


_COVERED_PROSE_TYPES = {
    BlockType.TEXT,
    BlockType.HEADING,
    BlockType.LIST_ITEM,
    BlockType.CAPTION,
    BlockType.FOOTNOTE,
}


def check_section_coverage(
    blocks: tuple[Block, ...],
    sections: tuple[Section, ...],
) -> SectionCoverage:
    required = {
        block.block_id
        for block in blocks
        if block.visibility is Visibility.VISIBLE and block.block_type in _COVERED_PROSE_TYPES
    }
    counts = Counter(
        block_id
        for section in sections
        for block_id in section.block_ids
        if block_id in required
    )
    return SectionCoverage(
        missing_block_ids=tuple(sorted(block_id for block_id in required if counts[block_id] == 0)),
        duplicated_block_ids=tuple(sorted(block_id for block_id in required if counts[block_id] > 1)),
    )


class EvidenceRef(VersionedContract):
    block_id: Annotated[str, Field(min_length=1)]
    quote: Annotated[str, Field(min_length=1)]
    char_start: Annotated[int, Field(ge=0)] | None
    char_end: Annotated[int, Field(ge=1)] | None

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("char_start and char_end must either both be null or both be set")
        if self.char_start is not None and self.char_end is not None:
            if self.char_start >= self.char_end:
                raise ValueError("char_start must be less than char_end")
        return self


class NumberFactValue(VersionedContract):
    label: Annotated[str, Field(min_length=1)]
    value_as_written: Annotated[str, Field(min_length=1)]
    unit: Annotated[str, Field(min_length=1)] | None
    page_label: str | None


class Fact(VersionedContract):
    fact_id: Annotated[str, Field(pattern=r"^fact:[0-9a-f]{16}$")]
    kind: FactKind
    statement: Annotated[str, Field(min_length=1)]
    attributed_to: Annotated[str, Field(min_length=1)] | None
    evidence: Annotated[tuple[EvidenceRef, ...], Field(min_length=1)]
    importance: Importance
    status: FactStatus
    reject_reasons: tuple[RejectReason, ...]
    number_value: NumberFactValue | None

    @field_validator("reject_reasons", mode="before")
    @classmethod
    def normalize_reject_reasons(cls, value: object) -> tuple[object, ...]:
        return tuple(dict.fromkeys(value))  # type: ignore[arg-type]

    @model_validator(mode="after")
    def validate_fact(self) -> Self:
        expected = make_fact_id(self.evidence[0].block_id, self.statement)
        if self.fact_id != expected:
            raise ValueError("fact_id does not match the deterministic identity inputs")
        if self.status is not FactStatus.REJECTED and self.reject_reasons:
            raise ValueError("reject_reasons must be empty unless status is rejected")
        if self.kind is FactKind.NUMBER and self.number_value is None:
            raise ValueError("number_value is required when kind is number")
        if self.kind is not FactKind.NUMBER and self.number_value is not None:
            raise ValueError("number_value is only allowed when kind is number")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        evidence = tuple(
            item if isinstance(item, EvidenceRef) else EvidenceRef.model_validate(item)
            for item in values.get("evidence", ())  # type: ignore[union-attr]
        )
        fact_id = (
            make_fact_id(evidence[0].block_id, str(values.get("statement", "")))
            if evidence
            else "invalid"
        )
        return cls(fact_id=fact_id, **{**values, "evidence": evidence})


class SummarySentence(VersionedContract):
    text: Annotated[str, Field(min_length=1)]
    type: SentenceType
    fact_ids: Annotated[tuple[str, ...], Field(min_length=1)]


class SectionSummary(VersionedContract):
    section_id: Annotated[str, Field(min_length=1)]
    sentences: tuple[SummarySentence, ...]


class KeyNumber(VersionedContract):
    fact_id: Annotated[str, Field(min_length=1)]
    label: Annotated[str, Field(min_length=1)]
    value_as_written: Annotated[str, Field(min_length=1)]
    unit: Annotated[str, Field(min_length=1)] | None
    page_label: str | None


class Summary(VersionedContract):
    doc_id: DocId
    tldr: Annotated[tuple[SummarySentence, ...], Field(min_length=1)]
    key_findings: tuple[SummarySentence, ...]
    section_summaries: tuple[SectionSummary, ...]
    key_numbers: tuple[KeyNumber, ...]


def key_numbers_from_facts(facts: tuple[Fact, ...]) -> tuple[KeyNumber, ...]:
    """Key numbers are copied by code from verified number facts; the model never writes them."""
    return tuple(
        KeyNumber(
            fact_id=fact.fact_id,
            label=fact.number_value.label,
            value_as_written=fact.number_value.value_as_written,
            unit=fact.number_value.unit,
            page_label=fact.number_value.page_label,
        )
        for fact in facts
        if fact.status is FactStatus.VERIFIED and fact.number_value is not None
    )


class SlideItem(VersionedContract):
    text: Annotated[str, Field(min_length=1, max_length=120)]
    fact_ids: Annotated[tuple[str, ...], Field(min_length=1)]


class ChartSpec(VersionedContract):
    table_id: Annotated[str, Field(min_length=1)]
    x_column: Annotated[int, Field(ge=0)]
    y_columns: Annotated[tuple[Annotated[int, Field(ge=0)], ...], Field(min_length=1)]
    chart_type: ChartType


class Slide(VersionedContract):
    slide_type: SlideType
    title: Annotated[str, Field(min_length=1, max_length=90)]
    items: Annotated[tuple[SlideItem, ...], Field(max_length=4)] = ()
    kpi_fact_ids: tuple[str, ...] = ()
    chart: ChartSpec | None = None
    notes: str | None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.slide_type is SlideType.KPI:
            if not 2 <= len(self.kpi_fact_ids) <= 4:
                raise ValueError("KPI slides require two to four kpi_fact_ids")
            if any(re.search(r"\d", item.text) for item in self.items):
                raise ValueError("KPI slide item text must not contain digits")
        elif self.kpi_fact_ids:
            raise ValueError("kpi_fact_ids are only allowed on KPI slides")
        if self.slide_type is SlideType.CHART:
            if self.chart is None:
                raise ValueError("chart is required on chart slides")
        elif self.chart is not None:
            raise ValueError("chart is only allowed on chart slides")
        return self


class DeckPlan(VersionedContract):
    doc_id: DocId
    slides: Annotated[tuple[Slide, ...], Field(min_length=1)]


def validate_deck_plan_against_facts(
    plan: DeckPlan,
    facts: tuple[Fact, ...],
) -> None:
    facts_by_id = {fact.fact_id: fact for fact in facts}
    for slide in plan.slides:
        for item in slide.items:
            for fact_id in item.fact_ids:
                if fact_id not in facts_by_id:
                    raise ValueError(f"UNKNOWN_FACT_ID:{fact_id}")
        for fact_id in slide.kpi_fact_ids:
            fact = facts_by_id.get(fact_id)
            if fact is None:
                raise ValueError(f"UNKNOWN_FACT_ID:{fact_id}")
            if fact.kind is not FactKind.NUMBER:
                raise ValueError(f"KPI_FACT_NOT_NUMBER:{fact_id}")


class PromptVersion(VersionedContract):
    name: Annotated[str, Field(min_length=1)]
    version: Annotated[str, Field(min_length=1)]


class SamplingParameters(VersionedContract):
    temperature: Annotated[float, Field(ge=0)]
    seed: int | None
    top_p: Annotated[float, Field(ge=0, le=1)] | None
    num_ctx: Annotated[int, Field(ge=1)] | None
    num_predict: Annotated[int, Field(ge=1)] | None


class RunManifest(VersionedContract):
    commit: Annotated[str, Field(pattern=r"^[0-9a-f]{7,40}$")]
    model_name: Annotated[str, Field(min_length=1)]
    model_digest: Annotated[str, Field(min_length=1)]
    prompt_versions: tuple[PromptVersion, ...]
    sampling_parameters: SamplingParameters
    extractor: ExtractorInfo
    started_at: datetime
    completed_at: datetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> Self:
        for field_name, value in (
            ("started_at", self.started_at),
            ("completed_at", self.completed_at),
        ):
            if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
                raise ValueError(f"{field_name} must be UTC-aware")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        return self
