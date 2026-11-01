"""Deck v2 renderer: storyboard -> editable .pptx through a gallery template (ADR-0022, ADR-0024).

The storyboard (storyboard_v2.py) decides what each slide says; this module only lays it out, through the existing
generate-and-score engine (`template_renderer._DeckBuilder`): reference layouts of the template are filled
(edit-based), candidates are measured with the deck's fonts and width safety, and slides that do not fit are
stepped down within the template minimum or split. Native tables (key numbers) and source figures are placed by
code in the template's content area. Every output slide is recorded in a manifest with the strings it may show,
so the QA gate can check the saved file independently.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt

from matn_contracts.domain import ChartSpec, EvidenceRef, Fact, NumberFactValue, SlideItem, Table, TableCell
from matn_contracts.enums import ChartType, FactKind, FactStatus, Importance, SlideType

from .catalog import EvidenceCatalog, NumericFact
from .figures import crop_figure
from .fit import Fitter
from .scoring import EMU_PER_PT, Rect
from .storyboard_v2 import LABELS, Controls, SlideSpec, Storyboard, build_storyboard
from .template_renderer import CONTENT_TYPES, RenderReport, TemplateInvalidError, _Content, _DeckBuilder, _Plan, load_labels
from .templates import validate_template

DECK_SAFETY = 0.91  # 9 % width headroom: LibreOffice and PowerPoint may still differ slightly (ADR-0020)
FONT_PROFILES = ("template", "office")
ASSERTION_VARIANTS = (
    "matn:finding:cards-3", "matn:finding:grid-2x2", "matn:executive_summary:default",
    "matn:executive_summary:grid-2x2", "matn:implications:cards-3", "matn:implications:default",
    "matn:closing:default", "matn:limitations:default",
)
DISAGREE_VARIANTS = ("matn:executive_summary:default", "matn:closing:default")  # rows: "<publisher> states" | unit
# Smallest text per list slide: claim-bearing lists keep the body minimum (16 pt); reference lists may go to 12 pt.
LIST_MIN_PT = {"agenda": 16, "gaps": 16, "figure": 16, "sources": 12, "methods": 12}
LIST_START_PT = {"agenda": 24, "gaps": 24}  # short lists start larger than body text and step down
# LibreOffice turns a layout's extra placeholders into master shapes and draws them on every slide that uses the
# layout; marker placeholders are filled circles with prompt text, so layouts with marker slots are never used.
UNFLOORED = {"title", "source", "section_number", "subtitle"}  # titles have their own minimum; the chip is a label
TABLE_LINE_HEADROOM = 1.15  # LibreOffice lays table rows out with the font's own line height, not 1.2 em
EXCLUDED_RULES = {"leads", "ordered", "quote", "pictogram", "progress", "decisions"}
TABLE_COLUMNS = (0.15, 0.12, 0.2, 0.53)  # numbers, period, scope, statement
CELL_MARGIN = (91440, 45720)  # python-pptx/OOXML default cell margins (left/right, top/bottom)
GAP_PT = 8


class DeckBuildError(ValueError):
    pass


def _fact_id(block_id: str, statement: str) -> str:
    return Fact.create(kind=FactKind.FINDING, statement=statement, attributed_to=None,
                       evidence=(EvidenceRef(block_id=block_id, quote="x", char_start=None, char_end=None),),
                       importance=Importance.IMPORTANT, status=FactStatus.VERIFIED, reject_reasons=(),
                       number_value=None).fact_id


def engine_facts(catalog: EvidenceCatalog) -> tuple[dict[str, str], dict[str, str], tuple[Fact, ...]]:
    """Engine Fact objects for every unit (finding) and every numeric fact (number, labelled by letter only)."""
    unit_fact, number_fact, facts = {}, {}, []
    for unit in catalog.units:
        evidence = EvidenceRef(block_id=unit.span.block_id, quote=unit.span.quote.strip() or unit.text,
                               char_start=None, char_end=None)
        fact = Fact.create(kind=FactKind.FINDING, statement=f"{unit.id}: {unit.text}", attributed_to=None,
                           evidence=(evidence,), importance=Importance.IMPORTANT, status=FactStatus.VERIFIED,
                           reject_reasons=(), number_value=None)
        unit_fact[unit.id] = fact.fact_id
        facts.append(fact)
    for n in catalog.numbers:
        evidence = EvidenceRef(block_id=n.span.block_id, quote=n.span.quote.strip() or n.value_as_written,
                               char_start=None, char_end=None)
        fact = Fact.create(kind=FactKind.NUMBER, statement=f"{n.id}: {n.value_as_written}", attributed_to=None,
                           evidence=(evidence,), importance=Importance.SUPPORTING, status=FactStatus.VERIFIED,
                           reject_reasons=(), number_value=NumberFactValue(label=n.id, value_as_written=n.value_as_written,
                                                                           unit=None, page_label=None))
        number_fact[n.id] = fact.fact_id
        facts.append(fact)
    return unit_fact, number_fact, tuple(facts)


def _item(text: str, fact_ids: tuple[str, ...] = ()) -> SlideItem:
    return SlideItem.model_construct(text=text, fact_ids=fact_ids)  # v2 bullets are full verified sentences


def bullet_text(bullet) -> str:
    """One bullet as shown: the unit text and its marker, then any required context on its own line."""
    text = f"{bullet.text.text} {bullet.text.marker}".strip()
    for ctx in bullet.context:
        text += f"\n{LABELS['context']}: “{ctx.text}” {ctx.marker}".rstrip()
    return text


def unit_label(n: NumericFact) -> str:
    return {"": "", "ratio": ""}.get(n.unit, n.unit)


@dataclass
class SlideRecord:
    """What one output slide may show, for the independent QA gate."""
    slide: int
    spec: int
    kind: str
    part: tuple[int, int] | None
    layout: str
    title: str
    allowed: list[dict] = field(default_factory=list)  # {"text", "kind", "ref", "marker"}
    figure: str | None = None
    picture: str | None = None
    chart: list[dict] | None = None
    table: list[list[str]] | None = None
    contrast: list[dict] = field(default_factory=list)  # {"name", "ratio", "size_pt", "bold"} as measured
    exclude: list[str] = field(default_factory=list)  # layouts excluded for this slide by a QA re-layout


class V2Builder(_DeckBuilder):
    def __init__(self, prs: Any, catalog: EvidenceCatalog, template: Path, *, safety: float = DECK_SAFETY,
                 assets: Path | None = None, exclude: dict[int, set[str]] | None = None) -> None:
        self.catalog = catalog
        self.unit_fact, self.number_fact, facts = engine_facts(catalog)
        super().__init__(prs, facts, (), load_labels("en"), Path(template))
        self.fitter = Fitter(safety, natural_lines=True)
        self.exclude = exclude or {}  # storyboard slide index -> layouts a QA re-layout ruled out
        self.assets = Path(assets) if assets else None
        self.specs: tuple[SlideSpec, ...] = ()
        self.storyboard: Storyboard | None = None
        self.table_rows: dict[tuple[int, Any], list[list[str]]] = {}
        self.records: list[SlideRecord] = []
        self._current: _Content | None = None
        self._size_override: dict[str, float] = {}

    # ---- measurement shared with the storyboard ---------------------------------------------------------------

    def headline_fits(self) -> Callable[[str], bool]:
        """Does a headline (with a citation marker) fit the title box at the minimum title size?"""
        layout = self.layouts["matn:limitations:default"]
        ph = self._layout_ph(layout, "title")
        size = float(self.cfg["title_sizes"][-1])

        def fits(text: str) -> bool:
            sample = text + " [9]"
            return self._extent([sample], self._title_style(layout, ph, size, sample), ph.width)[0] <= ph.height
        return fits

    # ---- engine overrides --------------------------------------------------------------------------------------

    def _spec(self, content: _Content) -> SlideSpec:
        return self.specs[content.plan_index]

    def _attempts(self, content: _Content, previous: str | None) -> list[_Plan]:
        self._current = content
        excluded = self.exclude.get(content.plan_index)
        if excluded:
            names = [n for n in self._variant_order(content.slide_type) if self._valid(n, content)]
            if not names:  # nothing else can show this content: keep the original candidates, the QA flags it
                self.exclude = {k: v for k, v in self.exclude.items() if k != content.plan_index}
        return super()._attempts(content, previous)

    def _variant_order(self, slide_type: SlideType) -> list[str]:
        if self.storyboard is not None and self._current is not None:
            from .edits import layout_overrides
            forced = layout_overrides(self.storyboard).get(self._current.plan_index)
            if forced:
                return [forced]
        kind = self._spec(self._current).kind if self._current is not None else ""
        if kind == "assertion":
            return list(ASSERTION_VARIANTS)
        if kind == "disagree":
            return list(DISAGREE_VARIANTS)
        return super()._variant_order(slide_type)

    def _valid(self, name: str, content: _Content) -> bool:
        spec = self.variants.get(name, {})
        if spec.get("valid", {}).get("requires") in EXCLUDED_RULES or spec.get("hero_panel"):
            return False
        if "quote" in spec.get("fixed", {}):
            return False
        slots = spec.get("slots", {})
        if "marker" in slots.get("stack", []) + slots.get("left", []) + slots.get("right", []):
            return False
        if name in self.exclude.get(content.plan_index, ()):
            return False
        return super()._valid(name, content)

    def _style(self, layout: Any, ph: Any):
        style = super()._style(layout, ph)
        size = getattr(self, "_size_override", {}).get(ph.name)
        return replace(style, size_pt=size) if size is not None else style

    def _ladder(self, base: float, minimum: float) -> list[float]:
        return list(dict.fromkeys(max(minimum, round(base * f)) for f in (1.0, 0.9, 0.8, 0.7, 0.6)))

    def _evaluate(self, layout: Any, content: _Content, order: tuple[int, int, int], previous_variant: str | None
                  ) -> _Plan:
        """Title subtitles and list slides step their text down from the template size (never below the minimum
        for that text: LIST_MIN_PT) until it fits; the chosen size is written on the runs. Everything else is the
        engine's own type scale."""
        names = {p.name for p in layout.placeholders}
        kind = self._spec(content).kind
        if content.slide_type is SlideType.TITLE and "subtitle" in names:
            return self._floor(self._stepped(layout, content, order, previous_variant, "subtitle",
                                             super()._style(layout, self._layout_ph(layout, "subtitle")).size_pt,
                                             float(self.cfg["minimums"]["body_pt"])), kind)
        if kind in LIST_MIN_PT and content.lines and "body" in names:
            reference = self.layouts["matn:limitations:default"]
            base = max(super()._style(reference, self._layout_ph(reference, "body")).size_pt,
                       float(LIST_START_PT.get(kind, 0)))
            return self._floor(self._stepped(layout, content, order, previous_variant, "body", base,
                                             float(LIST_MIN_PT[kind])), kind)
        floor = float(LIST_MIN_PT.get(kind, self.cfg["minimums"]["body_pt"]))
        raised = {ph.name: floor for ph in layout.placeholders if ph.name not in UNFLOORED
                  and not ph.name.startswith("marker_") and super()._style(layout, ph).size_pt + 1e-6 < floor}
        self._size_override = raised  # a template size under the floor is measured and written at the floor
        try:
            plan = super()._evaluate(layout, content, order, previous_variant)
        finally:
            self._size_override = {}
        for name in raised:
            if name in plan.fills and name not in plan.sizes:
                plan.sizes[name] = floor
        return self._floor(plan, kind)

    def _floor(self, plan: _Plan, kind: str) -> _Plan:
        """Deck v2 text floors: claim text never below the body minimum, reference lists never below 12 pt."""
        floor = float(LIST_MIN_PT.get(kind, self.cfg["minimums"]["body_pt"]))
        for name, size in plan.sizes.items():
            if name not in UNFLOORED and size + 1e-6 < floor:
                plan.score.hard.append(f"TEXT_TOO_SMALL:{name}:{size:g}")
        return plan

    def _stepped(self, layout: Any, content: _Content, order: tuple[int, int, int], previous_variant: str | None,
                 name: str, base: float, minimum: float) -> _Plan:
        plan = None
        for size in self._ladder(base, minimum):
            self._size_override = {name: size}
            try:
                plan = super()._evaluate(layout, content, order, previous_variant)
            finally:
                self._size_override = {}
            plan.sizes[name] = size
            if not any(o.placeholder == name for o in plan.overflows) and \
                    not any(h.startswith("OVERFLOW") for h in plan.score.hard):
                break
        return plan

    def _split_decisions(self, content: _Content):
        return list(content.items), []

    def _hero_number(self, content: _Content):
        return None

    def _callout(self, *args: Any, **kwargs: Any) -> None:
        """No derived callouts ("highest"): the data labels show each copied value."""

    def _chip(self, content: _Content) -> str:
        spec = self._spec(content)
        markers = [spec.title.marker] + [b.text.marker for b in spec.bullets] + [t.marker for t in spec.lines]
        markers += [c.marker for b in spec.bullets for c in b.context]
        found = list(dict.fromkeys(m for m in markers if m))
        if spec.kind == "key_numbers":
            rows = self.table_rows.get((content.plan_index, content.part), [])
            found = list(dict.fromkeys(m for row in rows for m in [row[-1].rsplit(" ", 1)[-1]] if m.startswith("[")))
        if spec.kind in ("title", "agenda", "gaps", "sources", "methods") or not found:
            return ""
        return f"{LABELS['sources']} " + " ".join(sorted(found, key=lambda m: int(m.strip("[]"))))

    def _pages_text(self, content: _Content) -> str:
        return self._chip(content)

    def _fills(self, layout: Any, content: _Content, spec: dict) -> dict[str, list[str]]:
        fills = super()._fills(layout, content, spec)
        story = self._spec(content)
        for key in [k for k in fills if k in ("quote", "attribution") or k.startswith("kpi_")]:
            del fills[key]
        for n, item in enumerate(content.items, start=1):
            if f"item_{n}" in fills:
                fills[f"item_{n}"] = [item.text]
            if f"item_{n}_title" in fills:
                titles = story.item_titles
                fills[f"item_{n}_title"] = [titles[n - 1].text if n <= len(titles)
                                            else self.labels["item_ordinal"].format(n=n)]
        chip = self._chip(content)
        if "source" in fills:
            if chip:
                fills["source"] = [chip]
            else:
                del fills["source"]
        return fills

    def _fill_text(self, shape: Any, paragraphs: list[str], size: float | None) -> None:
        frame = shape.text_frame
        for index, text in enumerate(paragraphs):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            for k, line in enumerate(text.split("\n")):
                if k:
                    paragraph.add_line_break()
                run = paragraph.add_run()
                run.text = line
                if size:
                    run.font.size = int(size * EMU_PER_PT)

    def _notes(self, slide: Any, content: _Content) -> None:
        spec = self._spec(content)
        lines = list(spec.notes)
        if spec.kind == "assertion" and spec.title.kind == "axis":
            lines.insert(0, "Headline: the plan's axis title (no verified sentence fit the title box).")
        if lines:
            slide.notes_slide.notes_text_frame.text = "\n".join(lines)

    # ---- contents ----------------------------------------------------------------------------------------------

    def _contents(self, index: int, spec: SlideSpec) -> list[_Content]:
        title = f"{spec.title.text} {spec.title.marker}".strip()
        part = spec.part
        if spec.kind == "title":
            return [_Content(SlideType.TITLE, spec.title.text, tuple(_item(t.text) for t in spec.lines),
                             plan_index=index)]
        if spec.kind in ("agenda", "gaps", "methods"):  # list slides: laid out like Sources, not scored for visuals
            return [_Content(SlideType.SOURCES, title, lines=tuple(t.text for t in spec.lines), plan_index=index)]
        if spec.kind == "sources":
            return [_Content(SlideType.SOURCES, title, lines=tuple(f"{t.marker} {t.text}" for t in spec.lines),
                             plan_index=index)]
        if spec.kind in ("assertion", "disagree"):
            items = tuple(_item(bullet_text(b), (self.unit_fact[b.unit_id],)) for b in spec.bullets)
            return [_Content(SlideType.FINDING, title, items, part=part, plan_index=index)]
        if spec.kind == "figure":
            line = " ".join(f"{t.text} {t.marker}".strip() for t in spec.lines)
            return [_Content(SlideType.SOURCES, title, lines=(line,), plan_index=index)]
        if spec.kind == "chart":  # the statements are cited bullets on the axis slide; here: chart, chip, notes
            table = self._chart_table(spec)
            self.tables[table.table_id] = table
            chart = ChartSpec(table_id=table.table_id, x_column=0, y_columns=(1,), chart_type=ChartType.BAR)
            return [_Content(SlideType.CHART, title, chart=chart, plan_index=index)]
        if spec.kind == "key_numbers":
            chunks = self._table_chunks(spec)
            contents = []
            for k, rows in enumerate(chunks, start=1):
                part = (k, len(chunks)) if len(chunks) > 1 else None
                self.table_rows[(index, part)] = rows
                contents.append(_Content(SlideType.SOURCES, title, part=part, plan_index=index))
            return contents
        raise DeckBuildError(f"SLIDE_KIND_UNKNOWN:{spec.kind}")

    def _number(self, fact_id: str) -> NumericFact:
        return next(n for n in self.catalog.numbers if n.id == fact_id)

    def _chart_table(self, spec: SlideSpec) -> Table:
        facts = [self._number(f) for f in spec.facts]
        rows = [["", LABELS["col_numbers"]]] + [[c.text, f.value_as_written] for c, f in zip(spec.item_titles, facts)]
        cells = tuple(TableCell(row=r, col=c, text=text, bbox=(10.0 + 50 * c, 10.0 + 20 * r, 59.0 + 50 * c,
                                                               29.0 + 20 * r), is_header=r == 0)
                      for r, row in enumerate(rows) for c, text in enumerate(row))
        doc = "sha256-" + hashlib.sha256("|".join(spec.facts).encode()).hexdigest()
        return Table.create(doc_id=doc, page_index=0, bbox=(10.0, 10.0, 160.0, 30.0 + 20 * len(rows)),
                            header_rows=(0,), cells=cells)

    # ---- key numbers table -------------------------------------------------------------------------------------

    def _table_style(self):
        layout = self.layouts["matn:limitations:default"]
        style = self._style(layout, self._layout_ph(layout, "body"))
        size = float(self.cfg["minimums"]["body_pt"])
        return replace(style, size_pt=size, space_before_pt=0.0, space_after_pt=0.0, indent_emu=0,
                       insets=(CELL_MARGIN[0], CELL_MARGIN[1], CELL_MARGIN[0], CELL_MARGIN[1]))

    def _table_header(self) -> list[str]:
        return [LABELS["col_numbers"], LABELS["col_period"], LABELS["col_scope"], LABELS["col_statement"]]

    def _key_rows(self, spec: SlideSpec) -> list[list[str]]:
        storyboard = self.storyboard
        rows, by_unit = [], {}
        for fid in spec.facts:
            n = self._number(fid)
            by_unit.setdefault(n.unit_id or n.id, []).append(n)
        for key, facts in by_unit.items():
            first = facts[0]
            numbers = "; ".join(f"{n.value_as_written} {unit_label(n)}".strip() for n in facts)
            period = ", ".join(first.period) or LABELS["not_stated"]
            scope = " · ".join(p for p in (first.population, first.geography) if p) or LABELS["not_stated"]
            if first.origin == "unit":
                unit = self.catalog.unit(first.unit_id)
                statement = f"{unit.text.strip()} {storyboard.marker(unit.source)}"
            else:
                statement = f"{first.span.block_id.removeprefix('json:')} {storyboard.marker(first.source)}"
            rows.append([numbers, period, scope, statement])
        return rows

    def _row_height(self, row: list[str], widths: list[float], style) -> float:
        line = self.fitter.line_height(style)
        tallest = 0.0
        for text, width in zip(row, widths):
            inner = (width - 2 * CELL_MARGIN[0]) * self.fitter.safety
            lines = sum(len(self.fitter.wrap(part, inner, style)) for part in text.split("\n"))
            tallest = max(tallest, lines * line * TABLE_LINE_HEADROOM)
        return tallest + 2 * CELL_MARGIN[1]

    def _table_chunks(self, spec: SlideSpec) -> list[list[list[str]]]:
        style = self._table_style()
        widths = [self.area.w * share for share in TABLE_COLUMNS]
        header_h = self._row_height(self._table_header(), widths, replace(style, bold=True))
        chunks, current, used = [], [], header_h
        for row in self._key_rows(spec):
            h = self._row_height(row, widths, style)
            if current and used + h > self.area.h:
                chunks.append(current)
                current, used = [], header_h
            current.append(row)
            used += h
        chunks.append(current)
        return chunks

    def _place_table(self, slide: Any, rows: list[list[str]]) -> list[list[str]]:
        style = self._table_style()
        widths = [self.area.w * share for share in TABLE_COLUMNS]
        grid = [self._table_header()] + rows
        heights = [self._row_height(r, widths, replace(style, bold=i == 0)) for i, r in enumerate(grid)]
        shape = slide.shapes.add_table(len(grid), len(TABLE_COLUMNS), Emu(int(self.area.x)), Emu(int(self.area.y)),
                                       Emu(int(self.area.w)), Emu(int(sum(heights))))
        shape.name = "key_numbers_table"
        table = shape.table
        tbl_pr = table._tbl.tblPr
        for attr in ("bandRow", "firstRow"):
            tbl_pr.set(attr, "0")
        style_id = tbl_pr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}tableStyleId")
        if style_id is not None:
            style_id.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"  # "No Style, No Grid": the template colours
        for c, width in enumerate(widths):
            table.columns[c].width = Emu(int(width))
        for r, height in enumerate(heights):
            table.rows[r].height = Emu(int(height))
        fg = self._fg(style)
        color = RGBColor(*[round(v * 255) for v in fg])
        for r, row in enumerate(grid):
            for c, text in enumerate(row):
                cell = table.cell(r, c)
                cell.margin_left = cell.margin_right = Emu(CELL_MARGIN[0])
                cell.margin_top = cell.margin_bottom = Emu(CELL_MARGIN[1])
                frame = cell.text_frame
                frame.word_wrap = True
                paragraph = frame.paragraphs[0]
                run = paragraph.add_run()
                run.text = text
                run.font.size = Pt(style.size_pt)
                run.font.bold = r == 0
                run.font.color.rgb = color
        cnv = shape._element.nvGraphicFramePr.cNvPr
        cnv.set("descr", LABELS["key_numbers"] + ": " + "; ".join(row[0] for row in rows))
        return grid

    # ---- figures -----------------------------------------------------------------------------------------------

    def _place_figure(self, slide: Any, plan: _Plan, spec: SlideSpec) -> str:
        figure = next(f for f in self.catalog.figures if f.id == spec.figure)
        if self.assets is None:
            raise DeckBuildError("FIGURE_NEEDS_ASSET_FOLDER")
        path = crop_figure(figure, self.assets)
        body = next(s for s in slide.placeholders if s.name == "body")
        layout_ph = self._layout_ph(plan.layout, "body")
        style = self._style(plan.layout, layout_ph)
        size = plan.sizes.get("body") or style.size_pt
        style = replace(style, size_pt=size)
        text = plan.fills["body"][0]
        caption_h = self._extent([text], style, self.area.w)[0]
        body.left, body.width = int(self.area.x), int(self.area.w)
        body.top, body.height = int(self.area.bottom - caption_h), int(caption_h)
        room = Rect(self.area.x, self.area.y, self.area.w, self.area.h - caption_h - GAP_PT * EMU_PER_PT)
        from PIL import Image
        with Image.open(path) as image:
            ratio = image.width / image.height
        w = min(room.w, room.h * ratio)
        h = w / ratio
        left = room.x + (room.w - w) / 2
        picture = slide.shapes.add_picture(str(path), Emu(int(left)), Emu(int(room.y)), Emu(int(w)), Emu(int(h)))
        picture.name = f"figure {figure.id}"
        picture._element.nvPicPr.cNvPr.set("descr", figure.caption)
        return str(path)

    # ---- deck --------------------------------------------------------------------------------------------------

    def build_storyboard(self, storyboard: Storyboard) -> Any:
        self.storyboard = storyboard
        self.specs = storyboard.slides
        from .edits import layout_overrides
        if "matn:finding:two-col" in layout_overrides(storyboard).values():
            # The v1 lead rule splits "label: claim". The v2 filler always
            # writes the complete verified statement and a separate fixed/source
            # label; an explicit two-column edit needs geometry only.
            self.variants = deepcopy(self.variants)
            self.variants["matn:finding:two-col"]["valid"].pop("requires", None)
        self.prs.core_properties.title = storyboard.slides[0].title.text
        self.sections = 0
        contents = [c for i, spec in enumerate(self.specs) for c in self._contents(i, spec)]
        titles = [c.title for c in contents if c.slide_type in CONTENT_TYPES]
        layout = self.layouts["matn:limitations:default"]
        ph = self._layout_ph(layout, "title")
        self.title_pt = float(self.cfg["title_sizes"][-1])
        for size in self.cfg["title_sizes"]:
            if all(self._extent([t], self._title_style(layout, ph, size, t), ph.width)[0] <= ph.height
                   for t in titles):
                self.title_pt = float(size)
                break
        previous: str | None = None
        for content in contents:
            parts = self._plan(content, previous)
            previous = parts[-1].layout.name if content.slide_type in CONTENT_TYPES else None
            for part in parts:
                self._emit(part)
                self._record(part)
        return self.prs

    def _record(self, plan: _Plan) -> None:
        spec = self._spec(plan.content)
        slide = self.prs.slides[len(self.prs.slides) - 1]
        record = SlideRecord(slide=len(self.prs.slides), spec=plan.content.plan_index, kind=spec.kind,
                             part=plan.content.part, layout=plan.layout.name, title=plan.fills["title"][0])
        record.contrast = [{"name": e.name, "kind": e.kind, "ratio": round(e.contrast, 3), "size_pt": e.size_pt,
                            "bold": e.bold} for e in plan.elements if e.contrast is not None]
        record.exclude = sorted(self.exclude.get(plan.content.plan_index, ()))
        texts = [spec.title, *spec.lines, *spec.item_titles]
        texts += [t for b in spec.bullets for t in (b.text, *b.context)]
        record.allowed = [asdict(t) for t in texts]
        if spec.kind == "figure":
            record.figure = spec.figure
            record.picture = self._place_figure(slide, plan, spec)
        if spec.kind == "key_numbers":
            record.table = self._place_table(slide, self.table_rows[(plan.content.plan_index, plan.content.part)])
            layout = self.layouts["matn:limitations:default"]
            ratio = self._contrast(self._table_style(), layout, None)
            record.contrast.append({"name": "key_numbers_table", "kind": "text", "ratio": round(ratio, 3),
                                    "size_pt": self._table_style().size_pt, "bold": False})
        if spec.kind == "chart":
            frame = next((s for s in slide.shapes if s.has_chart), None)
            if frame is not None:
                values = [(c.text, self._number(f).value_as_written) for c, f in zip(spec.item_titles, spec.facts)]
                frame._element.nvGraphicFramePr.cNvPr.set(
                    "descr", f"{spec.title.text}: " + "; ".join(f"{a} {b}" for a, b in values))
                record.chart = [{"fact": f, "category": c.text, "value_as_written": self._number(f).value_as_written}
                                for c, f in zip(spec.item_titles, spec.facts)]
        self.records.append(record)


@dataclass
class DeckBuild:
    folder: Path
    pptx: Path
    storyboard: Storyboard
    report: RenderReport
    records: list[SlideRecord]
    fonts: dict


def prepare_template(template: Path, fonts: str) -> tuple[Any, dict]:
    report = validate_template(template)
    if not report.ok:
        raise TemplateInvalidError(f"TEMPLATE_INVALID:{Path(template).name}: " + "; ".join(report.errors))
    if fonts not in FONT_PROFILES:
        raise ValueError(f"FONT_PROFILE_UNKNOWN:{fonts}")
    prs = Presentation(str(template))
    record = {"profile": "template"}
    if fonts == "office":
        from .font_profile import apply_office_profile  # ADR-0020
        record = apply_office_profile(prs)
    return prs, record


def build_deck(catalog: EvidenceCatalog, template: Path, out_dir: Path, *, controls: Controls = Controls(),
               fonts: str = "office", safety: float = DECK_SAFETY,
               exclude: dict[int, set[str]] | None = None, storyboard: Storyboard | None = None) -> DeckBuild:
    """catalog -> storyboard -> deck.pptx, plus storyboard.json, catalog.json and deck-manifest.json."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prs, font_record = prepare_template(Path(template), fonts)
    from .product_templates import is_product_template
    if is_product_template(Path(template)):
        from .product_renderer import ProductBuilder
        builder_class=ProductBuilder
    else:builder_class=V2Builder
    builder = builder_class(prs, catalog, Path(template), safety=safety, assets=out_dir / "assets", exclude=exclude)
    template_id = f"{Path(template).parent.name}|fonts={fonts}|safety={safety}"
    if storyboard is None:
        storyboard = build_storyboard(catalog, builder.headline_fits(), controls, template=template_id)
    else:
        from .edits import validate_storyboard
        validate_storyboard(storyboard, catalog)
        storyboard = replace(storyboard, template=template_id)
    builder.build_storyboard(storyboard)
    pptx = out_dir / "deck.pptx"
    if fonts == "template":
        from .product_templates import finalize_product_fonts
        finalize_product_fonts(prs, Path(template))
    prs.save(str(pptx))
    report = RenderReport(tuple(builder.layouts_used), tuple(builder.overflows), tuple(builder.warnings),
                          tuple(builder.scores))
    (out_dir / "catalog.json").write_text(catalog.to_json(), encoding="utf-8")
    (out_dir / "storyboard.json").write_text(storyboard.to_json(), encoding="utf-8")
    manifest = {"template": str(template), "fonts": font_record, "safety": safety,
                "product_evidence_design":"PRODUCT_EVIDENCE_DESIGN:v1" in storyboard.decisions,
                "storyboard_sha256": storyboard.sha256(), "catalog_sha256": catalog.sha256(),
                "slides": [asdict(r) for r in builder.records],
                "render": {"layouts": list(report.layouts), "warnings": list(report.warnings),
                           "overflows": [asdict(o) for o in report.overflows]}}
    (out_dir / "deck-manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False, sort_keys=True),
                                                encoding="utf-8")
    return DeckBuild(out_dir, pptx, storyboard, report, builder.records, font_record)
