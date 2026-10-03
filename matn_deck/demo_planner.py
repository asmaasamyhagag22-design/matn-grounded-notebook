"""Demo deck planner v0 (overnight demo): verified reference facts -> DeckPlan, by fixed deterministic rules.

This is not the Step 9 planner. The facts come from the dev gold through eval/gold_to_facts.py (out/demo/facts/), so
the deck shows real content while the model pipeline (Steps 3-9) is still to be built. The rules:

1. title: the document's registered title; the subtitle cites the purpose fact.
2. executive summary: up to 4 importance-3 points, one per top-level section first, in page order.
3. KPI: 1-4 verified number facts in page order (years are not KPIs).
4. findings: the remaining finding/purpose/definition points, grouped by top-level section_path, 2-4 per slide.
5. implications (recommendations) and limitations (caveats), 2-4 per slide, when the document has them.
6. closing: 3 takeaways (the latest importance-3 findings) plus one decision (a recommendation), when one exists.
7. sources.
A chart is added only from a clean detected table (none of the three dev documents has one today).

Titles: a cached model title (Ollama, see demo_phrasing.py) is used only when it passes `title_problems` now, at plan
time: at most 90 characters and every number in it, digits or spelled out, appears in the facts the slide cites.
KPI slides never take a model title: over several unrelated values the model merged two metrics into one claim
("69.4% accuracy with 19.7 minute training") while every number still passed the check.
Otherwise the title is deterministic: the shortest cited point of at most 90 characters, else the section heading.
Item text over 120 characters (the contract limit) is abridged at a clause boundary and marked with an ellipsis; the
full statement stays in the speaker notes. Only verified facts are ever cited.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from matn_contracts.conversion import numeric_tokens
from matn_contracts.domain import Block, ChartSpec, DeckPlan, Fact, Slide, SlideItem, Table
from matn_contracts.enums import ChartType, FactKind, FactStatus, SlideType

TITLE_MAX = 90
ITEM_MAX = 120
ELLIPSIS = "…"
_ATTRIBUTION = re.compile(
    r"^(?:the report|the authors|gao|the study)\s+(?:finds|says|argues|notes|observes|cautions?|advises)"
    r"(?:\s+that)?\s+", re.I)
_SPELLED = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100, "thousand": 1000, "million": 10**6,
    "billion": 10**9, "trillion": 10**12, "dozen": 12, "half": None, "double": None, "twice": None, "triple": None,
    "tripled": None, "doubled": None, "halved": None, "quadrupled": None,
}
_WORD = re.compile(r"[A-Za-z]+")


@dataclass(frozen=True)
class DemoDoc:
    """One document's demo inputs, as written by eval/gold_to_facts.py."""
    doc_key: str
    doc_id: str
    title: str
    publisher: str
    license: str
    facts: tuple[Fact, ...]
    tables: tuple[Table, ...]
    blocks: tuple[Block, ...]
    receipts: Mapping[str, dict]

    def fact(self, fact_id: str) -> Fact:
        return next(f for f in self.facts if f.fact_id == fact_id)


def load_demo_doc(path: Path) -> DemoDoc:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return DemoDoc(
        doc_key=data["doc_key"], doc_id=data["doc_id"], title=data["title"], publisher=data["publisher"],
        license=data["license"],
        facts=tuple(Fact.model_validate(f) for f in data["facts"]),
        tables=tuple(Table.model_validate(t) for t in data["tables"]),
        blocks=tuple(Block.model_validate(b) for b in data["blocks"]),
        receipts=data["receipts"],
    )


# ---- number check ---------------------------------------------------------------------------------------------------

def _decimal(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", "").lstrip("+"))
    except InvalidOperation:
        return None


def cited_numbers(facts: tuple[Fact, ...]) -> set[Decimal]:
    """Every number the cited facts print: digits in quotes, statements and number values."""
    values: set[Decimal] = set()
    for fact in facts:
        texts = [fact.statement] + [ev.quote for ev in fact.evidence]
        if fact.number_value is not None:
            texts.append(fact.number_value.value_as_written)
        for text in texts:
            values |= {d for m in numeric_tokens(text) if (d := _decimal(m.group().strip())) is not None}
            values |= {Decimal(_SPELLED[w]) for w in _WORD.findall(text.lower())
                       if _SPELLED.get(w) is not None}
    return values


def cited_words(facts: tuple[Fact, ...]) -> set[str]:
    words: set[str] = set()
    for fact in facts:
        for text in [fact.statement] + [ev.quote for ev in fact.evidence]:
            words |= {w.lower() for w in _WORD.findall(text)}
    return words


def title_problems(title: str, facts: tuple[Fact, ...]) -> list[str]:
    """Why a title may not be used (empty = usable): length, and numbers (digits or words) not in the cited facts."""
    problems = []
    if not title.strip():
        problems.append("EMPTY")
    if len(title) > TITLE_MAX:
        problems.append(f"TOO_LONG:{len(title)}")
    allowed = cited_numbers(facts)
    for match in numeric_tokens(title):
        value = _decimal(match.group().strip())
        if value is None or value not in allowed:
            problems.append(f"NUMBER_NOT_CITED:{match.group().strip()}")
    for digit_run in re.findall(r"\d+", title):  # digits glued to letters ("Q1", "FY2021") must be printed too
        if not any(digit_run in ev.quote or digit_run in f.statement for f in facts for ev in f.evidence):
            problems.append(f"DIGITS_NOT_CITED:{digit_run}")
    words = cited_words(facts)
    for word in _WORD.findall(title.lower()):
        if word in _SPELLED and word not in words:
            value = _SPELLED[word]
            if value is None or Decimal(value) not in allowed:
                problems.append(f"SPELLED_NUMBER_NOT_CITED:{word}")
    return list(dict.fromkeys(problems))


# ---- text rules -----------------------------------------------------------------------------------------------------

def strip_attribution(text: str) -> str:
    """"The report finds that X" -> "X" (the deck is about the report, so the lead adds nothing)."""
    stripped = _ATTRIBUTION.sub("", text, count=1)
    return stripped[:1].upper() + stripped[1:] if stripped != text else text


def abridge(text: str, limit: int = ITEM_MAX) -> tuple[str, bool]:
    """Fit `text` in `limit` characters: strip the attribution lead, then cut and mark the cut with an ellipsis.

    The cut is at a late clause boundary when one keeps at least 85% of the room, else at the last word boundary, so
    the main clause is kept. Returns (text, abridged); an abridged text only drops words, never changes them.
    """
    text = strip_attribution(text.strip())
    if len(text) <= limit:
        return text, False
    room = limit - len(ELLIPSIS)
    cuts = [m.start() for m in re.finditer(r"[,;:]\s|\s(?:and|but|while|which|because|so that|including)\s", text)
            if 0.85 * room <= m.start() <= room]
    end = cuts[-1] if cuts else text.rfind(" ", 0, room + 1)
    return text[:end].rstrip(" ,;:") + ELLIPSIS, True


_HEDGES = frozenset({"may", "might", "could", "likely", "unlikely", "not", "no", "only", "without", "cannot",
                     "significantly", "never", "unless", "however", "but", "less", "more", "most", "least",
                     "would", "should", "must", "can", "need", "needs", "started", "control"})
_STOP = frozenset({"the", "a", "an", "of", "to", "in", "and", "or", "for", "on", "by", "with", "as", "at", "its",
                   "it", "is", "are", "be", "that", "this", "their", "from", "than", "into", "over", "has", "have"})


def item_problems(text: str, fact: Fact, limit: int = ITEM_MAX) -> list[str]:
    """Why a model-phrased item may not replace a fact's statement (empty = usable).

    Length; numbers (digits or words) only from the fact; every hedge or negation of the statement kept and none
    added; and no new content word (a word counts as known when its first 5 letters start a word of the statement
    or the quote; one unknown word is tolerated for inflection).
    """
    problems = [p for p in title_problems(text, (fact,)) if not p.startswith("TOO_LONG")]
    if len(text) > limit:
        problems.append(f"TOO_LONG:{len(text)}")
    source_words = {w.lower() for t in [fact.statement] + [e.quote for e in fact.evidence] for w in _WORD.findall(t)}
    words = [w.lower() for w in _WORD.findall(text)]
    for hedge in _HEDGES:
        if hedge in {w.lower() for w in _WORD.findall(fact.statement)} and hedge not in words:
            problems.append(f"HEDGE_DROPPED:{hedge}")
        if hedge in words and hedge not in source_words:
            problems.append(f"HEDGE_ADDED:{hedge}")
    stems = {w[:5] for w in source_words}
    unknown = [w for w in words if w not in _STOP and len(w) > 3 and w[:5] not in stems]
    if len(unknown) > 1:
        problems.append("NEW_WORDS:" + ",".join(unknown))
    return list(dict.fromkeys(problems))


def section_of(doc: DemoDoc, fact: Fact) -> tuple[str, ...]:
    path = doc.receipts[fact.fact_id].get("section_path") or ["Document"]
    return tuple(path)


def page_of(doc: DemoDoc, fact: Fact) -> int:
    return int(doc.receipts[fact.fact_id]["page_index"])


def clean_heading(text: str) -> str:
    """A section heading as a slide title: "Chapter 1 – Recent ..." -> "Recent ...", within 90 characters."""
    text = re.sub(r"^(?:chapter|part|section)\s+\d+\s*[-–—:.�]\s*", "", text.strip(), flags=re.I)
    text = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", text)
    text = re.sub(r"^Framework Principle \d+\.\s*", "", text)
    return text if len(text) <= TITLE_MAX else abridge(text, TITLE_MAX)[0]


# ---- plan -----------------------------------------------------------------------------------------------------------

@dataclass
class SlideMeta:
    slide_type: str
    title: str
    title_source: str  # "model" | "shortest_point" | "section_heading" | "fixed"
    fact_ids: list[str]
    abridged: list[str] = field(default_factory=list)  # fact ids whose item text was abridged (ellipsis)
    model_items: list[str] = field(default_factory=list)  # fact ids whose item text is a checked model phrasing
    rejections: list[str] = field(default_factory=list)  # cached model phrasings refused now, with reasons


def slide_key(slide_type: SlideType, fact_ids: tuple[str, ...]) -> str:
    """Cache key of a slide's model title: its type and the facts it cites."""
    return hashlib.sha256(json.dumps([slide_type.value, list(fact_ids)]).encode()).hexdigest()[:16]


@dataclass
class DemoPlan:
    plan: DeckPlan
    meta: list[SlideMeta]
    requests: dict[str, dict]  # phrase key -> what a model phrasing would be asked for (see demo_phrasing.py)


class _Builder:
    def __init__(self, doc: DemoDoc, phrases: Mapping[str, str] | None) -> None:
        self.doc = doc
        self.phrases = phrases or {}
        self.slides: list[Slide] = []
        self.meta: list[SlideMeta] = []
        self.requests: dict[str, dict] = {}

    def item(self, fact: Fact) -> tuple[SlideItem, str, list[str]]:
        """The item for one fact: its statement when it fits, else a checked model phrasing, else an abridgment."""
        text, abridged = abridge(fact.statement)
        if not abridged:
            return SlideItem(text=text, fact_ids=(fact.fact_id,)), "statement", []
        key = f"item:{fact.fact_id}"
        self.requests[key] = {"kind": "item", "fact_ids": [fact.fact_id], "fallback": text}
        phrased = self.phrases.get(key)
        problems = item_problems(phrased, fact) if phrased else []
        if phrased and not problems:
            return SlideItem(text=phrased, fact_ids=(fact.fact_id,)), "model", []
        return SlideItem(text=text, fact_ids=(fact.fact_id,)), "abridged", [f"{key}:{p}" for p in problems]

    def title_for(self, slide_type: SlideType, facts: list[Fact], heading: str | None) -> tuple[str, str, list[str]]:
        cited = tuple(facts)
        key = "title:" + slide_key(slide_type, tuple(f.fact_id for f in facts))
        candidates = [strip_attribution(f.statement) for f in facts if f.kind is not FactKind.NUMBER]
        short = sorted((c for c in candidates if len(c) <= TITLE_MAX and not title_problems(c, cited)),
                       key=lambda c: (len(c), c))
        if short:
            fallback, source = short[0].rstrip("."), "shortest_point"
        else:
            fallback, source = clean_heading(heading or self.doc.title), "section_heading"
        if slide_type is SlideType.KPI:  # a model title over 4 unrelated values tends to merge them: fixed title
            return fallback, source, []
        self.requests[key] = {"kind": "title", "slide_type": slide_type.value,
                              "fact_ids": [f.fact_id for f in facts], "fallback": fallback}
        model_title = self.phrases.get(key)
        rejections = title_problems(model_title, cited) if model_title else []
        if model_title and not rejections:
            return model_title, "model", []
        return fallback, source, [f"{key}:{p}" for p in rejections]

    def add(self, slide_type: SlideType, facts: list[Fact], *, heading: str | None = None, title: str | None = None,
            items: list[Fact] | None = None, kpis: list[Fact] | None = None, notes_extra: str | None = None,
            chart: ChartSpec | None = None, fixed_items: list[SlideItem] | None = None) -> None:
        rejections: list[str] = []
        if title is None:
            title, source, rejections = self.title_for(slide_type, facts, heading)
        else:
            source = "fixed"
        slide_items, abridged, model_items = [], [], []
        for fact in items or []:
            item, how, problems = self.item(fact)
            slide_items.append(item)
            rejections += problems
            if how == "abridged":
                abridged.append(fact.fact_id)
            elif how == "model":
                model_items.append(fact.fact_id)
        slide_items += fixed_items or []
        notes = [f"{f.statement}" for f in (items or []) if f.fact_id in abridged + model_items]
        if notes_extra:
            notes.insert(0, notes_extra)
        self.slides.append(Slide(slide_type=slide_type, title=title, items=tuple(slide_items),
                                 kpi_fact_ids=tuple(f.fact_id for f in kpis or []), chart=chart,
                                 notes="\n".join(notes) or None))
        self.meta.append(SlideMeta(slide_type.value, title, source, [f.fact_id for f in facts], abridged,
                                   model_items, rejections))


def _diverse(facts: list[Fact], doc: DemoDoc, count: int) -> list[Fact]:
    """Up to `count` facts, one per top-level section first, then the rest; returned in page order."""
    chosen, seen = [], set()
    for fact in facts:
        top = section_of(doc, fact)[0]
        if top not in seen and len(chosen) < count:
            chosen.append(fact)
            seen.add(top)
    for fact in facts:
        if fact not in chosen and len(chosen) < count:
            chosen.append(fact)
    return sorted(chosen, key=lambda f: (page_of(doc, f), facts.index(f)))


def chunk(facts: list[Fact], low: int = 2, high: int = 4) -> list[list[Fact]]:
    """Split into the fewest groups of at most `high`, as even as possible (so no group is below `low` if avoidable)."""
    if not facts:
        return []
    groups = -(-len(facts) // high)
    size, extra = divmod(len(facts), groups)
    out, start = [], 0
    for g in range(groups):
        end = start + size + (1 if g < extra else 0)
        out.append(facts[start:end])
        start = end
    return out


def group_by_section(facts: list[Fact], doc: DemoDoc) -> list[tuple[str, list[Fact]]]:
    """Facts grouped by top-level section (page order), 2-4 per slide; a lone fact joins its neighbour group."""
    groups: list[tuple[str, list[Fact]]] = []
    for fact in facts:
        top = section_of(doc, fact)[0]
        if groups and groups[-1][0] == top:
            groups[-1][1].append(fact)
        else:
            groups.append((top, [fact]))
    merged: list[tuple[str, list[Fact]]] = []
    for heading, members in groups:
        if len(members) == 1 and merged and len(merged[-1][1]) < 4:
            merged[-1][1].append(members[0])
        else:
            merged.append((heading, members))
    if len(merged) > 1 and len(merged[0][1]) == 1:  # a lone first group joins the next one
        heading, members = merged.pop(0)
        merged[0] = (merged[0][0], members + merged[0][1])
    out = []
    for heading, members in merged:
        out += [(heading, part) for part in chunk(members)]
    return out


def plan_deck(doc: DemoDoc, phrases: Mapping[str, str] | None = None) -> DemoPlan:
    """The demo plan. `phrases` holds cached model phrasings ("title:<slide key>", "item:<fact_id>"); each one is
    re-checked here and replaced by the deterministic text when it fails."""
    b = _Builder(doc, phrases)
    verified = sorted((f for f in doc.facts if f.status is FactStatus.VERIFIED), key=lambda f: page_of(doc, f))
    points = [f for f in verified if f.kind is not FactKind.NUMBER]
    numbers = [f for f in verified if f.kind is FactKind.NUMBER]
    S = SlideType

    purpose = next((f for f in points if f.kind is FactKind.PURPOSE), points[0])
    title, _, rest = doc.title.partition(": ") if len(doc.title) > TITLE_MAX else (doc.title, "", "")
    subtitle = [SlideItem(text=abridge(rest or f"{doc.publisher} · demo deck from verified reference facts")[0],
                          fact_ids=(purpose.fact_id,))]
    b.add(S.TITLE, [purpose], title=title, fixed_items=subtitle,
          notes_extra="Demo deck v0: content is the verified reference (dev gold), not model output.")

    headline = [f for f in points if int(f.importance) == 3]
    summary = _diverse(headline, doc, 4)
    b.add(S.EXECUTIVE_SUMMARY, summary, items=summary, heading="Executive summary")

    kpis = [f for f in numbers if (doc.receipts[f.fact_id].get("unit_raw") or "") != "year"
            and f.number_value is not None and not re.fullmatch(r"(19|20)\d{2}", f.number_value.value_as_written)][:4]
    if kpis:
        b.add(S.KPI, kpis, kpis=kpis, heading="The headline numbers, each copied from its page")

    for table in doc.tables[:1]:  # a chart only from a clean detected table that holds a cited value
        cells = {c.text for c in table.cells}
        cited = [f for f in numbers if f.number_value is not None and f.number_value.value_as_written in cells
                 and page_of(doc, f) == table.page_index]
        if cited:
            b.add(S.CHART, cited[:1], items=cited[:1], chart=chart_for(table), heading="Key numbers")

    used = {f.fact_id for f in summary}
    findings = [f for f in points if f.fact_id not in used
                and f.kind in (FactKind.FINDING, FactKind.PURPOSE, FactKind.DEFINITION)]
    for heading, group in group_by_section(findings, doc):
        b.add(S.FINDING, group, items=group, heading=heading)

    recommendations = [f for f in points if f.kind is FactKind.RECOMMENDATION and f.fact_id not in used]
    for group in chunk(recommendations):
        b.add(S.IMPLICATIONS, group, items=group, heading="Recommendations")
    caveats = [f for f in points if f.kind is FactKind.CAVEAT and f.fact_id not in used]
    for group in chunk(caveats):
        b.add(S.LIMITATIONS, group, items=group, heading="Limits and caveats")

    decision = next((f for f in reversed(points) if f.kind is FactKind.RECOMMENDATION and int(f.importance) == 3),
                    next((f for f in reversed(points) if f.kind is FactKind.RECOMMENDATION), None))
    takeaway_pool = [f for f in reversed(headline) if f.kind in (FactKind.FINDING, FactKind.CAVEAT)]
    takeaway_pool += [f for f in reversed(headline) if f not in takeaway_pool and f is not decision]
    takeaways = sorted(takeaway_pool[:3], key=lambda f: page_of(doc, f))
    closing = takeaways + ([decision] if decision is not None else [])
    b.add(S.CLOSING, closing, items=closing, heading="Takeaways")

    source_line = SlideItem(text=abridge(f"Document: {doc.title}", ITEM_MAX)[0], fact_ids=(purpose.fact_id,))
    publisher_line = SlideItem(text=abridge(f"Publisher: {doc.publisher} · License: {doc.license.split(' (')[0]}",
                                            ITEM_MAX)[0], fact_ids=(purpose.fact_id,))
    b.add(S.SOURCES, [purpose], title="Sources and verification: every claim traces to a page",
          fixed_items=[source_line, publisher_line])

    plan = DeckPlan(doc_id=doc.doc_id, slides=tuple(b.slides))
    return DemoPlan(plan=plan, meta=b.meta, requests=b.requests)


def chart_for(table: Table) -> ChartSpec:  # used only when a clean detected table exists
    numeric_cols = sorted({c.col for c in table.cells if c.col > 0})
    return ChartSpec(table_id=table.table_id, x_column=0, y_columns=tuple(numeric_cols[:1]),
                     chart_type=ChartType.COLUMN)
