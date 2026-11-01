"""Numeric facts from verified units, and the comparability rules for charts, tables and disagreement (ADR-0023).

Numbers come only from `matn_verification.quantity_units.quantities` over a verified unit's display text, so each
fact's `value_as_written` is an exact substring of the unit. A unit whose parse reports any problem contributes no
facts. Years are periods, not facts. Nothing here computes a derived number (no sums, differences, growth or
shares).

What a number measures is the statement's content words once the number, the years and the place are removed
("30% of firms will train staff in Egypt by 2030" -> {firms, train, staff}). Facts compare only when unit,
population, measure and denominator are explicit and equal:
- a disagreement: also the same period and place, from different sources, with different values;
- a chart: the same measure across exactly one explicit dimension (years, or places), one fact per category; the
  categories are those explicit years or places, never invented labels.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from matn_verification.quantity_units import quantities

from .catalog import NumericFact, Unit

YEAR = re.compile(r"(?:19|20)\d{2}")
# Explicit place words only; anything else leaves geography unknown (None), and unknown never matches.
GEOGRAPHY = (
    ("world", r"\b(?:world(?:'s|’s)?|worldwide|global(?:ly)?)\b"),
    ("Egypt", r"\bEgypt(?:ian)?\b"),
    ("Morocco", r"\bMorocc(?:o|an)\b"),
    ("Jordan", r"\bJordan(?:ian)?\b"),
    ("Africa", r"\bAfrica(?:n)?\b"),
    ("Europe", r"\b(?:Europe(?:an)?|EU)\b"),
    ("United States", r"\b(?:United States|U\.S\.|US|America(?:n)?)\b"),
    ("United Kingdom", r"\b(?:United Kingdom|UK|U\.K\.|Britain|British)\b"),
    ("OECD", r"\bOECD\b"),
    ("MENA", r"\b(?:MENA|Middle East)\b"),
    ("Arab region", r"\bArab\b"),
    ("Canada", r"\bCanad(?:a|ian)\b"),
    ("Australia", r"\bAustralia(?:n)?\b"),
    ("India", r"\bIndia(?:n)?\b"),
    ("China", r"\bChin(?:a|ese)\b"),
)
STOPWORDS = frozenset("""a an the of in on at by to for from with and or as is are was were be been being will would
can could may might must shall should than that this these those its their his her our your it they them there
about around approximately nearly almost over under more less per cent percent some each every all""".split())


def geography(text: str) -> str | None:
    """The single explicit place named in `text`; None when none or more than one is named."""
    found = {name for name, pattern in GEOGRAPHY if re.search(pattern, text)}
    return found.pop() if len(found) == 1 else None


def measure(text: str, start: int, end: int) -> tuple[str, ...]:
    """Content words of a statement without the number itself, years and place names."""
    rest = text[:start] + " " + text[end:]
    rest = YEAR.sub(" ", rest)
    for _, pattern in GEOGRAPHY:
        rest = re.sub(pattern, " ", rest)
    rest = re.sub(r"\d+(?:[.,]\d+)*%?", " ", rest)
    return tuple(sorted({w for w in re.findall(r"[a-z]+", rest.lower()) if w not in STOPWORDS and len(w) > 1}))


def _is_year(q) -> bool:
    return q.unit == "" and q.denominator is None and YEAR.fullmatch(q.raw.strip()) is not None


def facts_for_unit(unit: Unit) -> tuple[NumericFact, ...]:
    """Numeric facts copied from one verified unit; () when its quantity parse reports a problem."""
    found, problems = quantities(unit.text)
    if problems:
        return ()
    periods = tuple(dict.fromkeys(q.raw.strip() for q in found if _is_year(q)))
    place = geography(unit.text)
    facts = []
    for q in found:
        if _is_year(q) or q.unit.startswith("period:"):
            continue
        written = unit.text[q.start:q.end]
        if written != q.raw:
            continue  # the ledger's raw text must be the unit's own characters
        facts.append(NumericFact(
            id=f"{unit.id}.N{len(facts) + 1}", unit_id=unit.id, value_as_written=written, start=q.start, end=q.end,
            value=str(q.value), unit=q.unit, span=unit.span, denominator=q.denominator,
            approximation=q.approximation, period=periods, population=q.population, geography=place))
    return tuple(facts)


@dataclass(frozen=True)
class Key:
    """What a number is about. Every part is explicit; unknown never matches anything."""
    unit: str
    population: str
    measure: tuple[str, ...]
    denominator: int | None


def key(fact: NumericFact, text: str) -> Key | None:
    if not fact.population or fact.approximation or fact.origin != "unit":
        return None
    words = measure(text, fact.start, fact.end)
    return Key(fact.unit, fact.population, words, fact.denominator) if words else None


def _groups(facts: tuple[NumericFact, ...], texts: dict[str, str]) -> list[tuple[Key, list[NumericFact]]]:
    grouped: dict[Key, list[NumericFact]] = {}
    for fact in facts:
        k = key(fact, texts.get(fact.unit_id, ""))
        if k is not None:
            grouped.setdefault(k, []).append(fact)
    return list(grouped.items())


@dataclass(frozen=True)
class Conflict:
    key: Key
    facts: tuple[NumericFact, NumericFact]  # different sources, same measure, period and place, different values


def conflicts(facts: tuple[NumericFact, ...], source_of: dict[str, str], texts: dict[str, str]) -> list[Conflict]:
    """Pairs of facts from different sources that state different values for the same measure, period and place.
    Never averaged or reconciled."""
    found = []
    for k, members in _groups(facts, texts):
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                same_scope = a.period and a.period == b.period and a.geography and a.geography == b.geography
                if same_scope and source_of[a.unit_id] != source_of[b.unit_id] and a.value != b.value:
                    found.append(Conflict(k, (a, b)))
    return found


@dataclass(frozen=True)
class ChartDecision:
    kind: str  # chart | table | none
    reason: str
    facts: tuple[NumericFact, ...] = ()
    categories: tuple[str, ...] = ()  # explicit years or places, one per fact
    dimension: str = ""  # period | geography


def decide_visual(facts: tuple[NumericFact, ...], source_of: dict[str, str], texts: dict[str, str]) -> ChartDecision:
    """A chart only for one measure across one explicit dimension with one fact per category and no conflict;
    otherwise the facts go to the key-numbers table (explicit unit, period and scope columns); otherwise nothing."""
    if not facts:
        return ChartDecision("none", "NO_NUMERIC_FACTS")
    clashing = {f.id for c in conflicts(facts, source_of, texts) for f in c.facts}
    reasons = set()
    for k, members in _groups(facts, texts):
        members = [f for f in members if f.id not in clashing]
        if len(members) < 2:
            reasons.add("FEWER_THAN_TWO_COMPARABLE")
            continue
        places = {f.geography for f in members}
        years = [f.period for f in members]
        if len(places) == 1 and None not in places and all(len(p) == 1 for p in years) and \
                len({p[0] for p in years}) == len(members):
            ordered = sorted(members, key=lambda f: f.period[0])
            return ChartDecision("chart", "SAME_MEASURE_ACROSS_YEARS", tuple(ordered),
                                 tuple(f.period[0] for f in ordered), "period")
        if len({p for p in years}) == 1 and years[0] and None not in places and len(places) == len(members):
            return ChartDecision("chart", "SAME_MEASURE_ACROSS_PLACES", tuple(members),
                                 tuple(f.geography for f in members), "geography")
        reasons.add("NO_SINGLE_EXPLICIT_DIMENSION")
    if not _groups(facts, texts):
        reasons.add("SCOPE_OR_MEASURE_NOT_EXPLICIT")
    if clashing:
        reasons.add("SOURCES_DISAGREE")
    return ChartDecision("table", "TABLE:" + ",".join(sorted(reasons)), facts)
