"""Renderer v1: DeckPlan + facts + tables -> editable .pptx through a gallery template.

The template owns every visual decision (docs/design/template-contract.md). This code picks a layout by name, fills
placeholders by name, inserts native charts into the chart placeholder, and measures text against each placeholder's
real box. On overflow it tries the next variant of the slide type, then splits the slide; a fact is never cut.
Values (KPI numbers, chart data, pages, quotes) are copied from facts and tables by code.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import PP_PLACEHOLDER

from matn_contracts.domain import ChartSpec, DeckPlan, Fact, Slide, SlideItem, Table, validate_deck_plan_against_facts
from matn_contracts.enums import ChartType, FactStatus, SlideType

from .fit import WIDTH_SAFETY, Box, Fitter, placeholder_style
from .measure import EMU_PER_PT
from .templates import LAYOUTS, validate_template

_PAGE_IN_ID = re.compile(r":p(\d{4,}):")
_NUMBER = re.compile(r"(?P<sign>[-−])?(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d+))?(?P<pct>%)?")
_LEAD = re.compile(r"^(?P<lead>[^:]{1,40}):\s+(?P<rest>\S.*)$", re.S)
_CHART_TYPES = {
    ChartType.BAR: XL_CHART_TYPE.BAR_CLUSTERED,
    ChartType.COLUMN: XL_CHART_TYPE.COLUMN_CLUSTERED,
    ChartType.LINE: XL_CHART_TYPE.LINE_MARKERS,
}
_ITEM_SLOT = re.compile(r"item_(\d)$")
UNIT_SCALE = 0.5  # a KPI unit is a second run at half the value size (template-contract.md §4)
KPI_STEPS = (1.0, 0.85, 0.7, 0.55)  # KPI values step down from the template's size until all fit one line
_KPI_SLOT = re.compile(r"kpi_value_(\d)$")


class DeckRenderError(ValueError):
    pass


class TemplateInvalidError(DeckRenderError):
    pass


@dataclass(frozen=True)
class Overflow:
    slide_number: int
    placeholder: str
    needed_emu: int
    available_emu: int


@dataclass(frozen=True)
class RenderReport:
    layouts: tuple[str, ...]  # layout used by each output slide, in order
    overflows: tuple[Overflow, ...]
    warnings: tuple[str, ...]


class DeckOverflowError(DeckRenderError):
    def __init__(self, report: RenderReport) -> None:
        where = ", ".join(f"slide {o.slide_number} {o.placeholder}" for o in report.overflows)
        super().__init__(f"TEXT_OVERFLOW: {where}")
        self.report = report


@lru_cache(maxsize=4)
def load_labels(language: str = "en") -> dict[str, Any]:
    return json.loads((Path(__file__).with_name("labels.json")).read_text(encoding="utf-8"))[language]


def page_number(block_or_table_id: str) -> int:
    """1-based physical PDF page encoded in a block_id or table_id."""
    match = _PAGE_IN_ID.search(block_or_table_id)
    if match is None:
        raise DeckRenderError(f"ID_HAS_NO_PAGE:{block_or_table_id}")
    return int(match.group(1)) + 1


@dataclass(frozen=True)
class _Content:
    """What one output slide shows. Splitting a slide splits `items`, `kpi_fact_ids` or `lines`."""
    slide_type: SlideType
    title: str
    items: tuple[SlideItem, ...] = ()
    kpi_fact_ids: tuple[str, ...] = ()
    chart: ChartSpec | None = None
    lines: tuple[str, ...] = ()
    line_fact_ids: tuple[str, ...] = ()
    notes: str | None = None
    section_number: int | None = None
    part: tuple[int, int] | None = None

    @property
    def fact_ids(self) -> tuple[str, ...]:
        ids = [fid for item in self.items for fid in item.fact_ids] + list(self.kpi_fact_ids) + list(self.line_fact_ids)
        return tuple(dict.fromkeys(ids))


@dataclass
class _Plan:
    layout: Any
    fills: dict[str, list[str]]
    content: _Content
    overflows: list[Overflow] = field(default_factory=list)
    units: dict[str, str] = field(default_factory=dict)  # kpi_value_N -> unit run text
    kpi_scale: float = 1.0  # one KPI_STEPS factor for every value on the slide

    @property
    def fits(self) -> bool:
        """A title overflow is reported but cannot be fixed by another variant or a split, so it does not count."""
        return all(o.placeholder == "title" for o in self.overflows)


def build_presentation(
    plan: DeckPlan,
    facts: tuple[Fact, ...],
    tables: tuple[Table, ...],
    template: Path,
    *,
    strict: bool = False,
    language: str = "en",
) -> tuple[Any, RenderReport]:
    report = validate_template(template)
    if not report.ok:
        raise TemplateInvalidError(f"TEMPLATE_INVALID:{Path(template).name}: " + "; ".join(report.errors))
    builder = _DeckBuilder(Presentation(str(template)), facts, tables, load_labels(language))
    prs = builder.build(plan)
    result = RenderReport(tuple(builder.layouts_used), tuple(builder.overflows), tuple(builder.warnings))
    if strict and result.overflows:
        raise DeckOverflowError(result)
    return prs, result


def render(
    plan: DeckPlan,
    facts: tuple[Fact, ...],
    tables: tuple[Table, ...],
    template: Path,
    out_path: Path,
    *,
    strict: bool = False,
    language: str = "en",
) -> RenderReport:
    prs, report = build_presentation(plan, facts, tables, template, strict=strict, language=language)
    prs.save(str(out_path))
    return report


class _DeckBuilder:
    def __init__(self, prs: Any, facts: tuple[Fact, ...], tables: tuple[Table, ...], labels: dict[str, Any]) -> None:
        self.prs = prs
        self.facts = {fact.fact_id: fact for fact in facts}
        self.tables = {table.table_id: table for table in tables}
        self.labels = labels
        self.fitter = Fitter()
        self.layouts = {layout.name: layout for layout in prs.slide_layouts}
        self.layouts_used: list[str] = []
        self.overflows: list[Overflow] = []
        self.warnings: list[str] = []
        self._styles: dict[tuple[str, str], Any] = {}

    # ---- deck ---------------------------------------------------------------------------------------------------

    def build(self, plan: DeckPlan) -> Any:
        validate_deck_plan_against_facts(plan, tuple(self.facts.values()))
        for slide in plan.slides:
            if slide.chart is not None and slide.chart.table_id not in self.tables:
                raise DeckRenderError(f"UNKNOWN_TABLE_ID:{slide.chart.table_id}")
            for fact_id in self._slide_fact_ids(slide):
                status = self.facts[fact_id].status
                if status is FactStatus.REJECTED:
                    raise DeckRenderError(f"REJECTED_FACT_CITED:{fact_id}")
                if status is not FactStatus.VERIFIED and f"UNVERIFIED_FACT:{fact_id}" not in self.warnings:
                    self.warnings.append(f"UNVERIFIED_FACT:{fact_id}")
        self.prs.core_properties.title = plan.slides[0].title

        cited = list(dict.fromkeys(fid for slide in plan.slides for fid in self._slide_fact_ids(slide)))
        contents = []
        dividers = 0
        for slide in plan.slides:
            content = _Content(slide.slide_type, slide.title, slide.items, slide.kpi_fact_ids, slide.chart,
                               notes=slide.notes)
            if slide.slide_type is SlideType.SECTION_DIVIDER:
                dividers += 1
                content = replace(content, section_number=dividers)
            elif slide.slide_type is SlideType.EVIDENCE_APPENDIX:
                content = self._appendix(content, cited)
            contents.append(content)

        planned: list[list[_Plan]] = [self._plan(content) for content in contents]
        for index, (slide, parts) in enumerate(zip(plan.slides, planned)):
            if slide.slide_type is SlideType.SOURCES:
                lines = self._sources_lines(plan, planned, cited)
                content = replace(contents[index], lines=tuple(lines))
                planned[index] = self._plan(content)
        for parts in planned:
            for part in parts:
                self._emit(part)
        return self.prs

    def _slide_fact_ids(self, slide: Slide) -> list[str]:
        return list(dict.fromkeys([fid for item in slide.items for fid in item.fact_ids] + list(slide.kpi_fact_ids)))

    # ---- planning: variant choice, measurement, split ------------------------------------------------------------

    def _candidates(self, content: _Content) -> list[Any]:
        prefix = f"matn:{content.slide_type.value}:"
        order = [name for name in LAYOUTS if name.startswith(prefix)]
        order += sorted(name for name in self.layouts if name.startswith(prefix) and name not in order)
        n_items, n_kpis = len(content.items), len(content.kpi_fact_ids)
        preferred = {
            (SlideType.FINDING, 2): "matn:finding:two-col",
            (SlideType.FINDING, 3): "matn:finding:cards-3",
        }.get((content.slide_type, n_items))
        if content.slide_type is SlideType.KPI and n_kpis <= 2:
            preferred = "matn:kpi:big-number"
        if preferred in order:
            order.remove(preferred)
            order.insert(0, preferred)
        fitting = [self.layouts[name] for name in order if self._holds(self.layouts[name], content)]
        # A layout whose decorated cards would stay empty is the last resort, never the first choice.
        fitting.sort(key=lambda layout: self._empty_cards(layout, content))
        if not fitting:
            raise DeckRenderError(f"NO_LAYOUT_FOR:{content.slide_type.value}:{n_items} items, {n_kpis} kpis")
        return fitting

    @staticmethod
    def _empty_cards(layout: Any, content: _Content) -> bool:
        if not any(shape.name == "card" and not shape.is_placeholder for shape in layout.shapes):
            return False
        item_slots = sum(bool(_ITEM_SLOT.match(ph.name)) for ph in layout.placeholders)
        return 0 < len(content.items) < item_slots

    @staticmethod
    def _holds(layout: Any, content: _Content) -> bool:
        """True when every item, KPI and line of `content` has a placeholder in `layout` (nothing is dropped)."""
        names = {ph.name for ph in layout.placeholders}
        item_slots = sum(bool(_ITEM_SLOT.match(n)) for n in names)
        kpi_slots = sum(bool(_KPI_SLOT.match(n)) for n in names)
        if len(content.kpi_fact_ids) > kpi_slots:
            return False
        if content.lines:
            return "body" in names
        if not content.items:
            return True
        if content.slide_type in (SlideType.TITLE, SlideType.SECTION_DIVIDER):
            return "subtitle" in names
        return len(content.items) <= item_slots if item_slots else "body" in names

    def _plan(self, content: _Content) -> list[_Plan]:
        attempts = [self._attempt(layout, content) for layout in self._candidates(content)]
        for attempt in attempts:
            if attempt.fits:
                return [attempt]
        halves = self._split(content)
        if halves is None:
            return [attempts[0]]
        first, second = (self._plan(half) for half in halves)
        parts = first + second
        total = len(parts)
        base = content.part
        renumbered = []
        for k, part in enumerate(parts, start=1):
            part.content = replace(part.content, part=(k, total) if base is None else part.content.part)
            renumbered.append(self._attempt(part.layout, part.content))
        return renumbered

    def _split(self, content: _Content) -> tuple[_Content, _Content] | None:
        if len(content.lines) >= 2:
            mid = (len(content.lines) + 1) // 2
            first_ids, second_ids = content.line_fact_ids[:mid], content.line_fact_ids[mid:]
            return (replace(content, lines=content.lines[:mid], line_fact_ids=first_ids),
                    replace(content, lines=content.lines[mid:], line_fact_ids=second_ids))
        if len(content.kpi_fact_ids) >= 2 and content.slide_type is SlideType.KPI:
            mid = (len(content.kpi_fact_ids) + 1) // 2
            return (replace(content, kpi_fact_ids=content.kpi_fact_ids[:mid]),
                    replace(content, kpi_fact_ids=content.kpi_fact_ids[mid:], items=()))
        if len(content.items) >= 2 and content.slide_type not in (SlideType.CHART, SlideType.TITLE):
            mid = (len(content.items) + 1) // 2
            return replace(content, items=content.items[:mid]), replace(content, items=content.items[mid:])
        return None

    def _attempt(self, layout: Any, content: _Content) -> _Plan:
        fills = self._fills(layout, content)
        units = {f"kpi_value_{n}": self._unit(fid) for n, fid in enumerate(content.kpi_fact_ids, start=1)}
        plan = _Plan(layout, fills, content, units={k: v for k, v in units.items() if v})
        by_name = {ph.name: ph for ph in layout.placeholders}
        if units:
            plan.kpi_scale = self._kpi_scale(layout, fills, units)
        for name, paragraphs in fills.items():
            if name == "source":
                continue  # the chip grows to its text
            ph = by_name[name]
            style = self._style(layout, ph)
            if name in units:  # value and unit stay on one line, at the slide's KPI step
                style = replace(style, size_pt=style.size_pt * plan.kpi_scale)
                inner = (ph.width - style.insets[0] - style.insets[2] - style.indent_emu) * WIDTH_SAFETY
                width = self._kpi_width(paragraphs[0], units[name], style)
                if width > inner:
                    plan.overflows.append(Overflow(0, name, int(width), int(inner)))
            needed = self.fitter.needed(paragraphs, style, Box(ph.width, ph.height))
            if needed > ph.height:
                plan.overflows.append(Overflow(0, name, int(needed), ph.height))
        return plan

    def _kpi_width(self, value: str, unit: str, style: Any) -> float:
        small = replace(style, size_pt=style.size_pt * UNIT_SCALE)
        return self.fitter.width(value, style) + self.fitter.width(unit, small)

    def _kpi_scale(self, layout: Any, fills: dict[str, list[str]], units: dict[str, str]) -> float:
        """Largest KPI_STEPS factor of the template's value size at which every value on the slide fits one line."""
        by_name = {ph.name: ph for ph in layout.placeholders}
        for scale in KPI_STEPS:
            fits = True
            for name, unit in units.items():
                ph = by_name[name]
                style = self._style(layout, ph)
                style = replace(style, size_pt=style.size_pt * scale)
                inner = (ph.width - style.insets[0] - style.insets[2] - style.indent_emu) * WIDTH_SAFETY
                fits &= self._kpi_width(fills[name][0], unit, style) <= inner
            if fits:
                return scale
        return KPI_STEPS[-1]

    def _unit(self, fact_id: str) -> str:
        unit = self.facts[fact_id].number_value.unit
        return "" if unit is None else unit if unit.startswith("%") else f" {unit}"

    def _style(self, layout: Any, ph: Any) -> Any:
        key = (layout.name, ph.name)
        if key not in self._styles:
            self._styles[key] = placeholder_style(ph)
        return self._styles[key]

    # ---- filling ----------------------------------------------------------------------------------------------

    def _fills(self, layout: Any, content: _Content) -> dict[str, list[str]]:
        names = {ph.name for ph in layout.placeholders}
        title = content.title
        if content.part is not None:
            title = self.labels["part_title"].format(title=title, k=content.part[0], n=content.part[1])
        fills: dict[str, list[str]] = {"title": [title]}
        texts = [item.text for item in content.items]

        if content.slide_type in (SlideType.TITLE, SlideType.SECTION_DIVIDER):
            if texts and "subtitle" in names:
                fills["subtitle"] = texts
        elif any(_ITEM_SLOT.match(n) for n in names):
            for n, text in enumerate(texts, start=1):
                lead = _LEAD.match(text)
                if f"item_{n}_title" in names:
                    fills[f"item_{n}_title"] = [lead["lead"] if lead else self.labels["item_ordinal"].format(n=n)]
                    fills[f"item_{n}"] = [lead["rest"] if lead else text]
                else:
                    fills[f"item_{n}"] = [text]
        elif content.lines:
            fills["body"] = list(content.lines)
        elif texts and "body" in names:
            fills["body"] = texts

        if content.section_number is not None:
            fills["section_number"] = [self.labels["section_number"].format(n=content.section_number)]
        for n, fact_id in enumerate(content.kpi_fact_ids, start=1):
            value = self.facts[fact_id].number_value
            fills[f"kpi_value_{n}"] = [value.value_as_written]
            fills[f"kpi_label_{n}"] = [value.label]
        if "quote" in names and content.items:
            evidence = self.facts[content.items[0].fact_ids[0]].evidence[0]
            fills["quote"] = [f"“{evidence.quote}”"]
            if "attribution" in names:
                fills["attribution"] = [self.labels["page"].format(n=page_number(evidence.block_id))]
        if "source" in names:
            fills["source"] = [self._pages_text(content) or self.labels["no_pages"]]
        return fills

    def _pages_text(self, content: _Content) -> str:
        pages = {page_number(ev.block_id) for fid in content.fact_ids for ev in self.facts[fid].evidence}
        entries = [(n, self.labels["page"].format(n=n)) for n in sorted(pages)]
        if content.chart is not None:
            table = self.tables[content.chart.table_id]
            entries.append((table.page_index + 1,
                            self.labels["page"].format(n=table.page_index + 1) + self.labels["table_suffix"]))
        if not entries:
            return ""
        texts = [text for _, text in sorted(entries)]
        first = texts[0]
        rest = [t.removeprefix(self.labels["page"].format(n="")) for t in texts[1:]]
        return self.labels["pages_joiner"].join([first, *rest])

    def _appendix(self, content: _Content, cited: list[str]) -> _Content:
        lines, ids = [], []
        for fact_id in cited:
            fact = self.facts[fact_id]
            if fact.number_value is None:
                continue
            value = fact.number_value
            for ev in fact.evidence:
                lines.append(self.labels["appendix_line"].format(
                    value=value.value_as_written + self._unit(fact_id), label=value.label,
                    page=self.labels["page"].format(n=page_number(ev.block_id)), quote=ev.quote))
                ids.append(fact_id)
        if not lines:
            lines = [self.labels["appendix_empty"]]
        return replace(content, lines=tuple(lines), line_fact_ids=tuple(ids))

    def _sources_lines(self, plan: DeckPlan, planned: list[list[_Plan]], cited: list[str]) -> list[str]:
        names = self.labels["slide_type_names"]
        lines = [item.text for slide in plan.slides if slide.slide_type is SlideType.SOURCES for item in slide.items]
        number = 0
        for slide, parts in zip(plan.slides, planned):
            for part in parts:
                number += 1
                if slide.slide_type in (SlideType.SOURCES, SlideType.TITLE, SlideType.SECTION_DIVIDER):
                    continue
                pages = self._pages_text(part.content) or self.labels["no_pages"]
                lines.append(self.labels["sources_line"].format(n=number, name=names[slide.slide_type.value],
                                                                pages=pages))
        verified = sum(self.facts[fid].status is FactStatus.VERIFIED for fid in cited)
        all_pages = sorted({page_number(ev.block_id) for fid in cited for ev in self.facts[fid].evidence}
                           | {self.tables[s.chart.table_id].page_index + 1 for s in plan.slides if s.chart})
        lines += [
            self.labels["facts_verified"].format(verified=verified, total=len(cited)),
            self.labels["pages_cited"].format(pages=self.labels["pages_joiner"].join(map(str, all_pages))),
            self.labels["document"].format(doc=f"{plan.doc_id[:19]}…"),
            self.labels["method"],
        ]
        return lines

    # ---- emitting -----------------------------------------------------------------------------------------------

    def _emit(self, plan: _Plan) -> None:
        slide = self.prs.slides.add_slide(plan.layout)
        number = len(self.prs.slides)
        self.layouts_used.append(plan.layout.name)
        self.overflows += [replace(o, slide_number=number) for o in plan.overflows]
        layout_names = {ph.placeholder_format.idx: ph.name for ph in plan.layout.placeholders}
        for shape in list(slide.placeholders):
            name = layout_names.get(shape.placeholder_format.idx)
            shape.name = name or shape.name
            if name == "chart" and plan.content.chart is not None:
                self._chart(shape, plan.content.chart)
            elif name in plan.fills:
                self._fill_text(shape, plan.fills[name])
                if _KPI_SLOT.match(name):
                    size = self._style(plan.layout, self._layout_ph(plan.layout, name)).size_pt * plan.kpi_scale
                    if plan.kpi_scale != 1.0:
                        shape.text_frame.paragraphs[0].runs[0].font.size = int(size * EMU_PER_PT)
                    if name in plan.units:
                        run = shape.text_frame.paragraphs[0].add_run()
                        run.text = plan.units[name]
                        run.font.size = int(size * UNIT_SCALE * EMU_PER_PT)
                if name == "source":
                    self._fit_chip(shape, plan)
            else:
                shape._element.getparent().remove(shape._element)
        self._notes(slide, plan.content)

    def _fill_text(self, shape: Any, paragraphs: list[str]) -> None:
        frame = shape.text_frame
        for index, text in enumerate(paragraphs):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.add_run().text = text

    @staticmethod
    def _layout_ph(layout: Any, name: str) -> Any:
        return next(ph for ph in layout.placeholders if ph.name == name)

    def _fit_chip(self, shape: Any, plan: _Plan) -> None:
        ph = self._layout_ph(plan.layout, "source")
        width = self.fitter.text_width(plan.fills["source"][0], self._style(plan.layout, ph))
        left, top, height = shape.left, shape.top, shape.height
        shape.left, shape.top, shape.width, shape.height = left, top, max(width, height * 2), height

    def _notes(self, slide: Any, content: _Content) -> None:
        lines = [content.notes, ""] if content.notes else []
        table = self.tables.get(content.chart.table_id) if content.chart else None
        if content.fact_ids or table is not None:
            lines.append(self.labels["notes_heading"])
            for fid in content.fact_ids:
                fact = self.facts[fid]
                for ev in fact.evidence:
                    page = self.labels["page"].format(n=page_number(ev.block_id))
                    lines.append(self.labels["notes_line"].format(fact_id=fid, page=page, status=fact.status.value,
                                                                  quote=ev.quote))
            if table is not None:
                page = self.labels["page"].format(n=table.page_index + 1)
                lines.append(self.labels["notes_table"].format(table_id=table.table_id, page=page))
        if lines:
            slide.notes_slide.notes_text_frame.text = "\n".join(lines)

    # ---- charts -------------------------------------------------------------------------------------------------

    def _chart(self, placeholder: Any, spec: ChartSpec) -> None:
        if placeholder.placeholder_format.type != PP_PLACEHOLDER.CHART:
            raise DeckRenderError("CHART_PLACEHOLDER_WRONG_KIND")
        table = self.tables[spec.table_id]
        cells = {(cell.row, cell.col): cell.text.strip() for cell in table.cells}
        rows = sorted({cell.row for cell in table.cells} - set(table.header_rows))

        def cell_text(row: int, col: int) -> str:
            text = cells.get((row, col), "")
            if not text:
                raise DeckRenderError(f"CHART_CELL_MISSING:{table.table_id}:r{row}c{col}")
            return text

        parsed, data = [], []
        for n, col in enumerate(spec.y_columns, start=1):
            header = " ".join(cells[(r, col)] for r in table.header_rows if cells.get((r, col)))
            values = []
            for row in rows:
                text = cell_text(row, col)
                match = _NUMBER.fullmatch(text)
                if match is None:
                    raise DeckRenderError(f"CHART_CELL_NOT_NUMERIC:{table.table_id}:r{row}c{col}:{text!r}")
                parsed.append(match)
                value = Decimal(match["int"].replace(",", "") + "." + (match["frac"] or "0"))
                values.append(float(-value if match["sign"] else value))
            data.append((header or self.labels["series_fallback"].format(n=n), values))

        decimals = max(len(m["frac"] or "") for m in parsed)
        number_format = "#,##0" if any("," in m["int"] for m in parsed) else "0"
        number_format += ("." + "0" * decimals if decimals else "") + ('"%"' if any(m["pct"] for m in parsed) else "")
        chart_data = CategoryChartData(number_format=number_format)
        chart_data.categories = [cell_text(row, spec.x_column) for row in rows]
        for name, values in data:
            chart_data.add_series(name, values)
        frame = placeholder.insert_chart(_CHART_TYPES[spec.chart_type], chart_data)
        frame.name = "chart"
        chart = frame.chart
        # Trick 12: direct value labels, no gridlines, a legend only for two or more series. Colors stay theme.
        chart.has_title = False
        chart.has_legend = len(data) > 1
        if chart.has_legend:
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = False
        plot = chart.plots[0]
        plot.vary_by_categories = False
        plot.has_data_labels = True
        plot.data_labels.number_format = number_format
        plot.data_labels.number_format_is_linked = False
        plot.data_labels.position = (XL_LABEL_POSITION.ABOVE if spec.chart_type is ChartType.LINE
                                     else XL_LABEL_POSITION.OUTSIDE_END)
        chart.value_axis.has_major_gridlines = False
        chart.value_axis.visible = False
        if spec.chart_type is ChartType.BAR:
            chart.category_axis.reverse_order = True  # first table row on top, as read
