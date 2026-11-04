import json

from scripts.evaluate_answers_v2 import evaluate


def ref(i, text, quote):
    span = dict(block_id='b1', quote=quote, start=0, end=len(quote))
    return dict(id=str(i), text=text, quote=quote, status='verified', kind='generated_verified_unit', span=span, spans=[span], title='T')


def row(qid, refs, seconds=200, kind='generated_answer'):
    text = '\n\n'.join(r['text'] + ' [' + r['id'] + ']' for r in refs)
    return dict(id=qid, wall_seconds=seconds, job=dict(status='complete'),
                result=dict(answer_kind=kind, text=text, citations=refs, failures=[]))


def test_gates_count_direct_answers_copies_and_not_covered(tmp_path):
    qs = [dict(id=f'A{i}', question='q', expected_pages=[], answer_type='direct') for i in range(10)]
    qs += [dict(id=f'N{i}', question='q', expected_pages=[], answer_type='not in sources') for i in range(3)]
    (tmp_path / 'c.json').write_text(json.dumps(dict(questions=qs)))
    good = ref(1, 'Workers should get training before they use equipment.', 'Workers should receive training before operating equipment.')
    copy = ref(1, 'Workers should receive training before operating equipment.', 'Workers should receive training before operating equipment.')
    rows = [row(f'A{i}', [good]) for i in range(7)] + [row('A7', [copy]), row('A8', []), row('A9', [], seconds=900)]
    rows += [row(f'N{i}', [good], kind='generated_source_coverage') for i in range(3)]
    (tmp_path / 'm.json').write_text(json.dumps(dict(results=rows)))
    review = {r['id']: dict(direct=True, not_covered_ok=True,
                            sentences=[dict(text=c['text'], verdict='supported') for c in r['result']['citations']]) for r in rows}
    review['A0']['sentences'][0]['verdict'] = 'borderline'
    (tmp_path / 'r.json').write_text(json.dumps(review))
    (tmp_path / 'd.json').write_text(json.dumps(dict(elements=[dict(block=dict(block_id='b1', text='Context.'))])))
    verdict, items, base = evaluate(tmp_path / 'c.json', tmp_path / 'm.json', tmp_path / 'r.json', [tmp_path / 'd.json'])
    gates = verdict['gates']
    assert gates['direct_answers']['value'] == 8 and gates['direct_answers']['required'] == 7 and gates['direct_answers']['passed']
    assert gates['excerpt_replies']['value'] == 1 and not gates['excerpt_replies']['passed']
    assert gates['not_covered']['passed'] and gates['silent_errors']['passed'] and gates['silent_errors']['borderline'] == 1
    assert verdict['status'] == 'FAIL' and base['fixed_gates_pass'] is False and not base['borderline_is_error']
    assert len(items) == 11 and items[0]['context'] == 'Context.' and base['direct_answers']['first_sentence']['A0'] == 'answers-v2-A0-1'
