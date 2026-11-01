"""Small typed boundary for model proposals; source text has no authority."""
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .budgets import STAGES


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Brief(Record):
    topic: str = Field(min_length=3, max_length=240)
    audience: str = Field(min_length=3, max_length=240)
    goal: str = Field(min_length=3, max_length=600)
    scope: str = Field(min_length=3, max_length=500)
    language: Literal['English'] = 'English'
    public_topic: Literal[True]


class Facet(Record):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,24}$')
    label: str = Field(min_length=3, max_length=90)
    question: str = Field(min_length=8, max_length=160)
    searches: list[str] = Field(min_length=3, max_length=3)
    success: str = Field(min_length=8, max_length=240)


class Plan(Record):
    facets: list[Facet] = Field(min_length=4, max_length=4)


class Dependency(Record):
    source: int | Literal['support']
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)
    dimension: Literal['population', 'denominator', 'period', 'condition', 'modality', 'example_attribution', 'definition', 'reading_context']
    reason: str = Field(min_length=8)


class Selection(Record):
    facet: str
    support: str | None  # None means missing evidence, never a fabricated handle
    state: Literal['reviewed', 'unknown']
    reason: str = Field(min_length=8)
    context_sources: list[int]
    dependencies: list[Dependency]
    conflict: str
    points: list[str] = Field(default_factory=list)
    next_question: str = ''
    next_action: str = ''


class Analysis(Record):
    # One selection per frozen requirement (sixteen), never two per axis.
    items: list[Selection] = Field(min_length=4, max_length=16)


LIMITS = dict(generation=6, native=64, edit_native_reserve=8, search_requests=12,
              sources=8, rounds=2, download_bytes=4 * 1024 * 1024, fetch_seconds=25,
              pdf_pages=6, source_characters=30000, catalog_characters=6000,
              stages=STAGES, low_addition_rounds=2)
