from __future__ import annotations

import re
from collections.abc import Mapping

from .domain import (
    Block,
    ChartSpec,
    DeckPlan,
    EvidenceRef,
    Fact,
    NumberFactValue,
    SectionSummary,
    Slide,
    SlideItem,
    SummarySentence,
    validate_deck_plan_against_facts,
)
from .drafts import DeckPlanDraft, FactDraft, SectionSummaryDraft
from .enums import FactStatus


# A whole number as written: 64, 2021, 1,234, 1,234.5, 12.5, .5. Sentence punctuation may follow it ("64.", "2021,"),
# but a "." or "," followed by a digit means the match is only part of a larger number (64.5, 1.2.3, 12,34).
_NUMERIC_TOKEN = re.compile(
    r"(?<![\w.,])[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)(?!\w|[.,]\d)"
)


def numeric_tokens(text: str) -> list[re.Match[str]]:
    """Every whole number as written in `text` (the same tokenizer that verifies number facts against quotes)."""
    return list(_NUMERIC_TOKEN.finditer(text))


def fact_from_draft(
    draft: FactDraft,
    block_ref_map: Mapping[str, Block],
) -> Fact:
    evidence: list[EvidenceRef] = []
    evidence_blocks: list[Block] = []
    for item in draft.evidence:
        try:
            source_block = block_ref_map[item.block_ref]
        except KeyError as exc:
            raise ValueError(f"UNKNOWN_BLOCK_REF:{item.block_ref}") from exc
        if item.quote not in source_block.text:
            raise ValueError(f"QUOTE_NOT_FOUND:{item.block_ref}")
        evidence.append(
            EvidenceRef(
                block_id=source_block.block_id,
                quote=item.quote,
                char_start=None,
                char_end=None,
            )
        )
        evidence_blocks.append(source_block)

    number_value = None
    if draft.number_value is not None:
        matching_index = _matching_number_evidence(
            draft.number_value.value_as_written,
            tuple(item.quote for item in draft.evidence),
        )
        if matching_index is None:
            raise ValueError("NUMBER_NOT_IN_EVIDENCE")
        matching_quote = draft.evidence[matching_index].quote
        if draft.number_value.unit is not None and draft.number_value.unit not in matching_quote:
            raise ValueError("UNIT_NOT_IN_EVIDENCE")
        evidence_tokens = {
            match.group(0) for item in draft.evidence for match in _NUMERIC_TOKEN.finditer(item.quote)
        }
        if any(match.group(0) not in evidence_tokens for match in _NUMERIC_TOKEN.finditer(draft.number_value.label)):
            raise ValueError("LABEL_NUMBER_NOT_IN_EVIDENCE")
        number_value = NumberFactValue(
            label=draft.number_value.label,
            value_as_written=draft.number_value.value_as_written,
            unit=draft.number_value.unit,
            page_label=evidence_blocks[matching_index].page_label,
        )

    return Fact.create(
        kind=draft.kind,
        statement=draft.statement,
        attributed_to=draft.attributed_to,
        evidence=tuple(evidence),
        importance=draft.importance,
        status=FactStatus.RAW,
        reject_reasons=(),
        number_value=number_value,
    )


def _matching_number_evidence(value_as_written: str, quotes: tuple[str, ...]) -> int | None:
    for index, quote in enumerate(quotes):
        if value_as_written in (match.group(0) for match in _NUMERIC_TOKEN.finditer(quote)):
            return index
    return None


def section_summary_from_draft(
    draft: SectionSummaryDraft,
    *,
    section_id: str,
) -> SectionSummary:
    return SectionSummary(
        section_id=section_id,
        sentences=tuple(
            SummarySentence(text=item.text, type=item.type, fact_ids=item.fact_ids)
            for item in draft.sentences
        ),
    )


def deck_plan_from_draft(
    draft: DeckPlanDraft,
    *,
    doc_id: str,
    facts: tuple[Fact, ...],
) -> DeckPlan:
    slides = tuple(
        Slide(
            slide_type=slide.slide_type,
            title=slide.title,
            items=tuple(
                SlideItem(text=item.text, fact_ids=item.fact_ids) for item in slide.items
            ),
            kpi_fact_ids=slide.kpi_fact_ids,
            chart=(
                ChartSpec(
                    table_id=slide.chart.table_id,
                    x_column=slide.chart.x_column,
                    y_columns=slide.chart.y_columns,
                    chart_type=slide.chart.chart_type,
                )
                if slide.chart is not None
                else None
            ),
            notes=slide.notes,
        )
        for slide in draft.slides
    )
    plan = DeckPlan(doc_id=doc_id, slides=slides)
    validate_deck_plan_against_facts(plan, facts)
    return plan
