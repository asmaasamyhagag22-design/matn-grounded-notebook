from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import VersionedContract
from .enums import ChartType, FactKind, Importance, SentenceType, SlideType


class EvidenceRefDraft(VersionedContract):
    block_ref: Annotated[str, Field(pattern=r"^b[1-9][0-9]*$")]
    quote: Annotated[str, Field(min_length=1)]


class NumberFactValueDraft(VersionedContract):
    label: Annotated[str, Field(min_length=1)]
    value_as_written: Annotated[str, Field(min_length=1)]
    unit: Annotated[str, Field(min_length=1)] | None


class FactDraft(VersionedContract):
    kind: FactKind
    statement: Annotated[str, Field(min_length=1)]
    attributed_to: Annotated[str, Field(min_length=1)] | None
    importance: Importance
    evidence: Annotated[tuple[EvidenceRefDraft, ...], Field(min_length=1)]
    number_value: NumberFactValueDraft | None

    @model_validator(mode="after")
    def validate_number_value(self) -> Self:
        if self.kind is FactKind.NUMBER and self.number_value is None:
            raise ValueError("number_value is required when kind is number")
        if self.kind is not FactKind.NUMBER and self.number_value is not None:
            raise ValueError("number_value is only allowed when kind is number")
        return self


class SummarySentenceDraft(VersionedContract):
    text: Annotated[str, Field(min_length=1)]
    type: SentenceType
    fact_ids: Annotated[tuple[str, ...], Field(min_length=1)]


class SectionSummaryDraft(VersionedContract):
    sentences: tuple[SummarySentenceDraft, ...]


class SlideItemDraft(VersionedContract):
    text: Annotated[str, Field(min_length=1, max_length=120)]
    fact_ids: Annotated[tuple[str, ...], Field(min_length=1)]


class ChartSpecDraft(VersionedContract):
    table_id: Annotated[str, Field(min_length=1)]
    x_column: Annotated[int, Field(ge=0)]
    y_columns: Annotated[tuple[Annotated[int, Field(ge=0)], ...], Field(min_length=1)]
    chart_type: ChartType


class SlideDraft(VersionedContract):
    schema_version: Literal[3] = 3  # v2: section_divider, closing, evidence_appendix; v3: 1-4 KPI values
    slide_type: SlideType
    title: Annotated[str, Field(min_length=1, max_length=90)]
    items: Annotated[tuple[SlideItemDraft, ...], Field(max_length=4)] = ()
    kpi_fact_ids: tuple[str, ...] = ()
    chart: ChartSpecDraft | None = None
    notes: str | None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if self.slide_type is SlideType.KPI:
            if not 1 <= len(self.kpi_fact_ids) <= 4:
                raise ValueError("KPI slides require one to four kpi_fact_ids")
            if any(re.search(r"\d", item.text) for item in self.items):
                raise ValueError("KPI slide item text must not contain digits")
        elif self.kpi_fact_ids:
            raise ValueError("kpi_fact_ids are only allowed on KPI slides")
        if self.slide_type is SlideType.CHART:
            if self.chart is None:
                raise ValueError("chart is required on chart slides")
        elif self.chart is not None:
            raise ValueError("chart is only allowed on chart slides")
        if self.slide_type is SlideType.SECTION_DIVIDER and len(self.items) > 1:
            raise ValueError("section_divider slides hold at most one item (the section question)")
        if self.slide_type is SlideType.EVIDENCE_APPENDIX and self.items:
            raise ValueError("evidence_appendix items are built by code from the cited facts")
        return self


class DeckPlanDraft(VersionedContract):
    schema_version: Literal[3] = 3  # v2: Slide v2; v3: Slide v3
    slides: Annotated[tuple[SlideDraft, ...], Field(min_length=1)]
