from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


class DeckPlanError(ValueError):
    """Raised when a deck plan fails closed."""


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = PROJECT_ROOT / "schemas" / "deck-plan.schema.json"


def validate_deck_plan_schema(plan: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(plan), key=lambda item: list(item.path))
    if errors:
        details = "; ".join(f"{'/'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in errors[:8])
        raise DeckPlanError(f"DECK_PLAN_SCHEMA_INVALID: {details}")


def load_deck_plan(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DeckPlanError("DECK_PLAN_ROOT_MUST_BE_OBJECT")
    validate_deck_plan_schema(value)
    return value
