"""Compute explicit Phase 03 metrics from a checklist and reviewed decisions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from matn_summarization.io import Phase03Error, read_json, write_json


def ratio(passed: int, applicable: int) -> dict[str, Any]:
    return {"numerator": passed, "denominator": applicable, "display": "N/A" if applicable == 0 else f"{passed} / {applicable}"}


def evaluate(checklist: dict[str, Any], run: dict[str, Any], review: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = run["summary"]
    claims = run["claims"]["claims"] if isinstance(run["claims"], dict) else run["claims"]
    audit = run["evidence_audit"]["checks"] if isinstance(run["evidence_audit"], dict) else run["evidence_audit"]
    selected = set(checklist["selection_chunk_ids"])
    evidence = [item for claim in claims for item in claim["evidence"]]
    metrics = {
        "citation_id_validity": ratio(sum(item["source_chunk_id"] in selected for item in evidence), len(evidence)),
        "exact_quote_validity": ratio(sum(item["exact_quote_match"] for item in audit), len(audit)),
        "canonical_quote_validity": ratio(sum(item["canonical_quote_match"] for item in audit), len(audit)),
        "boundary_purity": ratio(sum(item["source_chunk_id"] in selected for item in evidence), len(evidence)),
    }
    review_status = "pending_independent_human_review"
    for name in (
        "idea_coverage", "required_numeric_coverage", "generated_numeric_correctness",
        "required_terminology_coverage", "generated_terminology_correctness",
        "unsupported_claim_rate", "citation_support", "required_limitations_coverage",
    ):
        metrics[name] = ratio(0, 0)
    if review is not None:
        decisions = review.get("checklist_decisions", {})
        category_map = {"idea": "idea_coverage", "number": "required_numeric_coverage", "terminology": "required_terminology_coverage", "limitation": "required_limitations_coverage"}
        for category, metric_name in category_map.items():
            applicable = [item for item in checklist["items"] if item["category"] == category and decisions.get(item["id"]) != "not_applicable"]
            metrics[metric_name] = ratio(sum(decisions.get(item["id"]) == "pass" for item in applicable), len(applicable))
        claim_review = review.get("claim_support", {})
        reviewed = [claim for claim in claims if claim["claim_id"] in claim_review]
        metrics["citation_support"] = ratio(sum(claim_review[item["claim_id"]] == "supported" for item in reviewed), len(reviewed))
        metrics["unsupported_claim_rate"] = ratio(sum(claim_review[item["claim_id"]] == "unsupported" for item in reviewed), len(reviewed))
        generated_numbers = review.get("generated_numeric_correctness", {})
        reviewed_numbers = [value for value in generated_numbers.values() if value in {"correct", "incorrect"}]
        metrics["generated_numeric_correctness"] = ratio(sum(value == "correct" for value in reviewed_numbers), len(reviewed_numbers))
        generated_terms = review.get("generated_terminology_correctness", {})
        reviewed_terms = [value for value in generated_terms.values() if value in {"correct", "incorrect"}]
        metrics["generated_terminology_correctness"] = ratio(sum(value == "correct" for value in reviewed_terms), len(reviewed_terms))
        review_status = "human_review_supplied" if review.get("reviewed_by_human") is True else "non_independent_review_supplied"
    return {
        "schema_version": 1, "method": {"general_accuracy_reported": False, "schema_validity_is_factuality": False, "citation_existence_is_support": False},
        "review_status": review_status, "metrics": metrics,
        "counts": {"claims": len(claims), "summary_points": len(summary["summary_points"]), "evidence_quotes": len(evidence)},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checklist", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True, help="Directory containing summary.json, claims.json, evidence-audit.json")
    parser.add_argument("--review", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise SystemExit("output path exists")
    checklist = read_json(args.checklist)
    run = {
        "summary": read_json(args.run / "summary.json"),
        "claims": read_json(args.run / "claims.json"),
        "evidence_audit": read_json(args.run / "evidence-audit.json"),
    }
    review = read_json(args.review) if args.review else None
    report = evaluate(checklist, run, review)
    write_json(args.out, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
