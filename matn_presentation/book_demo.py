from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .demo import DEFAULT_DEMO_OUTPUT, PROJECT_ROOT, SOURCE_RUN, prepare_validated_demo
from .schema import load_deck_plan


BOOK_OUTPUT = PROJECT_ROOT / "output" / "book-demo"
BOOK_PLAN = BOOK_OUTPUT / "deck-plan.json"
BOOK_CLAIMS = BOOK_OUTPUT / "claims.json"
BOOK_PPTX = BOOK_OUTPUT / "matn-working-with-text-data-v2.pptx"
BOOK_PDF = BOOK_OUTPUT / "matn-working-with-text-data-v2.pdf"
BOOK_RECEIPT = BOOK_OUTPUT / "validation-receipt.json"
BOOK_PREVIEWS = BOOK_OUTPUT / "slide-previews-v2"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"EXPECTED_JSON_OBJECT:{path}")
    return value


def prepared_book_demo_ready() -> bool:
    required = [BOOK_PLAN, BOOK_CLAIMS, BOOK_PPTX, BOOK_PDF, BOOK_RECEIPT]
    if not all(path.is_file() for path in required):
        return False
    try:
        receipt = _read_json(BOOK_RECEIPT)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return False
    return receipt.get("status") == "validated"


def load_prepared_book_demo() -> dict[str, Any]:
    if not prepared_book_demo_ready():
        raise FileNotFoundError("PREPARED_BOOK_DEMO_NOT_READY")
    claims_artifact = _read_json(BOOK_CLAIMS)
    receipt = _read_json(BOOK_RECEIPT)
    return {
        "sample_kind": "book",
        "plan": load_deck_plan(BOOK_PLAN),
        "claims": claims_artifact["claims"],
        "plan_path": BOOK_PLAN,
        "pptx_path": BOOK_PPTX,
        "pdf_path": BOOK_PDF,
        "receipt_path": BOOK_RECEIPT,
        "preview_dir": BOOK_PREVIEWS,
        "validation": receipt,
        "summary_points": receipt.get("overview_points", []),
        "load_run_details": {
            "cache_status": "prepared_validated_sample",
            "model_generation_calls": 0,
            "prepared_sample": True,
        },
    }


def load_paper_fallback() -> dict[str, Any]:
    plan_path = DEFAULT_DEMO_OUTPUT / "deck-plan.json"
    pptx_path = DEFAULT_DEMO_OUTPUT / "matn-phase04a-english-demo.pptx"
    receipt_path = DEFAULT_DEMO_OUTPUT / "validation-receipt.json"
    if not (plan_path.is_file() and pptx_path.is_file() and receipt_path.is_file()):
        result = prepare_validated_demo()
    else:
        result = {
            "plan": load_deck_plan(plan_path),
            "claims": _read_json(SOURCE_RUN / "claims.json")["claims"],
            "plan_path": plan_path,
            "pptx_path": pptx_path,
            "receipt_path": receipt_path,
            "validation": _read_json(receipt_path),
        }
    return {
        **result,
        "sample_kind": "paper_fallback",
        "load_run_details": {
            "cache_status": "validated_cached_demo",
            "model_generation_calls": 0,
            "prepared_sample": True,
        },
    }


def load_primary_demo() -> dict[str, Any]:
    if prepared_book_demo_ready():
        return load_prepared_book_demo()
    return load_paper_fallback()
