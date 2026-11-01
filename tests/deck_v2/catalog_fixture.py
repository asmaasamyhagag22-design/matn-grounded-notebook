"""A small synthetic Evidence Catalog that exercises every deck v2 slide kind (fictional, public-safe content)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw

from matn_deck.catalog import (
    Axis, Context, EvidenceCatalog, Figure, Gap, Plan, Requirement, Source, Span, SynthesisSentence, Unit,
)
from matn_deck.numeric import facts_for_unit

DOC_A = "sha256-" + "a" * 64
DOC_B = "sha256-" + "b" * 64


def _span(doc: str, n: int, text: str, page: int = 0) -> Span:
    return Span(doc_id=doc, block_id=f"{doc}:p{page:04d}:{n:016x}", start=0, end=len(text), quote=text,
                page_index=page, page_label=None, bbox=(10.0, 10.0, 200.0, 40.0))


def unit(uid: str, axis: str, text: str, doc: str = DOC_A, source: str = "S1", page: int = 0,
         context: tuple[Context, ...] = ()) -> Unit:
    return Unit(id=uid, axis=axis, text=text, span=_span(doc, int(uid[1:]), text, page), source=source,
                source_type="government", status="verified", binding=hashlib.sha256(uid.encode()).hexdigest(),
                context=context)


def figure_pdf(folder: Path) -> Path:
    """A one-page PDF with a drawn bar chart region (the figure) at a known bbox."""
    image = Image.new("RGB", (612, 792), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 200, 500, 450), outline="black", width=3)
    for i, h in enumerate((120, 200, 80)):
        draw.rectangle((150 + i * 110, 440 - h, 220 + i * 110, 440), fill=(40, 110, 160))
    path = Path(folder) / "figure-source.pdf"
    image.save(path, "PDF", resolution=72)
    return path


def make_catalog(folder: Path | None = None, *, with_figure: bool = True) -> EvidenceCatalog:
    ctx = Context(quote="Agencies reported this in the 2024 annual review.", kind="required",
                  origin="source-backed context", span=_span(DOC_A, 99, "Agencies reported this in the 2024 annual review."))
    units = (
        unit("U1", "a1", "Shorter queues follow from online booking."),
        unit("U2", "a1", "Service centres that publish wait times see fewer repeat visits, according to the review of "
                         "regional offices.", context=(ctx,)),
        unit("U3", "a1", "Staff rotation plans are reviewed every quarter by the operations unit."),
        unit("U4", "a2", "30% of firms will train staff in Egypt by 2030."),
        unit("U5", "a2", "55% of firms will hire staff in Egypt by 2030."),
        unit("U6", "a3", "41% of firms will adopt AI tools in Egypt by 2030.", page=2),
        unit("U7", "a3", "45% of firms will adopt AI tools in Egypt by 2030.", doc=DOC_B, source="S2", page=0),
        unit("U8", "a5", "In 2022, 30% of firms will train staff in Egypt."),
        unit("U9", "a5", "In 2024, 38% of firms will train staff in Egypt."),
    )
    numbers = tuple(f for u in units for f in facts_for_unit(u))
    figures = ()
    if with_figure and folder is not None:
        pdf = figure_pdf(folder)
        figures = (Figure(id="F1", doc_id=DOC_A, source="S1", page_index=0, bbox=(100.0, 200.0, 500.0, 450.0),
                          caption="Figure 1 Queue length by office", caption_block_id=f"{DOC_A}:p0000:{7:016x}",
                          axis="a1", unit_ids=("U1",), pdf=str(pdf)),)
    plan = Plan(topic="Reducing waiting times in public offices", audience="service managers",
                goal="A bounded briefing", language="English",
                axes=(Axis("a1", "queue_practices"), Axis("a2", "Workforce Plans"), Axis("a3", "Technology Adoption"),
                      Axis("a4", "Funding"), Axis("a5", "Training Trend")),
                requirements=(Requirement("a1", "a1", "list practical steps", True),
                              Requirement("a4", "a4", "identify funding sources for queue systems", True)))
    sources = (Source(id="S1", doc_id=DOC_A, type="government", publisher="Example Ministry", title="Annual review",
                      url="https://example.gov/review", accessed="2026-10-28"),
               Source(id="S2", doc_id=DOC_B, type="international organization", publisher="Example Agency",
                      title=None, url="https://example.int/report", accessed="2026-10-27"))
    synthesis = (SynthesisSentence("a2", "Firms plan both training and hiring by 2030.", ("U4", "U5")),)
    gaps = (Gap(requirement="a4", axis="a4", label="Funding", missing=("identify funding sources for queue systems",)),)
    return EvidenceCatalog(plan=plan, units=units, sources=sources, synthesis=synthesis, numbers=numbers, gaps=gaps,
                           figures=figures, origin={"adapter": "test"}).validate()
