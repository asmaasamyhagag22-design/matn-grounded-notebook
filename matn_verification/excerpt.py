"""Source fidelity only: exact, bounded, contextual prose copied by Chat code.

This receipt deliberately is NOT a semantic Receipt. Numeric ledgers and L4
entailment authorize generated claims; they cannot disprove source text existing.
Relevance, answer completeness and any surrounding interpretation remain unproved.
"""
import hashlib
from typing import Literal

from pydantic import model_validator

from matn_rag.contracts import canonical
from .prose import sentence_spans, unresolved_opening
from .contracts import Contract, Request, Check, Evidence, aggregate
from . import rules, meaning
from .scope import source_units

VERSION = 'source-fidelity-grounded-v5'


class ExcerptReceipt(Contract):
    schema_version: Literal[1] = 1
    verifier_version: Literal['source-fidelity-grounded-v5'] = VERSION
    verification_scope: Literal['source_fidelity_only'] = 'source_fidelity_only'
    semantic_support: Literal['not_evaluated'] = 'not_evaluated'
    relevance: Literal['not_established'] = 'not_established'
    answer_completeness: Literal['unestablished'] = 'unestablished'
    text_sha256: str
    request_sha256: str
    source_fingerprints: dict[str, str]
    checks: tuple[Check, ...]
    evidence: tuple[Evidence, ...]
    status: Literal['verified', 'rejected', 'abstained']

    @model_validator(mode='after')
    def valid_status(self):
        if self.status != aggregate(self.checks):
            raise ValueError('excerpt receipt status disagrees with checks')
        return self


def verify_excerpt(documents, request, entailment=None):
    """Never called for generator output; exactness alone is not semantic support.

    One block, 1–4 complete consecutive sentences. No flattened unions, tables,
    normalization equivalence, cropped condition, or unresolved opening subject.
    Shared L0 retains selection, snapshot, eligibility and retrieval provenance.
    """
    docs = tuple(documents)
    fps = {d.doc_id: rules.fingerprint(d) for d in docs}
    checks = []; evidence = []
    data = canonical(request)
    text = request.get('sentence', '') if isinstance(request, dict) else ''
    try:
        req = Request.model_validate_json(data)
        if len(req.claims) != 1 or req.claims[0].text != req.sentence:
            raise ValueError('excerpt has no generated interpretation')
        refs = req.claims[0].citations
        l0, entries = rules._resolve(docs, req, refs, 'source_excerpt', fps)
        checks.append(l0)
        if l0.verdict == 'pass':
            exact = len(entries) == 1
            if exact:
                d, e, ref, quote = entries[0]
                spans = sentence_spans(e.block.text)
                selected = [s for s in spans if ref.start <= s.start and s.end <= ref.end]
                # No source-prefix deletion, including unresolved openings:
                # the omitted prefix might scope every following sentence.
                opening = 0
                exact = (text == quote and len(text) <= 900
                         and 1 <= len(selected) <= 4
                         and opening < len(spans) and ref.start == spans[opening].start
                         and ref.start == selected[0].start and ref.end == selected[-1].end
                         and all(e.block.text[s.start:s.end].rstrip().rstrip(')').endswith(('.', '!', '?', '."', '.”')) for s in selected)
                         and e.role != 'table' and rules._value(e.block.block_type) != 'table'
                         and not unresolved_opening(text))
                # Do not leave a later complete sentence (e.g. a contrasting
                # recursive rule) behind merely to fit the quote budget.
                exact = exact and not any(s.start >= ref.end and
                    e.block.text[s.start:s.end].rstrip().rstrip(')').endswith(('.', '!', '?', '."', '.”'))
                    for s in spans)
                # Explicit adjacent qualifiers are required even outside the quote.
                exact = exact and all(q.strip() in text and (not dep or dep in text)
                                      for q, dep in source_units(docs, refs))
                evidence.append(Evidence(block_id=ref.block_id, start=ref.start, end=ref.end,
                    quote=quote, doc_id=d.doc_id, pdf_page_index=e.block.page_index,
                    page_label=e.block.page_label, bbox=e.bbox.coordinates,
                    bbox_precision=e.bbox.bbox_precision))
            checks.append(rules._check('source_excerpt', 'L0', 'pass' if exact else 'unknown',
                                      () if exact else ('scope_unknown',)))
    except (ValueError, KeyError, TypeError):
        checks.append(rules._check('source_excerpt', 'L0', 'unknown', ('invalid_request',)))
    return ExcerptReceipt(text_sha256=hashlib.sha256(str(text).encode()).hexdigest(),
        request_sha256=hashlib.sha256(data).hexdigest(), source_fingerprints=fps,
        checks=tuple(checks), evidence=tuple(evidence), status=aggregate(checks))
