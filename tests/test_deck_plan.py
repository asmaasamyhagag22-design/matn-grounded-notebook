from __future__ import annotations

import json
from pathlib import Path

import pytest

from matn_presentation.planner import build_demo_deck_plan
from matn_presentation.schema import DeckPlanError, validate_deck_plan_schema
from matn_presentation.validation import validate_deck_plan


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "demo" / "phase04a"


def source_artifacts():
    claims = json.loads((RUN / "claims.json").read_text(encoding="utf-8"))["claims"]
    semantic = json.loads((RUN / "semantic-plan.json").read_text(encoding="utf-8"))
    return claims, semantic


def test_demo_plan_schema_provenance_and_exclusions():
    claims, semantic = source_artifacts()
    plan = build_demo_deck_plan(claims, semantic, figure_asset_path="output/phase04a-english-demo/assets/figure-2-page-3.png")
    validate_deck_plan_schema(plan)
    result = validate_deck_plan(plan, claims)
    used = set(result["used_claim_ids"])
    assert len(plan["slides"]) == 10
    assert "src-src-036" not in used
    assert "src-src-010" in used
    assert any("1 / loss" in bullet["text"] for slide in plan["slides"] for bullet in slide["bullets"])
    assert {item["claim_id"] for item in plan["omitted_claims"]} == {"src-src-002", "src-src-003", "src-src-004", "src-src-009", "src-src-036"}


def test_validator_fails_closed_if_picture_text_claim_is_reintroduced():
    claims, semantic = source_artifacts()
    plan = build_demo_deck_plan(claims, semantic, figure_asset_path="output/phase04a-english-demo/assets/figure-2-page-3.png")
    plan["slides"][1]["bullets"][0]["claim_ids"] = ["src-src-036"]
    plan["slides"][1]["citations"] = [{"claim_ids": ["src-src-036"], "pdf_pages": [3]}]
    plan["omitted_claims"] = [item for item in plan["omitted_claims"] if item["claim_id"] != "src-src-036"]
    plan["omitted_claims"].append({"claim_id": "src-src-001", "reason": "test"})
    with pytest.raises(DeckPlanError, match="PICTURE_TEXT_CLAIM_FORBIDDEN"):
        validate_deck_plan(plan, claims)


def test_validator_rejects_non_loopback_endpoint():
    claims, semantic = source_artifacts()
    plan = build_demo_deck_plan(claims, semantic, figure_asset_path="output/phase04a-english-demo/assets/figure-2-page-3.png")
    plan["generation_mode"] = "live_local"
    plan["provenance"]["inference_endpoint"] = "https://api.example.com"
    with pytest.raises(DeckPlanError, match="NON_LOOPBACK"):
        validate_deck_plan(plan, claims)
