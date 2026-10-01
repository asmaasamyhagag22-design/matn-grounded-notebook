from __future__ import annotations

import re
import unicodedata
from typing import Any

from .io import Phase03Error, canonical_json


def canonical_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def validate_claims(claims: list[dict[str, Any]], allowed_text: dict[str, str], prefix: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    evidence_audit: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, original in enumerate(claims, 1):
        claim = dict(original)
        local = claim["local_claim_id"]
        claim_id = f"{prefix}-{local}"
        if claim_id in seen:
            raise Phase03Error("DUPLICATE_CLAIM_ID")
        seen.add(claim_id)
        claim["claim_id"] = claim_id
        for evidence in claim["evidence"]:
            chunk_id = evidence["source_chunk_id"]
            if chunk_id not in allowed_text:
                raise Phase03Error("EVIDENCE_CHUNK_OUTSIDE_SELECTION")
            quote = evidence["short_quote"]
            text = allowed_text[chunk_id]
            exact = quote in text
            canonical = exact or canonical_text(quote) in canonical_text(text)
            evidence_audit.append({
                "claim_id": claim_id, "source_chunk_id": chunk_id,
                "exact_quote_match": exact, "canonical_quote_match": canonical,
                "semantic_support": "unreviewed",
                "reviewer_note": "",
            })
            if not canonical:
                raise Phase03Error("EVIDENCE_QUOTE_NOT_FOUND")
            exact_text = evidence.get("exact_text")
            if exact_text and canonical_text(exact_text) not in canonical_text(text):
                raise Phase03Error("EVIDENCE_SPAN_NOT_FOUND")
        accepted.append(claim)
    return accepted, evidence_audit


def deduplicate_claims(claims: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    result: list[dict[str, Any]] = []
    duplicates: list[dict[str, str]] = []
    exact_seen: dict[tuple[Any, ...], str] = {}
    canonical_seen: dict[tuple[Any, ...], str] = {}
    for claim in claims:
        text = claim["claim_text"]
        normalized = canonical_text(text)
        # Only merge claims that are textually equivalent *and* retain the same
        # semantic facets. This intentionally keeps distinct numbers, roles,
        # constraints, metrics, and limitations even when their wording is close.
        facets = (
            tuple(sorted(canonical_text(str(item)).casefold() for item in claim.get("numbers_and_units", []))),
            tuple(sorted(canonical_text(str(item)).casefold() for item in claim.get("technical_terms", []))),
            canonical_text(str(claim.get("limitation_or_uncertainty") or "")).casefold(),
            canonical_text(str(claim.get("topic") or "")).casefold(),
        )
        exact_key = (text, *facets)
        canonical_key = (normalized, *facets)
        existing = exact_seen.get(exact_key) or canonical_seen.get(canonical_key)
        if existing:
            duplicates.append({"removed_claim_id": claim["claim_id"], "kept_claim_id": existing})
            continue
        exact_seen[exact_key] = claim["claim_id"]
        canonical_seen[canonical_key] = claim["claim_id"]
        result.append(claim)
    return result, duplicates


def validate_synthesis(
    summary: dict[str, Any],
    claims: list[dict[str, Any]],
    selected_claim_ids: list[str] | None = None,
) -> None:
    known = {claim["claim_id"] for claim in claims}
    groups = [summary["summary_points"], summary["key_numbers"], summary["key_terms"], summary["limitations"]]
    for group in groups:
        for item in group:
            if not item["claim_ids"] or not set(item["claim_ids"]).issubset(known):
                raise Phase03Error("SYNTHESIS_UNKNOWN_CLAIM_ID")
    represented = {
        claim_id
        for group in groups
        for item in group
        for claim_id in item["claim_ids"]
    }
    if selected_claim_ids is not None and not set(selected_claim_ids).issubset(represented):
        raise Phase03Error("SYNTHESIS_MISSING_SELECTED_CLAIM")


def resolve_citations(summary: dict[str, Any], claims: list[dict[str, Any]], selection: dict[str, Any], store: dict[str, Any]) -> dict[str, Any]:
    claim_map = {item["claim_id"]: item for item in claims}
    pages = {item["pdf_page"]: item for item in store["pages"]}
    citations = {item["chunk_id"]: item for item in selection["citations"]}
    points: list[dict[str, Any]] = []
    for point in summary["summary_points"]:
        chunk_ids: list[str] = []
        claim_provenance: list[dict[str, Any]] = []
        for claim_id in point["claim_ids"]:
            claim = claim_map[claim_id]
            evidence = []
            for item in claim["evidence"]:
                chunk_id = item["source_chunk_id"]
                if chunk_id not in citations:
                    raise Phase03Error("CITATION_OUTSIDE_SELECTION")
                if chunk_id not in chunk_ids:
                    chunk_ids.append(chunk_id)
                evidence.append({
                    "source_chunk_id": chunk_id,
                    "short_quote": item["short_quote"],
                    **({"exact_text": item["exact_text"]} if item.get("exact_text") else {}),
                    **({"start_offset": item["start_offset"]} if item.get("start_offset") is not None else {}),
                    **({"end_offset": item["end_offset"]} if item.get("end_offset") is not None else {}),
                    **({"pdf_page": item["pdf_page"]} if item.get("pdf_page") is not None else {}),
                })
            claim_provenance.append({"claim_id": claim_id, "evidence": evidence})
        resolved = []
        seen_pages: set[int] = set()
        for chunk_id in chunk_ids:
            pdf_page = citations[chunk_id]["pdf_page"]
            if pdf_page in seen_pages:
                continue
            seen_pages.add(pdf_page)
            page = pages[pdf_page]
            display = f"[PDF p. {pdf_page}]"
            if page.get("printed_page") is not None and str(page["printed_page"]) != str(pdf_page):
                display = f"[PDF p. {pdf_page}; printed p. {page['printed_page']}]"
            resolved.append({"pdf_page": pdf_page, "page_label": page.get("page_label"), "printed_page": page.get("printed_page"), "display": display})
        points.append({**point, "citations": resolved, "provenance": claim_provenance})
    return {**summary, "summary_points": points}


def coverage_status(flags: list[str]) -> dict[str, bool]:
    values = set(flags)
    return {
        "text_supported": True,
        "limited_by_table_extraction": bool(values & {"contains_table", "complex_table_suspected"}),
        "limited_by_equation_extraction": "equation_or_symbol_risk" in values,
        "limited_by_picture_content": "contains_picture_region" in values,
        "human_review_required": "needs_human_review" in values or bool(values & {"complex_table_suspected", "equation_or_symbol_risk", "contains_picture_region", "extraction_order_risk"}),
    }


def deterministic_projection(value: Any) -> str:
    def strip(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: strip(child) for key, child in item.items() if key not in {"run_id", "started_at", "completed_at", "wall_clock_ns"}}
        if isinstance(item, list):
            return [strip(child) for child in item]
        return item
    return canonical_json(strip(value))
