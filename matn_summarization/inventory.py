from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .budget import SourceUnit
from .evidence import canonical_text


NUMBER_RE = re.compile(
    r"(?<![\w.])(?:\d+(?:\.\d+)?(?:%|[kKmMbB])?|\d+(?:\.\d+)?\s*(?:minutes?|seconds?|hours?|times?|GPUs?|tokens?|files?))(?![\w.])"
)
TERM_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9]*(?:[.-][A-Za-z0-9]+)*|[A-Za-z]+(?:-[A-Za-z0-9]+)+|[A-Z]{2,}[A-Za-z0-9.-]*)\b"
)
LIMITATION_RE = re.compile(
    r"\b(?:only|cannot|do not|does not|not allow|avoid|prevent|freeze|fixed|failed|fails|failure|maximum|at most|constraint|limitation|caveat|risk|halt)\b",
    re.IGNORECASE,
)

TERMINAL_RE = re.compile(r"[.!?](?:[\"'’”)]|</?[^>]+>|\*|_)*$")
LEADING_CONTINUATION_RE = re.compile(
    r"^(?:to|and|or|but|nor|so|yet|as|than|that|which|who|whose|where|when|while|with|without|"
    r"from|into|onto|for|of|by|on|in|at|under|over|after|before|because|if|unless|until|via)\b",
    re.IGNORECASE,
)
STRUCTURAL_RE = re.compile(r"^(?:#{1,6}\s|>\s*\d|\d+\s*$|\|[-:|\s]+\|?$)")


@dataclass(frozen=True)
class EvidenceSpan:
    source_chunk_id: str
    pdf_page: int
    exact_text: str
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class ReconciledStatement:
    text: str
    evidence_spans: tuple[EvidenceSpan, ...]
    source_order: int
    complete: bool
    review_reason: str | None = None
    normalization_notes: tuple[str, ...] = ()


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = canonical_text(value).strip(" ,.;:()[]{}")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def number_candidates(text: str) -> list[str]:
    return _unique(match.group(0) for match in NUMBER_RE.finditer(text))


def term_candidates(text: str) -> list[str]:
    stop = {"the", "this", "that", "first", "second", "table", "figure", "source"}
    return [item for item in _unique(match.group(0) for match in TERM_RE.finditer(text)) if item.casefold() not in stop]


def limitation_candidates(text: str) -> list[str]:
    return [statement for statement in split_statements(text) if LIMITATION_RE.search(statement)]


def split_statements(text: str) -> list[str]:
    cleaned = text.strip()
    if (
        not cleaned
        or re.fullmatch(r"[#*\s\d.]+", cleaned)
        or re.match(r"^#{1,6}\s", cleaned)
        or re.match(r"^>\s*\d+\s*\w", cleaned)
    ):
        return []
    parts = re.split(r"(?<=[.!?])\s+|\n+", cleaned)
    result: list[str] = []
    for part in parts:
        part = part.strip()
        if not part or re.fullmatch(r"[#*\s\d.]+", part):
            continue
        if len(part) > 760:
            clauses = re.split(r"(?<=;)\s+", part)
            result.extend(item.strip() for item in clauses if item.strip())
        else:
            result.append(part)
    return result


def _is_structural_or_risky_block(text: str) -> bool:
    stripped = text.strip()
    return bool(
        not stripped
        or STRUCTURAL_RE.match(stripped)
        or stripped.startswith("<!-- Start of picture text -->")
        or (stripped.startswith("|") and stripped.endswith("|"))
    )


def _starts_as_continuation(text: str) -> bool:
    stripped = re.sub(r"^(?:[*_`#>\s]+)", "", text.strip())
    if not stripped:
        return False
    first_alpha = re.search(r"[A-Za-z]", stripped)
    return bool(
        LEADING_CONTINUATION_RE.match(stripped)
        or (first_alpha and stripped[first_alpha.start()].islower())
    )


def _ends_sentence(text: str) -> bool:
    return bool(TERMINAL_RE.search(text.strip()))


def _obviously_unresolved(text: str) -> bool:
    stripped = text.strip()
    dangling = re.search(r"\b(?:a|an|the|and|or|but|of|to|in|on|for|with|from|into|that|which|who|whose|in order)\s*$", stripped, re.IGNORECASE)
    return bool(_starts_as_continuation(stripped) or dangling or len(stripped.split()) > 12)


def _statement_fragments(chunk: dict[str, Any], source_order: int) -> list[ReconciledStatement]:
    text = chunk.get("selection_text", "")
    if _is_structural_or_risky_block(text):
        if text.strip().startswith("<!-- Start of picture text -->"):
            span = EvidenceSpan(chunk["chunk_id"], chunk["pdf_page"], text.strip(), 0, len(text.strip()))
            return [ReconciledStatement(text.strip(), (span,), source_order, True, "extraction_risk_block")]
        return []
    parts = split_statements(text)
    records: list[ReconciledStatement] = []
    cursor = 0
    for part in parts:
        start = text.find(part, cursor)
        if start < 0:
            start = 0
        end = start + len(part)
        cursor = end
        span = EvidenceSpan(chunk["chunk_id"], chunk["pdf_page"], part, start, end)
        records.append(ReconciledStatement(part, (span,), source_order, _ends_sentence(part)))
    return records


def normalize_technical_text(text: str) -> tuple[str, list[str]]:
    """Apply conservative, auditable extraction repairs without changing evidence."""
    value = text
    notes: list[str] = []
    reciprocal = re.compile(r"\(\s*_([A-Za-z][A-Za-z0-9_-]*)_\s*<u>(\d+(?:\.\d+)?)</u><sup>\)")
    if reciprocal.search(value) and "</sup>" in value:
        value = reciprocal.sub(lambda match: f"({match.group(2)} / {match.group(1)})", value, count=1)
        value = value.replace("</sup>", "", 1)
        notes.append("normalized_malformed_reciprocal_math")
    updated = re.sub(r"\b(Qwen\d+(?:\.\d+)?)Math-", r"\1-Math-", value)
    if updated != value:
        value = updated
        notes.append("normalized_model_name_hyphenation")
    updated = re.sub(r"\bselfexecution\b", "self-execution", value, flags=re.IGNORECASE)
    if updated != value:
        value = updated
        notes.append("normalized_compound_hyphenation")
    return canonical_text(value), notes


def reconcile_source_statements(chunks: list[dict[str, Any]], *, lookahead_chunks: int = 4) -> tuple[list[ReconciledStatement], list[ReconciledStatement]]:
    """Reconcile sentence fragments across chunks, batches, columns, and pages.

    A merge requires both a non-terminal left edge and an obvious grammatical
    continuation on the right. Intervening complete content is retained and is
    never absorbed. Unresolved fragments are returned separately so callers can
    fail safely instead of publishing them.
    """
    records = [record for index, chunk in enumerate(chunks) for record in _statement_fragments(chunk, index)]
    consumed: set[int] = set()
    merged: list[ReconciledStatement] = []
    unresolved: list[ReconciledStatement] = []
    for index, record in enumerate(records):
        if index in consumed:
            continue
        if record.complete or record.review_reason == "extraction_risk_block":
            normalized, notes = normalize_technical_text(record.text)
            merged.append(ReconciledStatement(normalized, record.evidence_spans, record.source_order, True, record.review_reason, tuple(notes)))
            continue
        candidate_index: int | None = None
        left_page = record.evidence_spans[-1].pdf_page
        for probe in range(index + 1, len(records)):
            candidate = records[probe]
            if candidate.source_order - record.source_order > lookahead_chunks:
                break
            if candidate.evidence_spans[0].pdf_page - left_page > 1:
                break
            if probe in consumed or candidate.review_reason == "extraction_risk_block":
                continue
            if _starts_as_continuation(candidate.text):
                candidate_index = probe
                break
        if candidate_index is None:
            if _obviously_unresolved(record.text):
                unresolved.append(ReconciledStatement(record.text, record.evidence_spans, record.source_order, False, "unresolved_trailing_fragment"))
            else:
                normalized, notes = normalize_technical_text(record.text)
                merged.append(ReconciledStatement(normalized, record.evidence_spans, record.source_order, True, "terminal_punctuation_absent", tuple(notes)))
            continue
        right = records[candidate_index]
        combined = canonical_text(f"{record.text} {right.text}")
        normalized, notes = normalize_technical_text(combined)
        complete = _ends_sentence(right.text)
        joined = ReconciledStatement(
            normalized,
            record.evidence_spans + right.evidence_spans,
            record.source_order,
            complete,
            None if complete else "unresolved_merged_fragment",
            tuple(notes),
        )
        consumed.add(candidate_index)
        if complete:
            merged.append(joined)
        else:
            unresolved.append(joined)
    merged.sort(key=lambda item: item.source_order)
    return merged, unresolved


def reconcile_model_claims(claims: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge only obvious adjacent model fragments; report anything unresolved."""
    result: list[dict[str, Any]] = []
    unresolved: list[str] = []
    index = 0
    while index < len(claims):
        claim = dict(claims[index])
        text = claim.get("claim_text", "").strip()
        if _ends_sentence(text) or not _obviously_unresolved(text):
            result.append(claim)
            index += 1
            continue
        if index + 1 >= len(claims) or not _starts_as_continuation(claims[index + 1].get("claim_text", "")):
            unresolved.append(claim.get("local_claim_id", str(index)))
            index += 1
            continue
        right = claims[index + 1]
        combined, notes = normalize_technical_text(f"{text} {right['claim_text']}")
        evidence = []
        seen_evidence: set[tuple[str, str]] = set()
        for item in claim.get("evidence", []) + right.get("evidence", []):
            key = (item["source_chunk_id"], item["short_quote"])
            if key not in seen_evidence:
                evidence.append(item)
                seen_evidence.add(key)
        claim.update({
            "claim_text": combined,
            "evidence": evidence,
            "numbers_and_units": _unique(list(claim.get("numbers_and_units", [])) + list(right.get("numbers_and_units", []))),
            "technical_terms": _unique(list(claim.get("technical_terms", [])) + list(right.get("technical_terms", []))),
            "limitation_or_uncertainty": claim.get("limitation_or_uncertainty") or right.get("limitation_or_uncertainty"),
            "normalization_notes": _unique(list(claim.get("normalization_notes", [])) + list(right.get("normalization_notes", [])) + notes + ["merged_model_fragments"]),
        })
        if not _ends_sentence(right.get("claim_text", "")):
            unresolved.append(claim.get("local_claim_id", str(index)))
        else:
            result.append(claim)
        index += 2
    return result, unresolved


def _short_quote(statement: str) -> str | None:
    words = list(re.finditer(r"\S+", statement))
    if len(words) < 3:
        return None
    return statement[words[0].start():words[min(11, len(words) - 1)].end()]


def source_fallback_claims(units: list[SourceUnit] | None = None, *, statements: list[ReconciledStatement] | None = None) -> list[dict[str, Any]]:
    """Create lossless, source-verbatim fallbacks independently of evaluation data.

    Model claims remain useful atomic rewrites, while these statements ensure that
    schema pressure or extraction misses cannot silently erase a nonempty source
    statement from the evidence inventory.
    """
    result: list[dict[str, Any]] = []
    counter = 0
    seen: set[tuple[str, str]] = set()
    if statements is None:
        statements = []
        for order, unit in enumerate(units or []):
            normalized_statements = split_statements(unit.text)
            for statement in normalized_statements:
                normalized, notes = normalize_technical_text(statement)
                span = EvidenceSpan(unit.source_chunk_id, unit.pdf_page, statement, 0, len(statement))
                statements.append(ReconciledStatement(normalized, (span,), order, _ends_sentence(statement), normalization_notes=tuple(notes)))
    for record in statements:
        statement = record.text
        if not record.complete:
            continue
        if record.review_reason == "extraction_risk_block":
            quote = _short_quote(statement) or statement[:120]
        else:
            quote = _short_quote(statement)
        if quote is None:
            continue
        key = ("|".join(span.source_chunk_id for span in record.evidence_spans), canonical_text(statement))
        if key in seen:
            continue
        seen.add(key)
        counter += 1
        numbers = number_candidates(statement)
        terms = term_candidates(statement)
        limitation = statement if LIMITATION_RE.search(statement) else None
        evidence = []
        for span in record.evidence_spans:
            span_quote = _short_quote(span.exact_text) or span.exact_text[:120]
            evidence.append({
                "source_chunk_id": span.source_chunk_id,
                "short_quote": span_quote,
                "exact_text": span.exact_text,
                "start_offset": span.start_offset,
                "end_offset": span.end_offset,
                "pdf_page": span.pdf_page,
            })
        risk_flags = []
        if "normalized_malformed_reciprocal_math" in record.normalization_notes:
            risk_flags.append("equation_or_symbol_risk")
        if record.review_reason == "extraction_risk_block":
            risk_flags.append("contains_picture_region")
        result.append({
            "local_claim_id": f"src-{counter:03d}",
            "claim_text": statement,
            "topic": " / ".join(terms[:2])[:60] or "source statement",
            "importance": "core" if numbers or limitation or terms else "supporting",
            "evidence": evidence,
            "numbers_and_units": numbers[:20],
            "technical_terms": terms[:20],
            "limitation_or_uncertainty": limitation,
            "extraction_method": "deterministic_source_fallback",
            "normalization_notes": list(record.normalization_notes),
            "content_risk_flags": risk_flags,
        })
    return result


def classify_claim_risk(
    claim: dict[str, Any],
    chunk_flags: dict[str, list[str]],
    chunk_text: dict[str, str],
    visually_verified_chunk_ids: set[str],
) -> dict[str, Any]:
    flags = _unique(
        list(claim.get("content_risk_flags", [])) + [flag
        for evidence in claim.get("evidence", [])
        for flag in chunk_flags.get(evidence["source_chunk_id"], [])
        ]
    )
    evidence_chunks = {item["source_chunk_id"] for item in claim.get("evidence", [])}
    figure_or_table = any(
        re.search(r"\b(?:figure|table)\s*\d*\s*:", chunk_text.get(chunk_id, ""), re.IGNORECASE)
        for chunk_id in evidence_chunks
    )
    picture_text = any("<!-- Start of picture text -->" in chunk_text.get(chunk_id, "") for chunk_id in evidence_chunks)
    risky_value = bool(claim.get("numbers_and_units")) and (
        figure_or_table or bool(set(flags) & {"contains_table", "contains_picture_region", "complex_table_suspected"})
    )
    math_risk = "equation_or_symbol_risk" in flags
    if (risky_value or math_risk) and evidence_chunks and evidence_chunks.issubset(visually_verified_chunk_ids):
        status = "visually_verified"
    elif risky_value or picture_text or math_risk:
        status = "human_review_required"
    else:
        status = "unreviewed"
    return {**claim, "content_risk_flags": flags, "review_status": status, "extraction_method": claim.get("extraction_method", "model")}


def completeness_metadata(units: list[SourceUnit], claims: list[dict[str, Any]]) -> dict[str, Any]:
    processed = _unique(unit.source_chunk_id for unit in units)
    with_claims = _unique(
        item["source_chunk_id"]
        for claim in claims
        for item in claim.get("evidence", [])
        if item["source_chunk_id"] in processed
    )
    without = [chunk_id for chunk_id in processed if chunk_id not in set(with_claims)]
    empty = {
        unit.source_chunk_id
        for unit in units
        if not canonical_text(unit.text)
    }
    return {
        "processed_chunk_ids": processed,
        "chunks_with_claims": with_claims,
        "chunks_without_claims": without,
        "skipped_chunk_ids": sorted(empty),
        "skipped_reasons": {chunk_id: "empty_source_text" for chunk_id in sorted(empty)},
        "extracted_number_candidates": _unique(
            value for unit in units for value in number_candidates(unit.text)
        ),
        "extracted_term_candidates": _unique(
            value for unit in units for value in term_candidates(unit.text)
        ),
        "limitation_candidates": _unique(
            value for unit in units for value in limitation_candidates(unit.text)
        ),
    }
