"""Opt-in useful Chat with a per-displayed-unit scope veto and one redraft.

Historical engines/defaults stay unchanged. Excerpts are labelled evidence with
unknown answer completeness, not synthesized answers or a relevance guarantee.
"""
from types import FunctionType
from matn_verification.prose import sentence_spans, unresolved_opening
from matn_verification.excerpt import verify_excerpt
from matn_verification.contracts import Citation
from matn_verification.meaning import UNRESOLVED
from matn_verification.rules import interval_covered
from .generation import payload as base_payload

from . import engine
from . import handles as handle_module, meaning as catalog_module
from .meaning import meaning_payload
from .evidence_selection import select_handles, score
from .question_scope import question_scope

_symbol_handles = FunctionType(handle_module.build_handles.__code__,
    {**vars(handle_module), 'sentence_spans': sentence_spans})
build_meaning_handles = FunctionType(catalog_module.build_meaning_handles.__code__,
    {**vars(catalog_module), 'sentence_spans': sentence_spans, 'build_handles': _symbol_handles})
from matn_verification.scope import verify_scope, source_units

CONFIGURATION = 'grounded-chat-v5-final'

# Only a known, source-repairable failure gets the single existing redraft.
REPAIRABLE = {'scope_unknown', 'entity_binding_unknown', 'attribution_mismatch',
              'modality_mismatch', 'negation_mismatch', 'hedge_mismatch',
              'entailment_failed', 'entailment_uncertain', 'unsupported_statement'}


def preserved_payload(question, handles, failures=None, *, num_ctx=16384):
    # Reuse the existing source catalog once. Multi-span segment boundaries and
    # table orientation still come from the existing meaning payload when needed.
    contextual = any(len(h['citations']) > 1 or h.get('table_context') for h in handles.values())
    body = (meaning_payload if contextual else base_payload)(question, handles, failures, num_ctx=num_ctx)
    body['prompt'] = body['prompt'].replace(
        'Each output sentence is ONE short atomic claim, with 1 to 3 sentence handles. ',
        'Each output item is one meaning unit, with 1 to 3 handles. Keep a rule and '
        'all its conditions and exceptions in the SAME item; a short linked pair '
        'of sentences is allowed. Preserve if versus only if. ')
    body['prompt'] += '\nPut handle IDs only in the handles array, never in the text. Copy the relevant complete source rule with its conditions when possible. Keep every source option label in order in every item about those options; never infer aliases or turn a user instruction into a program action; a later quote or the question cannot supply a missing mode.\n'
    return body


class PreservedChatEngine(engine.ChatEngine):
    def _scope_verify(self,documents,request,adapter):
        return verify_scope(documents,request,adapter)

    _select_handles = staticmethod(select_handles)
    _ask = FunctionType(engine.ChatEngine.ask.__code__,
                        {**vars(engine), 'build_handles':build_meaning_handles})
    _generate_once = FunctionType(engine.ChatEngine._generate.__code__,
                             {**vars(engine), 'payload':preserved_payload})
    def _verify(self, sentences, entry, documents, timings, receipts):
        from matn_verification.scope import unit_witness, option_scope, canon
        from matn_verification.contracts import Citation
        by = {e.block.block_id: (d, e) for d in documents for e in d.elements}
        def entries(refs):
            return [(by[r['block_id']][0], by[r['block_id']][1], Citation(**r),
                     by[r['block_id']][1].block.text[r['start']:r['end']])
                    for r in refs if r['block_id'] in by]
        def verify_with_context(docs, req, adapter):
            entry.setdefault('verification_requests', []).append(dict(
                declared=req, effective=req, context_retrieval=[],
                context_policy='declared_source_spans_only'))
            result = self._scope_verify(docs, req, adapter)
            scope = question_scope(getattr(self, 'active_question', ''),
                [q for claim in req['claims'] for _, _, _, q in entries(claim['citations'])])
            entry['verification_requests'][-1]['question_scope'] = scope
            if not scope['passed']:
                from matn_verification.rules import _check, aggregate
                checks = result.checks + (_check('sentence', 'L3', 'unknown', ('scope_unknown',)),)
                result = result.model_copy(update={'checks': checks, 'status': aggregate(checks)})
            return result
        verify = FunctionType(engine.ChatEngine._verify.__code__,
                              {**vars(engine), 'verify': verify_with_context})
        resolved = verify(self, sentences, entry, documents, timings, receipts)
        for position, (item, index) in enumerate(resolved):
            item['declared_citations'] = list(item['citations'])
            effective = entry['verification_requests'][position]['effective']
            refs = effective['claims'][0]['citations']
            proof = unit_witness(item['text'], entries(refs)) if not item['unknown_handles'] else None
            source_scope_kept = (option_scope(item['text'], entries(refs))[0] and
                all(not dep or canon(dep) in canon(item['text'])
                    for _, dep in source_units(documents, [Citation(**r) for r in refs])))
            l0_ok = all(c['verdict'] == 'pass' for c in item['receipt']['checks'] if c['layer'] == 'L0')
            item['failure_class'] = ('retrieval_required' if not l0_ok else
                'verifier_limit' if proof and source_scope_kept and item['receipt']['status'] != 'verified'
                else 'generation_repairable')
            if proof and item['receipt']['status'] == 'verified':
                supported = []
                for d, e, r, q in proof:
                    supported.append(dict(block_id=r.block_id, start=r.start, end=r.end, quote=q,
                        doc_id=d.doc_id, pdf_page_index=e.block.page_index, page_label=e.block.page_label,
                        bbox=list(e.bbox.coordinates), bbox_precision=e.bbox.bbox_precision))
                item['citations'] = supported
                item['citation_binding'] = 'bounded_source_witness'
        return resolved

    def _generate(self, question, failures, timings):
        if failures is not None:
            # The engine zips returned repairs to slots; skip the whole call only
            # when every failed slot has positive evidence of a verifier limit.
            previous = self.trace[-1].get('sentences', []) if self.trace else []
            if failures and all(f['slot'] < len(previous) and
                    previous[f['slot']].get('failure_class') == 'verifier_limit' for f in failures):
                entry = dict(attempt=len(self.trace), kind='repair_skipped',
                    reason='proved_source_form_verifier_limit', failures=failures,
                    sentences=[], timings={'verification_seconds': 0.})
                self.trace.append(entry)
                return [], entry
        if failures is not None and not all(
                f['failure_codes'] and set(f['failure_codes']) <= REPAIRABLE for f in failures):
            entry = {'attempt': len(self.trace), 'kind': 'repair_skipped',
                     'reason': 'failure_not_source_repairable', 'failures': failures,
                     'sentences': [], 'timings': {'verification_seconds': 0.}}
            self.trace.append(entry)
            return [], entry
        before = self.handles
        self.handles = self._select_handles(question, before)
        audit = dict(kind='catalog_selection', before_handles=len(before), after_handles=len(self.handles),
                     before_characters=sum(len(h['text']) for h in before.values()),
                     after_characters=sum(len(h['text']) for h in self.handles.values()),
                     retained=list(self.handles), relevance='heuristic_not_proof')
        scope = question_scope(question, [h['text'] for h in self.handles.values()])
        if not scope['passed']:
            entry = dict(attempt=len(self.trace), kind='question_scope_unavailable',
                question_scope=scope, catalog_selection=audit, sentences=[],
                parsed={'sentences': []}, timings={'verification_seconds': 0.})
            self.trace.append(entry)
            return [], entry
        result = self._generate_once(question, failures, timings)
        result[1]['catalog_selection'] = audit
        return result

    def _excerpt(self, question, documents, result):
        candidates = []
        # A failed draft supplies candidate source addresses, never quote text.
        # Do not replace a blocked answer with a different, merely similar topic.
        failed_blocks = {c['block_id'] for t in self.trace
                         if t.get('kind') != 'excerpt_fallback'
                         for item in t.get('sentences', [])
                         if item.get('receipt', {}).get('status') != 'verified'
                         for c in item.get('citations', [])}
        # Code constructs the quote from original source ranges, never draft text.
        # Keep paragraph context rather than lifting an exception sentence alone.
        for d in documents:
            for e in d.elements:
                if e.block.block_id not in failed_blocks: continue
                refs = [Citation(**{k: c[k] for k in ('block_id','start','end')})
                        for handle in self.handles.values() for c in handle['citations']
                        if c['block_id'] == e.block.block_id]
                spans = sentence_spans(e.block.text)
                if not refs or not spans: continue
                if unresolved_opening(e.block.text[spans[0].start:spans[0].end]): continue
                opening = 0
                for end in range(opening, min(len(spans), opening+4)):
                    ref = Citation(block_id=e.block.block_id, start=spans[opening].start, end=spans[end].end)
                    if not interval_covered(ref, refs): continue
                    text = e.block.text[ref.start:ref.end]
                    if not all(e.block.text[s.start:s.end].rstrip().rstrip(')').endswith(('.', '!', '?', '."', '.”'))
                               for s in spans[opening:end+1]): continue
                    if any(e.block.text[s.start:s.end].rstrip().rstrip(')').endswith(('.', '!', '?', '."', '.”'))
                           for s in spans[end+1:]): continue
                    overlap = score(question, text, [x.block.text for doc in documents for x in doc.elements])
                    if overlap < 2 or len(text) > 900: continue
                    if not question_scope(question, [text])['passed']: continue
                    if any(dep and dep not in text for _, dep in source_units(documents, [ref])): continue
                    # Prefer more query terms, then fuller bounded context.
                    candidates.append((-overlap, -len(text), e.block.block_id, d, e, ref, text))
        if not candidates: return
        _, _, _, d, e, ref, text = min(candidates, key=lambda x: x[:3])
        citation = dict(block_id=ref.block_id, start=ref.start, end=ref.end, quote=text,
                        doc_id=d.doc_id, pdf_page_index=e.block.page_index, page_label=e.block.page_label,
                        bbox=list(e.bbox.coordinates), bbox_precision=e.bbox.bbox_precision)
        retrieved = [{k:c[k] for k in ('block_id','start','end')}
                     for h in self.handles.values() for c in h['citations']]
        req = dict(sentence=text, claims=[dict(text=text, citations=[{k:citation[k] for k in ('block_id','start','end','quote')}])],
                   selected_doc_ids=[d.doc_id for d in documents], fingerprints=self.fingerprints,
                   retrieved_spans=retrieved)
        start = self.clock()
        receipt = verify_excerpt(documents, req).model_dump(mode='json')
        seconds = self.clock()-start
        result['timings']['verification_seconds'] += seconds
        entry = {'attempt':len(self.trace), 'kind':'excerpt_fallback', 'sentences':[],
                 'timings':{'verification_seconds':seconds}, 'request':req}
        self.trace.append(entry)
        reasons = sorted({r for c in receipt['checks'] for r in c['reasons']})
        item = dict(text=text, handles=[], citations=[citation], receipt=receipt,
                    reasons=reasons, first_failure=engine.first_failure(receipt), unknown_handles=[])
        entry['sentences'].append(item)
        index = len(result['receipts'])
        result['receipts'].append(dict(attempt=entry['attempt'], sentence_index=0, handles=[],
                                       first_failure=item['first_failure'], receipt=receipt))
        if receipt['status'] == 'verified':
            result['sentences'].append(dict(text=text, handles=[], citations=[citation],
                receipt_index=index, kind='source_excerpt', verification_scope='source_fidelity_only',
                semantic_support='not_evaluated', answer_completeness='unestablished'))

    def ask(self, notebook, sources, question):
        start = self.clock()
        self.active_question = question
        result = self._ask(notebook, sources, question)
        result['configuration'] = CONFIGURATION
        if not result['error'] and result['state'] != 'deferred_memory':
            rows = [r for r in self.search.repo.source_rows(notebook) if r['id'] in sources]
            ids = {r['doc_id'] for r in rows}
            documents = tuple(d for d in self.documents if d.doc_id in ids)
            # Already verified units never depend on draft siblings. Each failed
            # slot got the existing single redraft before this bounded fallback.
            # A deliberate empty answer is abstention, not permission to display
            # a merely similar quote (especially for out-of-source questions).
            drafted = any(t.get('parsed', {}).get('sentences') for t in self.trace)
            if drafted and (not result['sentences'] or result['dropped_sentences']):
                try:self._excerpt(question, documents, result)
                finally:
                    if self.owns_entailment:self.entailment.close()
            excerpt = any(s.get('kind') == 'source_excerpt' for s in result['sentences'])
            if result['sentences'] and (excerpt or result['dropped_sentences']):
                result['state'] = 'partial_answer'
                result['message'] = ('Source excerpt: exact source text and context checked; semantic support, relevance and answer completeness not established.'
                                     if excerpt else 'Partial answer: some draft content could not be verified.')
            result['answer_completeness'] = 'unestablished'
        result['timings']['total_seconds'] = self.clock()-start
        return result
