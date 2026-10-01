"""Grounded presentation planning and rendering for Matn Phase 04A."""

from .demo import DEFAULT_DEMO_OUTPUT, prepare_validated_demo
from .schema import DeckPlanError, load_deck_plan, validate_deck_plan_schema
from .validation import validate_deck_plan

__all__ = [
    "DEFAULT_DEMO_OUTPUT",
    "DeckPlanError",
    "load_deck_plan",
    "prepare_validated_demo",
    "validate_deck_plan",
    "validate_deck_plan_schema",
]
