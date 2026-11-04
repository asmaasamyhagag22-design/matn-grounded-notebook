"""Answers v2 verdict from one saved measurement plus a cross-family AI review.

The rule is docs/answers-acceptance-v2.md, registered before the run. This
script never re-asks a question. It computes the fixed gates, queues every
displayed answer sentence for owner labels (group answers-v2) and registers
the verdict basis, so owner labels can later recompute the quality gates.
"""
import argparse
import json
from pathlib import Path
from statistics import median

from matn_app.answer_engine import copied_prose
from matn_app.labels import LabelStore
from matn_app.store import read, write

GROUP = 'answers-v2'
BLOCKED = 'answers-v2-blocked'


def blocked_items(rows, questions, blocks):
    """Rejected generated drafts, for an owner false-block rate; never in the verdict."""
    items = []
    for row in rows:
        folder = row['job'].get('folder')
        if not folder:
            continue
        for path in sorted(Path(folder).rglob('answer-receipts.json')):
            for entry in json.loads(path.read_bytes())['trace']:
                for n, sentence in enumerate(entry.get('sentences', [])):
                    if sentence['receipt'].get('status') == 'verified' or not sentence.get('citations'):
                        continue
                    ref = sentence['citations'][0]
                    items.append(dict(id=f"answers-v2-blocked-{row['id']}-{'coverage' if 'coverage-attempt' in path.parts else 'answer'}-{entry['attempt']}-{n}",
                                      group=BLOCKED, text=sentence['text'], question=questions[row['id']]['question'],
                                      source_title=None, source_type='public PDF', span=ref, spans=sentence['citations'],
                                      context=blocks.get(ref.get('block_id'), ref.get('quote', '')), receipt=sentence['receipt'],
                                      ai_verdict=dict(verifier='blocked', reasons=sentence.get('reasons'),
                                                      reason='Rejected by verification; label Correct if it was a false block')))
    return items


def displayed(result):
    return [c for c in result.get('citations', []) if c.get('kind') == 'generated_verified_unit' and c.get('status') == 'verified']


def excerpt_failures(row):
    """UI/data test: the reply is generated sentences only, none a source copy."""
    result = row['result']
    refs = displayed(result)
    problems = []
    for ref in refs:
        quotes = {str(i): dict(text=s.get('quote', '')) for i, s in enumerate(ref.get('spans') or [ref.get('span') or {}])}
        if copied_prose(ref['text'], quotes):
            problems.append(dict(id=row['id'], sentence=ref['id'], reason='source_copy'))
    expected = '\n\n'.join(ref['text'] + ' [' + ref['id'] + ']' for ref in refs)
    if refs and result.get('text') != expected:
        problems.append(dict(id=row['id'], reason='reply_text_is_not_only_generated_sentences'))
    if any(c.get('kind') != 'generated_verified_unit' for c in result.get('citations', [])):
        problems.append(dict(id=row['id'], reason='non_generated_citation_in_reply'))
    return problems


def evaluate(config, measurement, review, documents):
    questions = {q['id']: q for q in json.loads(Path(config).read_bytes())['questions']}
    rows = json.loads(Path(measurement).read_bytes())['results']
    ai = json.loads(Path(review).read_bytes())
    blocks = {}
    for path in documents:
        for e in json.loads(Path(path).read_bytes())['elements']:
            blocks[e['block']['block_id']] = e['block']['text']
    answerable = [q for q in questions.values() if q['answer_type'] != 'not in sources']
    direct, not_covered, errors, borderline, excerpts, items, first = {}, {}, [], [], [], [], {}
    chat_errors = []
    for row in rows:
        q = questions[row['id']]
        result = row['result']
        refs = displayed(result)
        verdict = ai[row['id']]
        # Any failed stage or unfinished job is an operational error under gate 6.
        if result.get('failures') or row['job'].get('status') != 'complete':
            chat_errors.append(row['id'])
        excerpts += excerpt_failures(row)
        for i, ref in enumerate(refs):
            judged = verdict['sentences'][i]
            if judged['text'] != ref['text']:
                raise ValueError('Review does not match displayed sentence: ' + row['id'])
            key = f"answers-v2-{row['id']}-{ref['id']}"
            if i == 0:
                first[row['id']] = key
            (errors if judged['verdict'] == 'error' else borderline if judged['verdict'] == 'borderline' else []).append(key)
            items.append(dict(id=key, group=GROUP, text=ref['text'], question=q['question'], source_title=ref.get('title'),
                              source_type='public PDF', span=ref.get('span'), spans=ref.get('spans'),
                              context=blocks.get((ref.get('span') or {}).get('block_id'), ref.get('quote', '')),
                              receipt=ref.get('verification'),
                              ai_verdict=dict(error=judged['verdict'] == 'error', borderline=judged['verdict'] == 'borderline',
                                              reason=judged.get('reason', ''), reviewer='Claude (cross-family AI review)')))
        if q['answer_type'] == 'not in sources':
            not_covered[row['id']] = bool(refs) and verdict.get('not_covered_ok') is True
        else:
            direct[row['id']] = bool(refs) and result.get('answer_kind') == 'generated_answer' and verdict.get('direct') is True
    # An interrupted turn never finished: count it as slower than any limit.
    seconds = [float('inf') if row.get('wall_seconds') is None else row['wall_seconds'] for row in rows]
    minimum = -(-7 * len(answerable) // 10)
    gates = dict(
        direct_answers=dict(value=sum(direct.values()), required=minimum, of=len(answerable), passed=sum(direct.values()) >= minimum),
        not_covered=dict(value=sum(not_covered.values()), required=len(not_covered), passed=all(not_covered.values()) and len(not_covered) == 3),
        excerpt_replies=dict(value=len(excerpts), detail=excerpts, passed=not excerpts),
        silent_errors=dict(value=len(errors), borderline=len(borderline), detail=errors, passed=not errors),
        median_seconds=dict(value=round(median(seconds), 1), limit=300, passed=median(seconds) <= 300,
                            interrupted=sum(x == float('inf') for x in seconds)),
        chat_errors=dict(value=len(chat_errors), detail=chat_errors, passed=not chat_errors))
    fixed = all(gates[k]['passed'] for k in ('not_covered', 'excerpt_replies', 'median_seconds', 'chat_errors'))
    status = 'PASS' if all(g['passed'] for g in gates.values()) else 'FAIL'
    items += blocked_items(rows, questions, blocks)
    return dict(status=status, gates=gates, direct=direct, not_covered=not_covered, review='AI review (Claude vs local Qwen3.5); owner labels pending',
                questions=len(rows)), items, dict(group=GROUP, fixed_gates_pass=fixed, borderline_is_error=False,
                direct_answers=dict(minimum=minimum, first_sentence=first, ai_direct=direct),
                reason='Registered answers-v2 rule; labels can change direct answers and silent errors, never the fixed gates.')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--measurement', type=Path, required=True)
    p.add_argument('--review', type=Path, required=True)
    p.add_argument('--document', type=Path, action='append', default=[])
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--labels', type=Path)
    a = p.parse_args()
    verdict, items, base = evaluate(a.config, a.measurement, a.review, a.document)
    write(a.out, verdict)
    if a.labels:
        store = LabelStore(a.labels)
        store.merge(items)
        bases = read(a.labels / 'verdict-bases.json', {})
        bases['answers-v2'] = base
        write(a.labels / 'verdict-bases.json', bases)
    print(json.dumps(dict(status=verdict['status'], gates={k: (g['value'], g['passed']) for k, g in verdict['gates'].items()})))
