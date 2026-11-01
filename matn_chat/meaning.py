"""Bounded source-context catalog. Added evidence is explicit, never a new quote.

Only eligible primary source intervals can be added. Headings/titles are not
silently promoted; table associations are metadata with exact source locators.
"""
from copy import deepcopy
from matn_reading.structure.sentences import sentence_spans
from matn_verification.contracts import Citation
from matn_verification.rules import eligibility, interval_covered
from matn_verification.meaning import continuous
from .handles import build_handles

VERSION = 'context-catalog-v1'
MAX_ADDED_CHARACTERS = 1600


def build_meaning_handles(documents, hits):
    docs = tuple(documents); expanded = deepcopy(hits); budget = MAX_ADDED_CHARACTERS
    by = {e.block.block_id: (d, i, e) for d in docs for i, e in enumerate(d.elements)}
    added = []
    for hit in expanded:
        for locator in list(hit['evidence']):
            if locator['kind'] != 'pdf_block_span': continue
            p = locator['payload']; d, i, e = by[p['block_id']]
            if eligibility(d, e): continue
            primary = [s for c in d.chunks for s in c.primary]
            sentences = sentence_spans(e.block.text)
            overlapping = [j for j, s in enumerate(sentences) if s.start < p['end'] and p['start'] < s.end]
            if not overlapping: continue
            candidates = [(e, sentences[j], 'sentence_completion') for j in overlapping]
            if min(overlapping) > 0:
                candidates.append((e, sentences[min(overlapping)-1], 'previous_sentence'))
            # At most one adjacent source block, only genuine unfinished prose.
            for j in (i-1, i+1):
                if not 0 <= j < len(d.elements): continue
                other = d.elements[j]
                pair = [other, e] if j < i else [e, other]
                refs = [Citation(block_id=x.block.block_id, start=0, end=len(x.block.text)) for x in pair if x.block.text]
                if len(refs) != 2 or not continuous((d,), refs): continue
                if pair[0].block.text.rstrip().endswith(('.', '!', '?', ';', ':')): continue
                if not pair[1].block.text[:1].islower(): continue
                spans = sentence_spans(other.block.text)
                candidates.append((other, spans[-1] if j < i else spans[0], 'source_continuation'))
            for element, s, reason in candidates:
                ref = Citation(block_id=element.block.block_id, start=s.start, end=s.end)
                if eligibility(d, element) or not interval_covered(ref, primary): continue
                existing = [Citation(**{k: x['payload'][k] for k in ('block_id', 'start', 'end')})
                            for x in hit['evidence'] if x['kind'] == 'pdf_block_span']
                if interval_covered(ref, existing): continue
                size = s.end-s.start
                if size > budget: continue
                budget -= size
                payload = dict(p, block_id=ref.block_id, start=ref.start, end=ref.end)
                hit['evidence'].append({'kind': 'pdf_block_span', 'payload': payload})
                added.append(dict(block_id=ref.block_id, start=ref.start, end=ref.end, reason=reason))
    handles = build_handles(docs, expanded)
    for handle in handles.values():
        handle['catalog_version'] = VERSION
        handle['context_additions'] = [a for a in added if any(a['block_id'] == c['block_id'] and a['start'] < c['end'] and c['start'] < a['end'] for c in handle['citations'])]
        # Available tables retain cells/headers/grid and primary locators. This
        # metadata is orientation only; prose synthesis is not source evidence.
        handle['table_context'] = []
        ids = {c['block_id'] for c in handle['citations']}
        for d in docs:
            for table in d.tables:
                if table.structure != 'available' or not ids.intersection(table.block_ids): continue
                handle['table_context'].append(dict(table_id=table.table_id, header_rows=list(table.header_rows),
                    cells=[dict(row=c.row, col=c.col, row_span=c.row_span, col_span=c.col_span,
                        is_header=c.is_header, text=c.text,
                        source_spans=[s.model_dump(mode='json') for s in c.source_spans]) for c in table.cells]))
    return handles


# Opt-in engine shares the first-pass/redraft implementation without modifying
# its historical fingerprint or any production globals.
from types import FunctionType
from .generation import payload as _payload
import json


def meaning_payload(question, handles, failures=None, *, num_ctx=16384):
    body = _payload(question, handles, failures, num_ctx=num_ctx)
    # Separate segment boundaries in the prompt; source locators stay code owned.
    context = {key: {'source_segments': [c['quote'] for c in h['citations']],
                     'table_orientation': h.get('table_context', [])}
               for key, h in handles.items() if len(h['citations']) > 1 or h.get('table_context')}
    # Table cell locators are metadata, never model-written citation addresses.
    for row in context.values():
        row['table_orientation'] = [
            {'header_rows': t['header_rows'], 'cells': [
                {k: c[k] for k in ('row','col','row_span','col_span','is_header','text')}
                for c in t['cells']]} for t in row['table_orientation']]
    body['prompt'] += ('\nSource segment boundaries (do not invent links across gaps). '
        'Table orientation is metadata, not an additional source quote; cite original handles. '
        'Unresolved antecedents, units, periods or headers require abstention.\n'
        + json.dumps(context, ensure_ascii=False, separators=(',', ':')))
    return body


from . import engine as _engine
from matn_verification.meaning import verify_meaning


class MeaningChatEngine(_engine.ChatEngine):
    ask = FunctionType(_engine.ChatEngine.ask.__code__,
                       {**vars(_engine), 'build_handles': build_meaning_handles})
    _generate = FunctionType(_engine.ChatEngine._generate.__code__,
                             {**vars(_engine), 'payload': meaning_payload})
    _verify = FunctionType(_engine.ChatEngine._verify.__code__,
                           {**vars(_engine), 'verify': verify_meaning})
