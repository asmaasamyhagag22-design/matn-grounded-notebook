from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .assets import render_figure_2
from .planner import build_demo_deck_plan
from .renderer import render_presentation, validate_rendered_pptx
from .validation import validate_deck_plan


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PDF = PROJECT_ROOT / "documents" / "2601.14525v1.pdf"
SOURCE_RUN = PROJECT_ROOT / "demo" / "phase04a"
DEFAULT_DEMO_OUTPUT = PROJECT_ROOT / "output" / "phase04a-english-demo"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"EXPECTED_JSON_OBJECT:{path}")
    return value


def prepare_validated_demo(output_dir: Path = DEFAULT_DEMO_OUTPUT) -> dict[str, Any]:
    """Build the cached demo without constructing or calling an Ollama client."""
    claims_artifact = _read_json(SOURCE_RUN / "claims.json")
    semantic_artifact = _read_json(SOURCE_RUN / "semantic-plan.json")
    claims = claims_artifact["claims"]
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_path = output_dir / "assets" / "figure-2-page-3.png"
    render_figure_2(SOURCE_PDF, asset_path)
    try:
        relative_asset = asset_path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        relative_asset = str(asset_path)
    plan = build_demo_deck_plan(claims, semantic_artifact, figure_asset_path=relative_asset)
    validation = validate_deck_plan(plan, claims, project_root=PROJECT_ROOT)
    plan_path = output_dir / "deck-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pptx_path = output_dir / "matn-phase04a-english-demo.pptx"
    render_presentation(plan, pptx_path, project_root=PROJECT_ROOT)
    render_validation = validate_rendered_pptx(pptx_path, expected_slides=len(plan["slides"]))
    receipt = {
        "status": "validated",
        "generation_mode": "validated_demo",
        "model_generation_calls": 0,
        "cloud_fallback_enabled": False,
        "plan_validation": validation,
        "presentation_validation": render_validation,
    }
    receipt_path = output_dir / "validation-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "plan": plan,
        "claims": claims,
        "plan_path": plan_path,
        "pptx_path": pptx_path,
        "asset_path": asset_path,
        "receipt_path": receipt_path,
        "validation": receipt,
    }
