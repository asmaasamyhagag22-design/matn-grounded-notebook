"""V1 receipts are code-owned, immutable and validate their own aggregation."""
from __future__ import annotations

from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, model_validator

VERIFIER_VERSION = 'verification-rules-v2.1'
NORMALIZER_VERSION = 'english-decimal-scope-v2.0'
Verdict = Literal['pass', 'reject', 'unknown', 'not_run']
REASONS = frozenset('''quote_not_found invalid_evidence_span number_not_in_evidence
unsupported_statement attribution_mismatch hedge_mismatch evidence_hidden evidence_in_figure
spelled_number_mismatch source_not_selected stale_source evidence_not_citable separator_or_prefix
mixed_ocr_evidence unavailable_table_evidence code_text number_status_disallowed number_unlinked
scope_mismatch scope_unknown table_cell_required unsupported_numeric_form direction_mismatch
negation_mismatch modality_mismatch comparison_mismatch quantity_mismatch entity_binding_unknown
entailment_failed entailment_uncertain model_unavailable model_input_overflow model_output_invalid
invalid_request snapshot_invalid evidence_not_retrieved'''.split())


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)


class Citation(Contract):
    block_id: str
    start: int
    end: int
    quote: str | None = None


class Claim(Contract):
    text: str = Field(min_length=1)
    citations: tuple[Citation, ...]


class Request(Contract):
    sentence: str = Field(min_length=1)
    claims: tuple[Claim, ...]
    selected_doc_ids: tuple[str, ...]
    fingerprints: dict[str, str]
    retrieved_spans: tuple[Citation, ...] | None = None


class L4Record(Contract):
    protocol: Literal[1] = 1
    model_id: str
    revision: str
    file_hashes: dict[str, str]
    cutoff: Literal[0.5] = 0.5
    raw_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    tokens: int = Field(ge=1, le=512)
    seconds: float = Field(ge=0, allow_inf_nan=False)


class Check(Contract):
    target: str
    layer: Literal['L0', 'L1', 'L2', 'L3', 'L4']
    verdict: Verdict
    reasons: tuple[str, ...] = ()
    l4: L4Record | None = None

    @model_validator(mode='after')
    def closed_reasons(self):
        if any(r not in REASONS for r in self.reasons):
            raise ValueError('unknown receipt reason')
        if self.verdict == 'pass' and self.reasons:
            raise ValueError('passing check cannot have reject reasons')
        return self


class Evidence(Contract):
    block_id: str
    start: int
    end: int
    quote: str
    doc_id: str
    pdf_page_index: int
    page_label: str | None
    bbox: tuple[float, float, float, float]
    bbox_precision: str


def aggregate(checks):
    if any(c.verdict == 'reject' for c in checks):
        return 'rejected'
    if not checks or any(c.verdict != 'pass' for c in checks):
        return 'abstained'
    return 'verified'


class Receipt(Contract):
    schema_version: Literal[1] = 1
    verifier_version: Literal['verification-rules-v2.1'] = VERIFIER_VERSION
    normalizer_version: Literal['english-decimal-scope-v2.0'] = NORMALIZER_VERSION
    text_sha256: str
    request_sha256: str
    source_fingerprints: dict[str, str]
    checks: tuple[Check, ...]
    evidence: tuple[Evidence, ...]
    status: Literal['verified', 'rejected', 'abstained']

    @model_validator(mode='after')
    def validate_aggregation(self):
        if self.status != aggregate(self.checks):
            raise ValueError('receipt status disagrees with checks')
        if self.status == 'verified':
            targets = {c.target for c in self.checks}
            if 'sentence' not in targets or not any(t.startswith('claim:') for t in targets):
                raise ValueError('verified receipt has no final/atomic checks')
            for target in targets:
                if {c.layer for c in self.checks if c.target == target} != {'L0','L1','L2','L3','L4'}:
                    raise ValueError('verified receipt has incomplete layers')
        return self


class Entailment(Protocol):
    """Future trusted adapter; receives only already-resolved eligible evidence."""
    def check(self, text: str, evidence: tuple[Evidence, ...], target: str) -> Check: ...


class NotRunEntailment:
    def check(self, text, evidence, target):
        return Check(target=target, layer='L4', verdict='not_run', reasons=('model_unavailable',))
