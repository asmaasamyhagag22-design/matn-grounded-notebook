"""Hand-written specimen deck: fictional content that exercises every archetype.

Nothing here comes from a real document. Every statement starts with "Sample" so a reader can never mistake it for
findings. Run `python -m matn_deck.specimen` to write design/specimen/specimen.pptx.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from matn_contracts.domain import (
    ChartSpec,
    DeckPlan,
    EvidenceRef,
    Fact,
    NumberFactValue,
    Slide,
    SlideItem,
    Table,
    TableCell,
)
from matn_contracts.enums import ChartType, FactKind, FactStatus, Importance, SlideType
from matn_contracts.ids import make_block_id

from .render import render

SPECIMEN_DOC_ID = "sha256-" + hashlib.sha256(b"matn design specimen - fictional content").hexdigest()
SPECIMEN_PATH = Path(__file__).resolve().parents[1] / "design" / "specimen" / "specimen.pptx"
_BBOX = (72.0, 100.0, 520.0, 140.0)


def sample_fact(
    statement: str,
    quote: str,
    page_index: int,
    *,
    kind: FactKind = FactKind.FINDING,
    number: tuple[str, str, str | None] | None = None,
    status: FactStatus = FactStatus.VERIFIED,
    doc_id: str = SPECIMEN_DOC_ID,
) -> Fact:
    """A fact whose single evidence block sits on `page_index`; `number` is (label, value_as_written, unit)."""
    block_id = make_block_id(doc_id, page_index, _BBOX, quote)
    number_value = None
    if number is not None:
        label, value, unit = number
        number_value = NumberFactValue(label=label, value_as_written=value, unit=unit, page_label=str(page_index + 1))
    return Fact.create(
        kind=FactKind.NUMBER if number is not None else kind,
        statement=statement,
        attributed_to=None,
        evidence=(EvidenceRef(block_id=block_id, quote=quote, char_start=None, char_end=None),),
        importance=Importance.HEADLINE,
        status=status,
        reject_reasons=(),
        number_value=number_value,
    )


def sample_table(rows: list[list[str]], page_index: int, *, doc_id: str = SPECIMEN_DOC_ID) -> Table:
    """A table whose first row is the header."""
    cells = tuple(
        TableCell(
            row=r,
            col=c,
            text=text,
            bbox=(72.0 + 100 * c, 300.0 + 20 * r, 170.0 + 100 * c, 318.0 + 20 * r),
            is_header=r == 0,
        )
        for r, row in enumerate(rows)
        for c, text in enumerate(row)
    )
    return Table.create(doc_id=doc_id, page_index=page_index, bbox=(72.0, 300.0, 520.0, 420.0), header_rows=(0,),
                        cells=cells)


def item(text: str, *facts: Fact) -> SlideItem:
    return SlideItem(text=text, fact_ids=tuple(f.fact_id for f in facts))


def specimen_inputs() -> tuple[DeckPlan, tuple[Fact, ...], tuple[Table, ...]]:
    adoption = sample_fact("Sample: adoption of the sample service rose 18% in 2025.",
                           "Sample text: adoption of the sample service rose 18% in 2025.", 2)
    growth = sample_fact("Sample: adoption grew 18 percent in 2025.",
                         "Sample text: adoption of the sample service rose 18% in 2025.", 2,
                         number=("Sample adoption growth in 2025", "18", "%"))
    offices = sample_fact("Sample: 1,240 offices were connected.",
                          "Sample text: by year end, 1,240 offices were connected.", 4,
                          number=("Sample offices connected by year end", "1,240", None))
    days = sample_fact("Sample: average processing took 4.5 days.",
                       "Sample text: average processing took 4.5 days.", 5,
                       number=("Sample average processing time", "4.5", "days"))
    satisfaction = sample_fact("Sample: 72% of users were satisfied.",
                               "Sample text: 72% of surveyed users were satisfied.", 6,
                               number=("Sample users satisfied with the service", "72", "%"))
    rural = sample_fact("Sample: rural offices adopted the service more slowly than urban offices.",
                        "Sample text: rural offices adopted the service more slowly than urban offices, "
                        "mainly because staff had less time for training.", 7)
    training = sample_fact("Sample: training was the most cited barrier.",
                           "Sample text: training was the barrier respondents cited most often.", 8)
    urban = sample_fact("Sample: urban offices led adoption.",
                        "Sample text: urban offices led adoption in every sample region.", 7)
    rec_training = sample_fact("Sample: extend training to rural offices first.",
                               "Sample text: we recommend extending training to rural offices first.", 10,
                               kind=FactKind.RECOMMENDATION)
    rec_measure = sample_fact("Sample: publish processing times every quarter.",
                              "Sample text: processing times should be published every quarter.", 10,
                              kind=FactKind.RECOMMENDATION)
    rec_support = sample_fact("Sample: add a support line for small offices.",
                              "Sample text: small offices asked for a dedicated support line.", 11,
                              kind=FactKind.RECOMMENDATION)
    survey = sample_fact("Sample: the survey covered four sample regions only.",
                         "Sample text: the survey covered four sample regions only.", 13, kind=FactKind.CAVEAT)
    provisional = sample_fact("Sample: figures for 2025 are provisional.",
                              "Sample text: all 2025 figures are provisional.", 13, kind=FactKind.CAVEAT)
    table = sample_table([
        ["Sample region", "2024", "2025"],
        ["Region A", "12.5", "18.0"],
        ["Region B", "9.0", "14.5"],
        ["Region C", "6.5", "8.0"],
        ["Region D", "4.0", "7.5"],
    ], 9)

    facts = (adoption, growth, offices, days, satisfaction, rural, training, urban, rec_training, rec_measure,
             rec_support, survey, provisional)
    slides = (
        Slide(slide_type=SlideType.TITLE,
              title="Sample deck: the sample service reaches more offices, but rural adoption lags",
              items=(item("Design specimen. All content is fictional and comes from no real document.", adoption),),
              notes="Specimen only. Fictional content for layout review."),
        Slide(slide_type=SlideType.EXECUTIVE_SUMMARY,
              title="Sample assertion: adoption rose 18% in 2025, led by urban offices",
              items=(item("Sample answer: adoption of the sample service rose in 2025.", adoption),
                     item("Sample answer: urban offices led adoption in every sample region.", urban),
                     item("Sample answer: rural offices adopted more slowly; training was the main barrier.",
                          rural, training),
                     item("Sample answer: extending training to rural offices first is the next step.", rec_training)),
              notes=None),
        Slide(slide_type=SlideType.KPI,
              title="Sample assertion: four sample numbers show the service is scaling",
              kpi_fact_ids=(growth.fact_id, offices.fact_id, days.fact_id, satisfaction.fact_id),
              items=(item("Sample context: each value above is copied by code from a verified number fact.",
                          growth, offices),),
              notes=None),
        Slide(slide_type=SlideType.FINDING,
              title="Sample assertion: rural offices adopt more slowly than urban offices",
              items=(item("Sample point: rural offices adopted the service more slowly.", rural),
                     item("Sample point: staff named training as the most cited barrier.", training),
                     item("Sample point: urban offices led adoption in every sample region.", urban)),
              notes=None),
        Slide(slide_type=SlideType.CHART,
              title="Sample assertion: every sample region grew between 2024 and 2025",
              chart=ChartSpec(table_id=table.table_id, x_column=0, y_columns=(1, 2), chart_type=ChartType.COLUMN),
              items=(item("Sample takeaway: Region A grew the most.", urban),
                     item("Sample takeaway: Region D is still the smallest.", rural)),
              notes=None),
        Slide(slide_type=SlideType.IMPLICATIONS,
              title="Sample assertion: four sample actions follow from these findings",
              items=(item("Sample action: extend training to rural offices first.", rec_training),
                     item("Sample action: publish processing times every quarter.", rec_measure),
                     item("Sample action: add a support line for small offices.", rec_support),
                     item("Sample action: repeat the survey once the 2025 figures are final.", provisional)),
              notes=None),
        Slide(slide_type=SlideType.LIMITATIONS,
              title="Sample assertion: two limits apply to these sample results",
              items=(item("Sample caveat: the survey covered four sample regions only.", survey),
                     item("Sample caveat: figures for the latest year are provisional.", provisional)),
              notes=None),
        Slide(slide_type=SlideType.SOURCES,
              title="Sources and verification: every sample claim traces to a source page",
              notes=None),
    )
    return DeckPlan(doc_id=SPECIMEN_DOC_ID, slides=slides), facts, (table,)


def main(out_path: Path = SPECIMEN_PATH) -> int:
    plan, facts, tables = specimen_inputs()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = render(plan, facts, tables, out_path, strict=True)
    for warning in report.warnings:
        print(f"warning: {warning}")
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else SPECIMEN_PATH))
