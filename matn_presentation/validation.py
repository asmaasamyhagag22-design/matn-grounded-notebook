from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .schema import DeckPlanError, validate_deck_plan_schema


PICTURE_MARKER = "<!-- Start of picture text -->"


def _claim_pages(claim: dict[str, Any]) -> list[int]:
    return sorted({int(item["pdf_page"]) for item in claim.get("evidence", [])})


def _is_loopback(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        return False
    if parsed.hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


def validate_deck_plan(
    plan: dict[str, Any],
    claims: list[dict[str, Any]],
    *,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Validate schema, provenance, risk exclusions, and local-only claims.

    The validator deliberately fails closed. It never repairs a deck plan.
    """
    validate_deck_plan_schema(plan)
    claim_map = {claim["claim_id"]: claim for claim in claims}
    accepted_risk = set(plan.get("validation_profile", {}).get("accepted_risk_claim_ids", []))
    used: set[str] = set()

    if "src-src-036" in accepted_risk:
        raise DeckPlanError("RAW_PICTURE_TEXT_CANNOT_BE_ACCEPTED")

    for slide in plan["slides"]:
        bullet_ids: set[str] = set()
        for bullet in slide["bullets"]:
            if not bullet["claim_ids"]:
                raise DeckPlanError(f"BULLET_WITHOUT_PROVENANCE:{slide['slide_id']}")
            for claim_id in bullet["claim_ids"]:
                claim = claim_map.get(claim_id)
                if claim is None:
                    raise DeckPlanError(f"UNKNOWN_CLAIM:{claim_id}")
                flags = set(claim.get("content_risk_flags", []))
                text = claim.get("claim_text", "")
                if claim_id == "src-src-036" or "contains_picture_region" in flags or PICTURE_MARKER in text:
                    raise DeckPlanError(f"PICTURE_TEXT_CLAIM_FORBIDDEN:{claim_id}")
                status = claim.get("review_status", "unreviewed")
                if status in {"rejected", "unresolved", "fragment"}:
                    raise DeckPlanError(f"REJECTED_OR_UNRESOLVED_CLAIM:{claim_id}")
                if status == "human_review_required" and claim_id not in accepted_risk:
                    raise DeckPlanError(f"UNVERIFIED_RISK_CLAIM:{claim_id}")
                used.add(claim_id)
                bullet_ids.add(claim_id)

        cited_ids: set[str] = set()
        for citation in slide["citations"]:
            cited_ids.update(citation["claim_ids"])
            expected_pages = sorted({page for claim_id in citation["claim_ids"] for page in _claim_pages(claim_map[claim_id])})
            if citation["pdf_pages"] != expected_pages:
                raise DeckPlanError(f"CITATION_PAGE_MISMATCH:{slide['slide_id']}")
        if bullet_ids != cited_ids:
            raise DeckPlanError(f"SLIDE_CITATION_CLAIM_MISMATCH:{slide['slide_id']}")

        asset = slide.get("visual_asset")
        if asset:
            if asset["source_pdf_page"] not in {page for citation in slide["citations"] for page in citation["pdf_pages"]}:
                raise DeckPlanError(f"VISUAL_ASSET_PAGE_NOT_CITED:{slide['slide_id']}")
            if project_root is not None and not (project_root / asset["path"]).is_file():
                raise DeckPlanError(f"VISUAL_ASSET_MISSING:{asset['path']}")

    omitted = {item["claim_id"] for item in plan["omitted_claims"]}
    all_ids = set(claim_map)
    if used & omitted:
        raise DeckPlanError("CLAIM_BOTH_USED_AND_OMITTED")
    if used | omitted != all_ids:
        missing = sorted(all_ids - used - omitted)
        raise DeckPlanError(f"CLAIMS_NOT_ACCOUNTED_FOR:{','.join(missing)}")
    if "src-src-036" in used:
        raise DeckPlanError("SRC_SRC_036_FORBIDDEN")

    proxy_bullets = [
        bullet
        for slide in plan["slides"]
        for bullet in slide["bullets"]
        if "proxy reward" in bullet["text"].casefold()
    ]
    if proxy_bullets and not any("src-src-010" in bullet["claim_ids"] for bullet in proxy_bullets):
        raise DeckPlanError("PROXY_REWARD_MISSING_RECIPROCAL_CLAIM")
    if proxy_bullets and "src-src-010" not in used:
        raise DeckPlanError("SRC_SRC_010_REQUIRED")

    if not any(slide["layout"] == "sources" for slide in plan["slides"]):
        raise DeckPlanError("SOURCE_DISCLOSURE_SLIDE_REQUIRED")

    provenance = plan["provenance"]
    endpoint = provenance.get("inference_endpoint")
    if endpoint and not _is_loopback(endpoint):
        raise DeckPlanError("NON_LOOPBACK_INFERENCE_ENDPOINT")
    if plan["generation_mode"] == "validated_demo":
        if provenance["model_generation_calls"] != 0:
            raise DeckPlanError("VALIDATED_DEMO_MODEL_CALLS_MUST_BE_ZERO")
        if provenance["cache_status"] != "validated_cached_demo":
            raise DeckPlanError("VALIDATED_DEMO_CACHE_DISCLOSURE_REQUIRED")
    if plan["generation_mode"] == "prepared_sample":
        if provenance["model_generation_calls"] < 1:
            raise DeckPlanError("PREPARED_SAMPLE_REQUIRES_RECORDED_MODEL_CALLS")
        if provenance["cache_status"] != "prepared_validated_sample":
            raise DeckPlanError("PREPARED_SAMPLE_CACHE_DISCLOSURE_REQUIRED")
        if provenance.get("inference_endpoint") != "http://127.0.0.1:11434":
            raise DeckPlanError("PREPARED_SAMPLE_ENDPOINT_MISMATCH")

    return {
        "status": "pass",
        "slide_count": len(plan["slides"]),
        "used_claim_ids": sorted(used),
        "omitted_claim_ids": sorted(omitted),
        "model_generation_calls": provenance["model_generation_calls"],
    }
