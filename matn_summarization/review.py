from __future__ import annotations

from typing import Any

from .evidence import canonical_text


def _context(text: str, quote: str, radius: int = 140) -> tuple[str, str]:
    index = text.find(quote)
    if index < 0:
        quote = canonical_text(quote)
        text = canonical_text(text)
        index = text.find(quote)
        if index < 0:
            return "", ""
    return text[max(0, index - radius):index], text[index + len(quote):index + len(quote) + radius]


def _supporting_span(text: str, evidence: dict[str, Any]) -> str:
    if evidence.get("exact_text"):
        return evidence["exact_text"]
    quote = canonical_text(evidence["short_quote"])
    source = canonical_text(text)
    index = source.find(quote)
    if index < 0:
        return evidence["short_quote"]
    left_mark = max(source.rfind(mark, 0, index) for mark in (". ", "? ", "! "))
    left = left_mark + 2 if left_mark >= 0 else 0
    rights = [value for value in (source.find(mark, index + len(quote)) for mark in (". ", "? ", "! ")) if value >= 0]
    right = min(rights) + 1 if rights else len(source)
    return source[left:right].strip()


def _claim_parity_status(claim_id: str, parity: dict[str, Any] | None) -> str:
    if not parity:
        return "not_run"
    failures = [str(value) for values in parity.get("failures", {}).values() for value in values]
    return "fail" if any(value == claim_id or value.startswith(claim_id + ":") for value in failures) else "pass"


def _claim_check_status(claim_id: str, parity: dict[str, Any] | None, groups: tuple[str, ...]) -> str:
    if not parity:
        return "not_run"
    failures = [str(value) for group in groups for value in parity.get("failures", {}).get(group, [])]
    return "fail" if any(value == claim_id or value.startswith(claim_id + ":") for value in failures) else "pass"


NORMALIZATION_REASONS = {
    "normalized_malformed_reciprocal_math": "Deterministically restored the reciprocal expression from extraction markup while retaining the raw span.",
    "normalized_model_name_hyphenation": "Deterministically restored standard model-name hyphenation.",
    "normalized_compound_hyphenation": "Deterministically restored a split technical compound.",
    "merged_model_fragments": "Deterministically joined adjacent model fragments after boundary validation.",
}


def build_claims_review(
    summary: dict[str, Any],
    claims: list[dict[str, Any]],
    selection: dict[str, Any],
    *,
    english_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chunks = {chunk["chunk_id"]: chunk for chunk in selection["chunks"]}
    selected = set(summary["selected_claim_ids"])
    english_renderings = (english_summary or summary).get("claim_renderings", {})
    arabic_renderings = summary.get("claim_renderings", {}) if english_summary is not None else {}
    parity = summary.get("parity_validation")
    points: list[dict[str, Any]] = []
    for index, claim in enumerate((item for item in claims if item["claim_id"] in selected), 1):
        evidence_rows: list[dict[str, Any]] = []
        pages: list[int] = []
        for evidence in claim["evidence"]:
            chunk = chunks[evidence["source_chunk_id"]]
            before, after = _context(chunk.get("selection_text", ""), evidence["short_quote"])
            page = evidence.get("pdf_page", chunk["pdf_page"])
            if page not in pages:
                pages.append(page)
            evidence_rows.append({
                "claim_id": claim["claim_id"], "claim_text": claim["claim_text"], "pdf_page": page,
                "chunk_id": chunk["chunk_id"], "exact_short_quote": evidence["short_quote"],
                "complete_evidence_span": _supporting_span(chunk.get("selection_text", ""), evidence),
                "context_before": before, "context_after": after,
                "content_risk_flags": claim.get("content_risk_flags", chunk.get("content_risk_flags", [])),
                "extraction_review_status": claim.get("review_status", "unreviewed"),
                "semantic_support_status": "unreviewed", "reviewer_note": "",
            })
        arabic = arabic_renderings.get(claim["claim_id"], "")
        normalization_notes = [
            {
                "normalization_type": note,
                "normalization_reason": NORMALIZATION_REASONS.get(note, "Deterministic conservative text normalization."),
                "verification": "deterministic",
            }
            for note in claim.get("normalization_notes", [])
        ]
        normalization = {
            "raw_extracted_text": [item["complete_evidence_span"] for item in evidence_rows],
            "normalized_claim_text": claim["claim_text"],
            "notes": normalization_notes,
            "visually_verified": claim.get("review_status") == "visually_verified",
            "contributing_chunk_ids": [item["chunk_id"] for item in evidence_rows],
            "pages": pages,
        }
        numeric_status = _claim_check_status(claim["claim_id"], parity, ("numeric_values", "units", "qualifiers")) if arabic else "not_run"
        terminology_status = _claim_check_status(claim["claim_id"], parity, ("terminology",)) if arabic else "not_run"
        if arabic and parity:
            missing_terms = [str(item).casefold() for item in parity.get("failures", {}).get("terminology", [])]
            claim_terms = " ".join([claim["claim_text"], *claim.get("technical_terms", [])]).casefold()
            if any(term in claim_terms for term in missing_terms):
                terminology_status = "fail"
        semantic_status = _claim_check_status(claim["claim_id"], parity, ("negations", "semantic_relations")) if arabic else "not_run"
        mandatory = (numeric_status, terminology_status, semantic_status)
        aggregate_status = "fail" if "fail" in mandatory else ("pass" if arabic and all(value == "pass" for value in mandatory) else "not_run")
        points.append({
            "point_id": f"P{index:03d}", "claim_id": claim["claim_id"], "claim_ids": [claim["claim_id"]],
            "english_claim": english_renderings.get(claim["claim_id"], claim["claim_text"]),
            "arabic_rendering": arabic, "point_text": arabic or english_renderings.get(claim["claim_id"], claim["claim_text"]),
            "evidence": evidence_rows, "pages": pages, "normalization": normalization,
            "numeric_check": numeric_status,
            "terminology_check": terminology_status,
            "semantic_relation_check": semantic_status,
            "automated_parity_result": aggregate_status,
            "human_semantic_status": "unreviewed", "semantic_support_status": "unreviewed", "reviewer_note": "",
        })
    return {"schema_version": 3, "review_status": "pending_human_review", "independent_human_reviewed": False, "points": points}


def _display_text(value: Any) -> str:
    return str(value).replace("\n", " ").strip()


def render_claims_review(review: dict[str, Any]) -> str:
    lines = [
        "# Claims review", "",
        "Status: pending human semantic review. Automated checks are risk gates, not proof of semantic correctness; no item is automatically marked supported.", "",
    ]
    for point in review["points"]:
        lines.extend([
            f"## {point['point_id']} · `{point['claim_id']}`", "",
            "**English canonical claim**", "",
            f"<div dir=\"ltr\">{_display_text(point['english_claim'])}</div>", "",
            "**Arabic rendering**", "",
            f"<div dir=\"rtl\">{_display_text(point['arabic_rendering']) if point['arabic_rendering'] else '—'}</div>", "",
            f"**Pages:** {', '.join(map(str, point['pages'])) or '—'}", "",
            "**Ordered evidence spans**", "",
        ])
        for index, item in enumerate(point["evidence"], 1):
            lines.extend([
                f"{index}. `{item['chunk_id']}` · PDF p. {item['pdf_page']}", "",
                f"   <div dir=\"ltr\">{_display_text(item['complete_evidence_span'])}</div>", "",
            ])
        normalization = point["normalization"]
        lines.extend(["**Normalization notes**", ""])
        if normalization["notes"]:
            for note in normalization["notes"]:
                lines.append(
                    f"- `{note['normalization_type']}` ({note['verification']}): {note['normalization_reason']}"
                )
            lines.append("")
        else:
            lines.extend(["- None; normalized claim matches the deterministically canonicalized evidence text.", ""])
        lines.extend([
            f"- Contributing chunks: {', '.join(f'`{item}`' for item in normalization['contributing_chunk_ids'])}",
            f"- Visual verification recorded: {'yes' if normalization['visually_verified'] else 'no'}", "",
            "**Automated checks**", "",
            f"- Numeric / units / qualifiers: `{point['numeric_check']}`",
            f"- Terminology: `{point['terminology_check']}`",
            f"- Semantic relations / negation: `{point['semantic_relation_check']}`",
            f"- Aggregate parity: `{point['automated_parity_result']}`", "",
            f"**Human status:** `{point['human_semantic_status']}`", "",
            f"**Reviewer note:** {point['reviewer_note'] or '—'}", "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def build_coverage_report(summary: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1, "review_status": "pending_human_review",
        "available_claim_ids": summary["available_claim_ids"], "selected_claim_ids": summary["selected_claim_ids"],
        "omitted_claim_ids": summary["omitted_claim_ids"], "omission_reason": summary["omission_reason"],
        "source_topic_coverage": summary["source_topic_coverage"], "numeric_coverage": summary["numeric_coverage"],
        "terminology_coverage": summary["terminology_coverage"], "limitations_coverage": summary["limitations_coverage"],
        "coverage_warnings": summary["coverage_warnings"], "inventory_completeness": inventory,
        "generated_numeric_correctness": {"display": "N/A", "numerator": 0, "denominator": 0},
        "generated_terminology_correctness": {"display": "N/A", "numerator": 0, "denominator": 0},
        "citation_support": {"display": "N/A", "numerator": 0, "denominator": 0},
        "unsupported_claim_rate": {"display": "N/A", "numerator": 0, "denominator": 0},
    }


def render_coverage_report(report: dict[str, Any]) -> str:
    def metric(name: str) -> str:
        value = report[name]
        return value["display"] if "display" in value else f"{value.get('selected', 0)} / {value.get('available', 0)}"

    lines = [
        "# Coverage report", "", "Status: pending human review.", "",
        f"- Available claims: {len(report['available_claim_ids'])}", f"- Selected claims: {len(report['selected_claim_ids'])}",
        f"- Omitted claims: {len(report['omitted_claim_ids'])}", f"- Source-topic coverage: {metric('source_topic_coverage')}",
        f"- Numeric inventory coverage: {metric('numeric_coverage')}", f"- Terminology inventory coverage: {metric('terminology_coverage')}",
        f"- Limitations inventory coverage: {metric('limitations_coverage')}", f"- Generated numeric correctness: {metric('generated_numeric_correctness')}",
        f"- Generated terminology correctness: {metric('generated_terminology_correctness')}", f"- Citation support: {metric('citation_support')}",
        f"- Unsupported claim rate: {metric('unsupported_claim_rate')}", "", "## Omissions", "",
    ]
    lines.extend((f"- `{claim_id}`: {report['omission_reason'][claim_id]}" for claim_id in report["omitted_claim_ids"]))
    if not report["omitted_claim_ids"]:
        lines.append("- None.")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {item}" for item in report["coverage_warnings"] or ["None."])
    return "\n".join(lines).rstrip() + "\n"
