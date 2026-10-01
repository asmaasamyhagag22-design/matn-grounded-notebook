from __future__ import annotations

import re
from typing import Any

from .evidence import canonical_text


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = canonical_text(value).casefold()
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


ANAPHOR_RE = re.compile(
    r"\bthis\s+(?P<noun>(?:[a-z-]+\s+){0,3}(?:function|method|configuration))\b",
    re.IGNORECASE,
)


def order_claims_with_antecedents(
    claims: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Keep source order, except to place an anaphoric claim after its antecedent.

    The returned mapping is dependent claim ID -> antecedent claim ID. Callers use
    it to keep both claims in the same rendered section as well as in the right
    order.
    """
    ordered = list(claims)
    dependencies: dict[str, str] = {}
    for dependent in list(ordered):
        match = ANAPHOR_RE.search(dependent.get("claim_text", ""))
        if not match:
            continue
        noun = match.group("noun").casefold()
        candidates = [
            claim for claim in ordered
            if claim is not dependent
            and re.search(r"\b(?:a|an|the)\s+" + re.escape(noun) + r"\b", claim.get("claim_text", ""), re.IGNORECASE)
        ]
        if not candidates:
            continue
        dependent_index = ordered.index(dependent)
        antecedent = min(candidates, key=lambda claim: abs(ordered.index(claim) - dependent_index))
        dependencies[dependent["claim_id"]] = antecedent["claim_id"]
        ordered.remove(dependent)
        ordered.insert(ordered.index(antecedent) + 1, dependent)
    return ordered, dependencies


def rewrite_orphan_anaphora(text: str, canonical_english: str, language: str) -> str:
    """Replace an orphaned demonstrative with an explicit technical noun phrase."""
    match = ANAPHOR_RE.search(canonical_english)
    if not match:
        return text
    noun = match.group("noun")
    if language == "en":
        return ANAPHOR_RE.sub("the " + noun, text, count=1)
    explicit = {
        "function": "الدالة المحددة",
        "inference function": "دالة الاستنتاج",
        "method": "الطريقة المحددة",
        "configuration": "إعداد المهمة المحدد",
        "job configuration": "إعداد المهمة",
    }.get(noun.casefold(), "المكوّن المحدد")
    return re.sub(r"(?:هذه|هذا)\s+(?:الدالة|الطريقة|الإعداد|التكوين)", explicit, text, count=1)


def build_semantic_plan(
    claims: list[dict[str, Any]],
    length: str,
    comprehensive: bool = False,
    visually_verified_claim_ids: set[str] | None = None,
) -> dict[str, Any]:
    available = [claim["claim_id"] for claim in claims]
    verified = set(visually_verified_claim_ids or set())

    def raw_picture_text(claim: dict[str, Any]) -> bool:
        return (
            "contains_picture_region" in set(claim.get("content_risk_flags", []))
            or "<!-- Start of picture text -->" in claim.get("claim_text", "")
        )

    safe = [
        claim for claim in claims
        if not raw_picture_text(claim)
        and (claim.get("review_status") != "human_review_required" or claim["claim_id"] in verified)
    ]
    excluded_picture = [claim for claim in claims if raw_picture_text(claim)]
    excluded_risk = [
        claim for claim in claims
        if claim.get("review_status") == "human_review_required"
        and claim["claim_id"] not in verified
        and not raw_picture_text(claim)
    ]
    if comprehensive or length == "long":
        selected_claims = safe
    else:
        limit = 5 if length == "short" else 10
        ranked = sorted(
            enumerate(safe),
            key=lambda pair: (
                0 if pair[1].get("importance") == "core" else 1,
                0 if pair[1].get("limitation_or_uncertainty") else 1,
                0 if pair[1].get("numbers_and_units") else 1,
                pair[0],
            ),
        )
        chosen = {claim["claim_id"] for _, claim in ranked[:limit]}
        selected_claims = [claim for claim in safe if claim["claim_id"] in chosen]
    selected = [claim["claim_id"] for claim in selected_claims]
    omission_reason: dict[str, str] = {}
    for claim in excluded_picture:
        omission_reason[claim["claim_id"]] = "excluded_raw_picture_text"
    for claim in excluded_risk:
        omission_reason[claim["claim_id"]] = "excluded_pending_visual_review_of_extraction-risk_value"
    for claim in safe:
        if claim["claim_id"] not in set(selected):
            omission_reason[claim["claim_id"]] = "omitted_for_requested_length"
    omitted = [claim_id for claim_id in available if claim_id not in set(selected)]
    dropped_core = [claim["claim_id"] for claim in safe if claim.get("importance") == "core" and claim["claim_id"] not in set(selected)]

    def coverage(field: str, predicate=lambda claim: True) -> dict[str, Any]:
        available_values = _unique([
            str(value)
            for claim in claims if predicate(claim)
            for value in claim.get(field, [])
        ])
        selected_values = _unique([
            str(value)
            for claim in selected_claims if predicate(claim)
            for value in claim.get(field, [])
        ])
        return {
            "available": len(available_values),
            "selected": len(selected_values),
            "omitted": len([value for value in available_values if canonical_text(value).casefold() not in {canonical_text(item).casefold() for item in selected_values}]),
        }

    topics_available = _unique([claim.get("topic", "") for claim in claims])
    topics_selected = _unique([claim.get("topic", "") for claim in selected_claims])
    warnings: list[str] = []
    if dropped_core:
        warnings.append("Requested length is insufficient for comprehensive coverage; high-importance claims were omitted.")
    if excluded_risk:
        warnings.append("Values found only in extraction-risk figure or table content were omitted pending visual review.")
    if excluded_picture:
        warnings.append("Raw picture-region transcription was omitted and cannot be promoted to summary content.")
    if any(claim.get("review_status") == "visually_verified" and claim.get("numbers_and_units") for claim in selected_claims):
        warnings.append("Values present in textual captions were visually verified against the PDF and retained.")
    return {
        "available_claim_ids": available,
        "selected_claim_ids": selected,
        "omitted_claim_ids": omitted,
        "omission_reason": omission_reason,
        "source_topic_coverage": {"available": len(topics_available), "selected": len(topics_selected)},
        "numeric_coverage": coverage("numbers_and_units"),
        "terminology_coverage": coverage("technical_terms"),
        "limitations_coverage": {
            "available": sum(bool(claim.get("limitation_or_uncertainty")) for claim in claims),
            "selected": sum(bool(claim.get("limitation_or_uncertainty")) for claim in selected_claims),
        },
        "coverage_warnings": warnings,
        "comprehensive_requested": bool(comprehensive or length == "long"),
    }
