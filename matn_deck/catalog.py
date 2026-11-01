"""Evidence Catalog (ADR-0021): one contract between every Matn input path and the deck.

A catalog holds only what saved, verified results already contain: the plan, verified units with their exact
source spans and displayed context, shown synthesis sentences, numeric facts copied from verified units, gaps,
sources, and reader-detected figures. Adapters (catalog_adapters.py) build it; nothing here calls a model.
JSON is byte-stable (sorted keys, fixed separators), so the same catalog always serializes to the same bytes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
import hashlib
import json
from typing import Any, get_args, get_origin, get_type_hints

CATALOG_VERSION = 1


@dataclass(frozen=True)
class Axis:
    id: str
    title: str  # the plan's axis label, as saved
    query: str = ""


@dataclass(frozen=True)
class Requirement:
    id: str
    axis: str
    description: str
    critical: bool = False


@dataclass(frozen=True)
class Plan:
    topic: str
    audience: str
    goal: str
    language: str
    axes: tuple[Axis, ...]
    requirements: tuple[Requirement, ...] = ()


@dataclass(frozen=True)
class Span:
    """An exact source span: `quote` is `block text[start:end]` of `block_id`."""
    doc_id: str
    block_id: str
    start: int
    end: int
    quote: str
    page_index: int | None = None
    page_label: str | None = None
    bbox: tuple[float, ...] | None = None


@dataclass(frozen=True)
class Context:
    quote: str
    kind: str  # required (verified display context) | heading | local (display-only reading context)
    origin: str = ""
    span: Span | None = None


@dataclass(frozen=True)
class Unit:
    id: str  # U1, U2, ... in display order
    axis: str
    text: str  # the verified display text, exactly as saved
    span: Span
    source: str  # Source.id
    source_type: str
    status: str
    binding: str  # receipt binding of the saved check
    requirement: str | None = None
    context: tuple[Context, ...] = ()


@dataclass(frozen=True)
class SynthesisSentence:
    axis: str
    text: str
    unit_ids: tuple[str, ...]


@dataclass(frozen=True)
class NumericFact:
    id: str
    unit_id: str  # the verified unit the number is copied from ("" for a structured JSON value)
    value_as_written: str  # == unit.text[start:end]; for JSON, == span.quote (the value at the JSON path)
    start: int
    end: int
    value: str  # exact fraction, e.g. "59" or "3/5"
    unit: str  # quantity_units unit ("" for a bare count, "ratio" for % and fractions)
    span: Span
    denominator: int | None = None
    approximation: str = ""
    period: tuple[str, ...] = ()
    population: str = ""
    geography: str | None = None
    origin: str = "unit"  # unit | json
    source: str = ""  # Source.id for JSON values (units carry their own)


@dataclass(frozen=True)
class Gap:
    requirement: str
    axis: str
    label: str
    missing: tuple[str, ...]  # requirement descriptions not established
    reason: str = ""


@dataclass(frozen=True)
class Source:
    id: str  # S1, S2, ... in order of first citation by a unit, then uncited sources
    doc_id: str
    type: str  # source-type label ("government", "uploaded document", ...)
    publisher: str
    title: str | None = None  # None when the saved source has no title; never invented
    url: str | None = None
    file: str | None = None
    accessed: str | None = None  # ISO date from the saved fetch time; None when absent
    pages: tuple[int, ...] = ()  # 1-based pages cited (PDF sources)


@dataclass(frozen=True)
class Figure:
    id: str
    doc_id: str
    source: str
    page_index: int
    bbox: tuple[float, ...]  # PDF points, top-left origin (reader convention)
    caption: str  # the reader's caption block text, exact
    caption_block_id: str
    axis: str
    unit_ids: tuple[str, ...]  # displayed units that link the figure to the axis
    rights: str = "uploaded-document"
    pdf: str | None = None  # path of the original PDF the figure is cropped from


@dataclass(frozen=True)
class ReaderTable:
    id: str
    doc_id: str
    page_index: int
    bbox: tuple[float, ...]


@dataclass(frozen=True)
class EvidenceCatalog:
    plan: Plan
    units: tuple[Unit, ...]
    sources: tuple[Source, ...]
    synthesis: tuple[SynthesisSentence, ...] = ()
    numbers: tuple[NumericFact, ...] = ()
    gaps: tuple[Gap, ...] = ()
    figures: tuple[Figure, ...] = ()
    tables: tuple[ReaderTable, ...] = ()
    origin: dict[str, Any] = field(default_factory=dict, compare=True)
    version: int = CATALOG_VERSION

    # ---- lookups -------------------------------------------------------------------------------------------------

    def unit(self, unit_id: str) -> Unit:
        return next(u for u in self.units if u.id == unit_id)

    def source(self, source_id: str) -> Source:
        return next(s for s in self.sources if s.id == source_id)

    # ---- validation ----------------------------------------------------------------------------------------------

    def problems(self) -> list[str]:
        """Contract violations; [] for a valid catalog."""
        found: list[str] = []
        for name, items in (("unit", self.units), ("source", self.sources), ("number", self.numbers),
                            ("figure", self.figures), ("axis", self.plan.axes)):
            ids = [item.id for item in items]
            found += [f"DUPLICATE_{name.upper()}_ID:{i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
        axes = {a.id for a in self.plan.axes}
        sources = {s.id for s in self.sources}
        units = {u.id: u for u in self.units}
        for u in self.units:
            if not u.text.strip():
                found.append(f"EMPTY_UNIT:{u.id}")
            if u.status != "verified":
                found.append(f"UNIT_NOT_VERIFIED:{u.id}")
            if u.axis not in axes:
                found.append(f"UNIT_AXIS_UNKNOWN:{u.id}")
            if u.source not in sources:
                found.append(f"UNIT_SOURCE_UNKNOWN:{u.id}")
        for n in self.numbers:
            if n.origin == "json":
                if n.source not in sources or n.span.quote != n.value_as_written:
                    found.append(f"NUMBER_NOT_COPIED:{n.id}")
                continue
            unit = units.get(n.unit_id)
            if unit is None:
                found.append(f"NUMBER_UNIT_UNKNOWN:{n.id}")
            elif unit.text[n.start:n.end] != n.value_as_written:
                found.append(f"NUMBER_NOT_COPIED:{n.id}")
        for s in self.synthesis:
            if s.axis not in axes:
                found.append(f"SYNTHESIS_AXIS_UNKNOWN:{s.text[:30]}")
            for uid in s.unit_ids:
                if uid not in units:
                    found.append(f"SYNTHESIS_UNIT_UNKNOWN:{uid}")
        for f in self.figures:
            if not f.caption.strip():
                found.append(f"FIGURE_NO_CAPTION:{f.id}")
            if f.source not in sources:
                found.append(f"FIGURE_SOURCE_UNKNOWN:{f.id}")
        for g in self.gaps:
            if g.axis not in axes:
                found.append(f"GAP_AXIS_UNKNOWN:{g.requirement}")
        return found

    def validate(self) -> "EvidenceCatalog":
        problems = self.problems()
        if problems:
            raise ValueError("CATALOG_INVALID: " + "; ".join(problems))
        return self

    # ---- JSON ----------------------------------------------------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"

    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_json(cls, text: str | bytes) -> "EvidenceCatalog":
        return _build(cls, json.loads(text))


def _build(kind: Any, value: Any) -> Any:
    """Rebuild nested frozen dataclasses (and tuples) from their asdict() form."""
    if value is None:
        return None
    origin = get_origin(kind)
    if origin is tuple:
        inner = get_args(kind)[0]
        return tuple(_build(inner, v) for v in value)
    if origin is not None and type(None) in get_args(kind):  # X | None
        inner = next(a for a in get_args(kind) if a is not type(None))
        return _build(inner, value)
    if isinstance(kind, type) and hasattr(kind, "__dataclass_fields__"):
        hints = get_type_hints(kind)
        return kind(**{f.name: _build(hints[f.name], value[f.name]) for f in fields(kind) if f.name in value})
    return value
