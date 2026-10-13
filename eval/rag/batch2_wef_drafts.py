"""Offline WEF draft recheck and replacement packet; no freeze or retrieval."""
import argparse
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

from matn_contracts.structure import DocumentStructure
from .prepare_drafts import draw_order
from .question_tools import locate, question_checks

STRUCTURE = Path('out/r-lite-3/closure/production/wef-future-of-jobs-2025/05_document.json')
ORIGINAL = Path('out/rag-core/wef-question-drafts.json')
ROOT = Path('out/batch2/completion/wef')


def save(name, value):
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                       sort_keys=True, allow_nan=False) + '\n')


def inventory():
    d = DocumentStructure.model_validate_json(STRUCTURE.read_bytes())
    assert d.producer_versions['document'] == 'r-lite-3'
    by = {e.block.block_id: e for e in d.elements}
    available = {b for t in d.tables if t.structure == 'available' and t.cells for b in t.block_ids}
    mixed = {p.pdf_page_index for p in d.pages if p.route == 'mixed'}

    def reasons(span):
        e = by.get(span['block_id'])
        if e is None:
            return ['missing target block']
        r = []
        if not e.citable:
            r.append('non-citable/' + e.role)
        if e.role == 'table' and e.block.block_id not in available:
            r.append('L3-15/L3-17 unavailable table')
        if e.block.page_index in mixed and e.block.route.value != 'text_layer':
            r.append('L3-03/L3-12 mixed-route OCR')
        if not 0 <= span['start'] < span['end'] <= len(e.block.text):
            r.append('invalid target offsets')
        return r

    def relevant(text, spans):
        # Bind the quote to its own target blocks, not a repeated quote elsewhere.
        candidates = tuple(c for c in d.chunks if all(
            any(s.block_id == t['block_id'] and s.start <= t['start'] and s.end >= t['end']
                for s in c.primary) for t in spans))
        ids, _ = locate(SimpleNamespace(chunks=candidates), text)
        return ids

    kept, drops = [], []
    old = json.loads(ORIGINAL.read_text())
    for original in old['items']:
        q = copy.deepcopy(original)
        why = sorted({r for s in q['target_spans'] for r in reasons(s)})
        ids = relevant(q['target_text'], q['target_spans']) if not why else []
        if not ids and not why:
            why = ['no exact quote in a chunk covering the original target spans']
        if why:
            drops.append({'id': q['id'], 'question': q['question'],
                          'original_target_spans': q['target_spans'],
                          'reachable': False, 'action': 'dropped, never rewritten', 'reasons': why})
            continue
        q['relevant_chunk_ids'] = ids
        q['reachable'] = True
        for s in q['target_spans']:
            s['primary_chunk_id'] = ids[0]
        q['question_kind'] = 'kp'
        q['scope_number_roles'] = [{'token': x, 'role': 'scope'} for x in q['scope_numbers']]
        q['provenance'] = 'drafted by model family A'
        kept.append(q)
    draws = draw_order(d)
    for draw in draws:
        for sentence in draw['sentences']:
            spans = sentence['target_spans']
            sentence['eligibility_reasons'] = sorted({r for s in spans for r in reasons(s)})
            sentence['eligible'] = bool(spans) and not sentence['eligibility_reasons']
            if sentence['eligible']:
                sentence['eligible'] = bool(relevant(sentence['text'], spans))
    return d, by, old, kept, drops, draws, relevant


def run(selection=None):
    d, by, old, kept, drops, draws, relevant = inventory()
    if selection is None:
        save('recheck.json', {'structure_sha256': hashlib.sha256(STRUCTURE.read_bytes()).hexdigest(),
                             'original_sha256': hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(),
                             'kept': kept, 'drops': drops,
                             'kept_thirds': dict(Counter(q['stratum']['page_third'] for q in kept)),
                             'original_thirds': dict(Counter(q['stratum']['page_third'] for q in old['items'])),
                             'kind_interpretation': 'original forty questions are qualitative kp; no explicit old kp/kn fields'})
        save('draw-order.json', draws)
        return
    choices = json.loads(selection.read_text())
    assert [c['draw_index'] for c in choices] == list(range(len(choices))), 'DRAW_ORDER_GAP_OR_REORDER'
    new, skips = [], []
    used = {(s['block_id'], s['start'], s['end']) for q in kept for s in q['target_spans']}
    for choice in choices:
        draw = draws[choice['draw_index']]
        if 'skip_reason' in choice:
            skips.append({'draw_index': draw['draw_index'], 'chunk_id': draw['chunk_id'],
                          'third': draw['third'], 'reason': choice['skip_reason']})
            continue
        sentence = draw['sentences'][choice['sentence_index']]
        assert sentence['eligible'], 'INELIGIBLE_TARGET'
        spans = copy.deepcopy(sentence['target_spans'])
        assert not any((s['block_id'], s['start'], s['end']) in used for s in spans), 'DUPLICATE_TARGET'
        question = choice['question']
        assert not re.search(r'world economic forum|future of jobs|\bpage\s+\d', question, re.I), 'DOCUMENT_OR_PUBLISHER_NAME'
        checks = question_checks(question, sentence['text'])
        assert not checks['shared_content_4grams'], 'QUESTION_4GRAM'
        assert checks['scope_numbers'] == choice.get('scope_numbers', []), 'UNMARKED_SCOPE_NUMBER'
        ids = relevant(sentence['text'], spans)
        assert ids, 'TARGET_UNREACHABLE'
        for s in spans:
            b = by[s['block_id']].block
            s.update(pdf_page_index=b.page_index, page_label=b.page_label, bbox=list(b.bbox),
                     primary_chunk_id=ids[0])
            used.add((s['block_id'], s['start'], s['end']))
        new.append({'id': f'wef-batch2-kp-{len(new)+1:02}', 'source': 'wef-future-of-jobs-2025',
                    'question': question, 'question_kind': 'kp', 'target_text': sentence['text'],
                    'target_spans': spans, 'relevant_chunk_ids': ids, 'reachable': True,
                    'draw_index': draw['draw_index'],
                    'stratum': {'page_third': draw['third'], 'kind': draw['kind']},
                    'target_sentence': {'draw_chunk_id': draw['chunk_id'],
                                        'sentence_index': sentence['sentence_index'],
                                        'start': sentence['chunk_start'], 'end': sentence['chunk_end']},
                    **checks, 'scope_number_roles': [{'token': x, 'role': 'scope'} for x in checks['scope_numbers']],
                    'provenance': 'drafted by model family A', 'state': 'draft', 'split': None})
    rows = kept + new
    assert len(rows) == 40, f'WEF_DRAFT_COUNT:{len(rows)}'
    assert Counter(q['stratum']['page_third'] for q in rows) == Counter(
        q['stratum']['page_third'] for q in old['items']), 'THIRD_QUOTA_CHANGED'
    for q in rows:
        assert not question_checks(q['question'], q['target_text'])['shared_content_4grams']
    result = {'schema': 'matn-rag-question-drafts/1', 'state': 'draft-not-frozen', 'seed': old['seed'],
              'structure_sha256': hashlib.sha256(STRUCTURE.read_bytes()).hexdigest(),
              'provenance': 'drafted by model family A', 'items': rows, 'skips': skips}
    save('drafts.json', result)
    save('drop-ledger.json', {'drops': drops, 'kept': len(kept), 'replacements': len(new),
                              'total': len(rows), 'thirds': dict(Counter(q['stratum']['page_third'] for q in rows)),
                              'question_kinds': dict(Counter(q['question_kind'] for q in rows)),
                              'screen': 'PENDING; lexical checks do not establish semantic leakage or answerability'})
    lines = ['# WEF screening packet — 40 drafts, NOT FROZEN', '',
             'Provenance: "drafted by model family A". Cross-family/owner review PENDING; no reviewer contacted.', '',
             'Targets use current r-lite-3. L3-03/12 mixed OCR and L3-15/17 unavailable tables excluded.', '',
             'Screen criterion: a question must not contain the target conclusion, items, direction or cause; topic/dimension may be named.', '',
             'Rejected items are dropped, never rewritten. Prefixes and neighboring entity blocks are not evidence.', '']
    for i, q in enumerate(rows, 1):
        roles = [by[s['block_id']].role for s in q['target_spans']]
        lines += [f'### {i:02}. {q["id"]}', '',
                  f'Source: `{q["source"]}`; reachable: true; PDF page indexes (zero-based): ' +
                  str(sorted({s['pdf_page_index'] for s in q['target_spans']})) + '.', '',
                  'Question: ' + q['question'], '', 'Exact target:', '```text', q['target_text'], '```', '',
                  f'Scope numbers: `{q["scope_numbers"]}`; roles: `{roles}`; kind: kp.', '',
                  'Target block spans: `' + json.dumps(q['target_spans'], ensure_ascii=False) + '`.', '',
                  'Existing verdict: none. Cross-family verdict: PENDING. Owner verdict: PENDING.', '']
    (ROOT / 'screening-packet.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--selection', type=Path)
    run(parser.parse_args().selection)
