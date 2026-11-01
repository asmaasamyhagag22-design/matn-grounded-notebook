"""Storyboard v2 (ADR-0022): a pure function from an Evidence Catalog, a template's measured title fit and the user
controls to a JSON storyboard. Same inputs, byte-identical JSON. No model, no new prose.

Every on-slide string has a category that the QA gate checks against the catalog: `unit` (a verified unit,
exactly), `synthesis` (a shown synthesis sentence), `axis` (a plan axis title), `requirement` (a requirement
description), `caption` (a reader caption, exact), `source_meta` (title, publisher, URL, file, type, date),
`plan` (topic, audience) or `label` (a fixed UI label from labels_v2). Citation markers `[n]` resolve to the
Sources slide.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Callable

from .catalog import EvidenceCatalog, NumericFact, Unit
from .numeric import conflicts, decide_visual

DETAILS = ("summary", "standard", "detailed")
MAX_BULLETS = 4  # the template's largest item variant (finding:grid-2x2)
SUMMARY_BULLETS = 2
HEADLINE_MAX_CHARS = 140
FIGURES_PER_AXIS = {"summary": 0, "standard": 1, "detailed": 3}

LABELS = {
    "draft": "AI-assisted draft — every statement is source-linked",
    "agenda": "Agenda",
    "section": "Source-linked evidence",
    "closing": "Evidence to take forward",
    "source_balance": "Source balance",
    "commercial_warning": "Sources are mostly commercial; independent coverage is limited.",
    "no_query": "No search phrase was recorded.",
    "gaps": "What we could not establish",
    "gap_axis": "No verified evidence was displayed for this axis",
    "no_gaps": "No open gaps were recorded for this result.",
    "sources": "Sources",
    "methods": "How this deck was made",
    "key_numbers": "Key numbers",
    "disagree": "Sources disagree",
    "states": "states",
    "further": "Further evidence",
    "context": "Context",
    "untitled": "(untitled)",
    "accessed": "accessed",
    "pages": "pp.",
    "page": "p.",
    "not_stated": "not stated",
    "figure_source": "Source figure",
    "col_numbers": "Numbers as written",
    "col_period": "Period",
    "col_scope": "Scope",
    "col_statement": "Statement",
    "methods_lines": (
        "Every statement on the content slides is a verified source sentence, copied exactly; no slide text was "
        "written for this deck.",
        "Numbers are copied by code from verified statements; nothing is computed, summed or averaged.",
        "Where sources give different values for the same measure, both are shown side by side.",
        "Speaker notes give the exact quote, context, source, page or URL and access date for every statement.",
        "Layout was chosen by code; no model wrote layout or slide text.",
    ),
    "methods_synthesis": "Headlines marked synthesis were written by the local model from the cited statements only "
                         "and checked against them before display.",
    "methods_uncited": "Further sources were read but are not cited on any slide.",
}


@dataclass(frozen=True)
class Text:
    text: str
    kind: str  # unit | synthesis | axis | requirement | caption | source_meta | plan | label | date
    ref: str = ""  # unit id, axis id, source id, figure id ...
    marker: str = ""  # "[n]" appended on the slide


@dataclass(frozen=True)
class Bullet:
    unit_id: str
    text: Text
    context: tuple[Text, ...] = ()


@dataclass(frozen=True)
class SlideSpec:
    kind: str  # title | agenda | assertion | figure | chart | key_numbers | disagree | gaps | sources | methods
    title: Text
    axis: str | None = None
    bullets: tuple[Bullet, ...] = ()
    lines: tuple[Text, ...] = ()
    figure: str | None = None
    facts: tuple[str, ...] = ()  # numeric fact ids (chart, key numbers, disagreement)
    item_titles: tuple[Text, ...] = ()  # disagreement: "<publisher> states"
    notes: tuple[str, ...] = ()
    part: tuple[int, int] | None = None
    appendix: bool = False
    composition: str = ""


@dataclass(frozen=True)
class Controls:
    detail: str = "standard"
    target_slides: int | None = None
    audience: str | None = None
    date: str = ""  # ISO date shown on the title slide; passed in so the storyboard stays a pure function


@dataclass(frozen=True)
class Storyboard:
    slides: tuple[SlideSpec, ...]
    citations: tuple[str, ...]  # source ids in [n] order
    decisions: tuple[str, ...]  # one line per decision (headline choice, chart refusal, detail reduction ...)
    controls: Controls
    catalog_sha256: str
    template: str
    version: int = 1

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"

    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()

    def marker(self, source_id: str) -> str:
        return f"[{self.citations.index(source_id) + 1}]"


def axis_title(label: str) -> str:
    """Display form of a plan label: snake_case words get spaces and a capital first letter; nothing is added."""
    if "_" in label or label == label.lower():
        words = " ".join(label.replace("_", " ").split())
        return words[:1].upper() + words[1:]
    return label


class _Citations:
    def __init__(self) -> None:
        self.order: list[str] = []

    def __call__(self, source_id: str) -> str:
        if source_id not in self.order:
            self.order.append(source_id)
        return f"[{self.order.index(source_id) + 1}]"


def _unit_notes(catalog: EvidenceCatalog, unit: Unit, marker: str) -> list[str]:
    source = catalog.source(unit.source)
    where = source.url or source.file or "no URL or file recorded"
    if unit.span.page_index is not None and (source.file or source.pages):
        where += f", {LABELS['page']} {unit.span.page_index + 1}"
    lines = [f"{unit.id} {marker} · {source.title or LABELS['untitled']} · {source.publisher} · {source.type} · "
             f"{where} · {LABELS['accessed']} {source.accessed or LABELS['not_stated']}",
             f"  Quote: “{unit.span.quote.strip()}”"]
    for ctx in unit.context:
        lines.append(f"  {ctx.kind} context (display only, not a verified claim): “{ctx.quote.strip()}”")
    lines.append(f"  Receipt binding: {unit.binding}; block {unit.span.block_id} [{unit.span.start}:{unit.span.end}]")
    return lines


def _bullet(catalog: EvidenceCatalog, unit: Unit, cite: _Citations) -> Bullet:
    marker = cite(unit.source)
    context = tuple(Text(c.quote.strip(), "context", unit.id, marker) for c in unit.context if c.kind == "required")
    return Bullet(unit.id, Text(unit.text.strip(), "unit", unit.id, marker), context)


def _headline(catalog: EvidenceCatalog, axis_id: str, units: list[Unit], fits: Callable[[str], bool],
              decisions: list[str]) -> tuple[Text, Unit | None]:
    """Synthesis sentence for the axis whose cited units are all on it and that fits; else the shortest verified
    unit that fits (only when another unit remains as evidence); else the axis title."""
    ids = {u.id for u in units}
    title = axis_title(next(a.title for a in catalog.plan.axes if a.id == axis_id))
    for sentence in catalog.synthesis:
        if sentence.axis == axis_id and set(sentence.unit_ids) <= ids and len(sentence.text) <= HEADLINE_MAX_CHARS \
                and fits(sentence.text):
            decisions.append(f"HEADLINE:{axis_id}:synthesis")
            return Text(sentence.text.strip(), "synthesis", axis_id), None
    if len(units) >= 2:
        for unit in sorted(units, key=lambda u: (len(u.text.strip()), units.index(u))):
            if len(unit.text.strip()) <= HEADLINE_MAX_CHARS and fits(unit.text.strip()):
                decisions.append(f"HEADLINE:{axis_id}:unit:{unit.id}")
                return Text(unit.text.strip(), "unit", unit.id), unit
    decisions.append(f"HEADLINE:{axis_id}:axis_title")
    return Text(title, "axis", axis_id), None


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)] or [[]]


def _plan_slides(catalog: EvidenceCatalog, fits: Callable[[str], bool], controls: Controls, detail: str,
                 decisions: list[str]) -> tuple[list[SlideSpec], list[str]]:
    cite = _Citations()
    plan = catalog.plan
    slides: list[SlideSpec] = []
    appendix: list[SlideSpec] = []
    audience = controls.audience or plan.audience
    draft = f"{controls.date} · {LABELS['draft']}" if controls.date else LABELS["draft"]
    slides.append(SlideSpec("title", Text(plan.topic, "plan", "topic"), lines=tuple(
        t for t in (Text(audience, "plan", "audience") if audience else None, Text(draft, "label", "draft"))
        if t is not None)))
    slides.append(SlideSpec("agenda", Text(LABELS["agenda"], "label"),
                            lines=tuple(Text(axis_title(a.title), "axis", a.id) for a in plan.axes)))
    source_of = {u.id: u.source for u in catalog.units}
    texts = {u.id: u.text for u in catalog.units}
    clashes = conflicts(tuple(n for n in catalog.numbers if n.origin == "unit"), source_of, texts)
    for axis in plan.axes:
        units = [u for u in catalog.units if u.axis == axis.id]
        if not units:
            decisions.append(f"AXIS_EMPTY:{axis.id}")
            continue
        headline, used = _headline(catalog, axis.id, units, fits, decisions)
        body = [u for u in units if u is not used]
        shown = body if detail != "summary" else body[:SUMMARY_BULLETS]
        rest = [] if detail != "summary" else body[SUMMARY_BULLETS:]
        parts = _chunks(shown, MAX_BULLETS)
        for k, chunk in enumerate(parts, start=1):
            bullets = tuple(_bullet(catalog, u, cite) for u in chunk)
            notes = []
            if used is not None:
                notes += ["Headline:"] + _unit_notes(catalog, used, cite(used.source))
            elif headline.kind == "synthesis":
                sentence = next(s for s in catalog.synthesis if s.text.strip() == headline.text)
                notes.append("Headline (synthesis, written by the local model from " + ", ".join(sentence.unit_ids)
                             + " and checked against them)")
            for b in bullets:
                notes += _unit_notes(catalog, catalog.unit(b.unit_id), b.text.marker)
            title = headline if used is None else Text(headline.text, "unit", used.id, cite(used.source))
            slides.append(SlideSpec("assertion", title, axis.id, bullets, notes=tuple(notes),
                                    part=(k, len(parts)) if len(parts) > 1 else None))
        if rest:
            for k, chunk in enumerate(_chunks(rest, MAX_BULLETS), start=1):
                bullets = tuple(_bullet(catalog, u, cite) for u in chunk)
                notes = [line for b in bullets for line in _unit_notes(catalog, catalog.unit(b.unit_id), b.text.marker)]
                appendix.append(SlideSpec("assertion", Text(f"{LABELS['further']}: {axis_title(axis.title)}", "label",
                                                            axis.id), axis.id, bullets, notes=tuple(notes),
                                          appendix=True))
        figures = [f for f in catalog.figures if f.axis == axis.id]
        figures.sort(key=lambda f: (min(abs(f.page_index - catalog.unit(u).span.page_index) for u in f.unit_ids),
                                    f.page_index, f.id))
        for figure in figures[:FIGURES_PER_AXIS[detail]]:
            marker = cite(figure.source)
            source = catalog.source(figure.source)
            title = Text(figure.caption, "caption", figure.id, marker)
            if not fits(figure.caption):
                title = Text(f"{LABELS['figure_source']}: {axis_title(axis.title)}", "label", axis.id)
            slides.append(SlideSpec("figure", title, axis.id, figure=figure.id,
                                    lines=(Text(figure.caption, "caption", figure.id, marker),),
                                    notes=(f"{figure.id}: {source.title or LABELS['untitled']} · {source.file} · "
                                           f"{LABELS['page']} {figure.page_index + 1} · bbox {list(figure.bbox)} · "
                                           f"caption block {figure.caption_block_id}; cropped from the original PDF, "
                                           f"unaltered; numbers are never read off the image.",)))
        decisions += [f"FIGURES:{axis.id}:{len(figures)} linked, {min(len(figures), FIGURES_PER_AXIS[detail])} shown"]
        facts = tuple(n for n in catalog.numbers if n.origin == "unit" and source_of.get(n.unit_id) and
                      catalog.unit(n.unit_id).axis == axis.id)
        visual = decide_visual(facts, source_of, texts)
        shown_as = {"chart": "chart" if detail != "summary" else "not shown (summary)",
                    "table": "key-numbers table", "none": "no visual"}[visual.kind]
        decisions.append(f"VISUAL:{axis.id}:{visual.kind}:{visual.reason} -> {shown_as}")
        if visual.kind == "chart" and detail != "summary":
            chart_units = list(dict.fromkeys(f.unit_id for f in visual.facts))
            bullets = tuple(_bullet(catalog, catalog.unit(uid), cite) for uid in chart_units)
            notes = [f"{category}: {f.id} = {f.value_as_written} from {f.unit_id}: “{f.span.quote.strip()}”"
                     for category, f in zip(visual.categories, visual.facts)]
            slides.append(SlideSpec("chart", Text(axis_title(axis.title), "axis", axis.id), axis.id, bullets,
                                    facts=tuple(f.id for f in visual.facts),
                                    item_titles=tuple(Text(c, "category", visual.dimension) for c in visual.categories),
                                    notes=tuple(notes)))
        for clash in clashes:
            first = catalog.unit(clash.facts[0].unit_id)
            if first.axis != axis.id:
                continue
            a, b = (catalog.unit(f.unit_id) for f in clash.facts)
            bullets = (_bullet(catalog, a, cite), _bullet(catalog, b, cite))
            titles = tuple(Text(f"{catalog.source(u.source).publisher} {LABELS['states']}", "source_meta", u.source)
                           for u in (a, b))
            notes = ["Values are shown as each source states them; they are never averaged or reconciled."]
            notes += [line for u in (a, b) for line in _unit_notes(catalog, u, cite(u.source))]
            slides.append(SlideSpec("disagree", Text(f"{LABELS['disagree']}: {axis_title(axis.title)}", "label",
                                                     axis.id), axis.id, bullets, item_titles=titles,
                                    facts=tuple(f.id for f in clash.facts), notes=tuple(notes)))
            decisions.append(f"DISAGREE:{clash.facts[0].id}:{clash.facts[1].id}")
    numeric_units = list(dict.fromkeys(n.unit_id for n in catalog.numbers if n.origin == "unit"))
    json_facts = [n for n in catalog.numbers if n.origin == "json"]
    if detail != "summary" and (len(numeric_units) >= 2 or json_facts):
        rows = [n.id for n in catalog.numbers]
        for uid in numeric_units:
            cite(catalog.unit(uid).source)
        for n in json_facts:
            cite(n.source)
        notes = [f"{n.id} = {n.value_as_written} ({n.origin}: {n.unit_id or n.span.block_id}): “{n.span.quote.strip()}”"
                 for n in catalog.numbers]
        slides.append(SlideSpec("key_numbers", Text(LABELS["key_numbers"], "label"), facts=tuple(rows),
                                notes=tuple(notes)))
        decisions.append(f"KEY_NUMBERS:{len(numeric_units)} statements, {len(json_facts)} JSON values")
    else:
        decisions.append(f"KEY_NUMBERS:skipped ({len(numeric_units)} numeric statements, detail {detail})")
    slides += appendix
    gap_lines = []
    for gap in catalog.gaps:
        gap_lines += [Text(m, "requirement", gap.requirement) for m in gap.missing]
    for axis in plan.axes:
        if not any(u.axis == axis.id for u in catalog.units):
            gap_lines.append(Text(f"{LABELS['gap_axis']}: {axis_title(axis.title)}", "label", axis.id))
    slides.append(SlideSpec("gaps", Text(LABELS["gaps"], "label"),
                            lines=tuple(gap_lines) or (Text(LABELS["no_gaps"], "label"),)))
    source_lines = []
    for n, source_id in enumerate(cite.order, start=1):
        s = catalog.source(source_id)
        parts = [s.title or LABELS["untitled"], s.publisher, s.type, s.url or s.file or ""]
        if s.pages:
            parts.append(f"{LABELS['pages']} {', '.join(map(str, s.pages))}")
        if s.accessed:
            parts.append(f"{LABELS['accessed']} {s.accessed}")
        source_lines.append(Text(" · ".join(p for p in parts if p), "source_meta", source_id, f"[{n}]"))
    slides.append(SlideSpec("sources", Text(LABELS["sources"], "label"), lines=tuple(source_lines)))
    methods = [Text(line, "label") for line in LABELS["methods_lines"]]
    if any(s.title.kind == "synthesis" for s in slides):
        methods.append(Text(LABELS["methods_synthesis"], "label"))
    if len(catalog.sources) > len(cite.order):
        methods.append(Text(LABELS["methods_uncited"], "label"))
    slides.append(SlideSpec("methods", Text(LABELS["methods"], "label"), lines=tuple(methods)))
    return slides, cite.order


def build_storyboard(catalog: EvidenceCatalog, fits: Callable[[str], bool], controls: Controls = Controls(), *,
                     template: str = "") -> Storyboard:
    """The deck's storyboard. `fits(text)` says whether a headline fits the template's title box at the minimum
    title size (measured with the deck's fonts); it must be deterministic for a template."""
    catalog.validate()
    if controls.detail not in DETAILS:
        raise ValueError(f"DETAIL_UNKNOWN:{controls.detail}")
    decisions: list[str] = []
    detail = controls.detail
    while True:
        attempt: list[str] = []
        slides, order = _plan_slides(catalog, fits, controls, detail, attempt)
        if template.split('|')[0] in ('ministry_light','midnight','editorial'):
            from .product_storyboard import refine
            from .edits import recite
            slides=refine(catalog,slides,controls,detail,attempt)
            renewed=recite(Storyboard(tuple(slides),tuple(order),tuple(attempt),controls,catalog.sha256(),template),catalog)
            slides=list(renewed.slides);order=list(renewed.citations)
        main = [s for s in slides if not s.appendix]
        if controls.target_slides is None or len(main) <= controls.target_slides or detail == "summary":
            decisions += attempt
            break
        decisions.append(f"TARGET:{len(main)} slides at detail {detail} > target {controls.target_slides}; "
                         f"detail lowered")
        detail = DETAILS[DETAILS.index(detail) - 1]
    main = [s for s in slides if not s.appendix]
    if controls.target_slides is not None and len(main) > controls.target_slides:
        decisions.append(f"TARGET_EXCEEDED:{len(main)} main slides at detail summary; nothing is dropped")
    decisions.append(f"DETAIL:{detail}")
    return Storyboard(tuple(slides), tuple(order), tuple(decisions), controls, catalog.sha256(), template)


MARKER = re.compile(r" \[\d+\]$")
