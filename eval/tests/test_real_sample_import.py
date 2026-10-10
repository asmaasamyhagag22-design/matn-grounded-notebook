"""Human import validation against synthetic answers only."""
import copy
import json
import pytest
from eval.reading.real.import_answers import import_answers
from eval.reading.real.sample import digest


def fixture(tmp_path):
    batch = {'batch': 'initial', 'items': [{'id': 'a', 'page': 'fixture_p0000'}, {'id': 'b', 'page': 'fixture_p0001'}]}
    for index in range(2):
        (tmp_path / f'fixture_p{index:04d}.json').write_text(json.dumps({
            'doc_key': 'fixture', 'page_index': index, 'numbers': [], 'blocks': ['keep'], 'status': 'template'}))
    answer = {'kind': 'number', 'value_as_printed': '17', 'verified_by': 'Synthetic reviewer',
              'verified_at': '2026-10-10T00:00:00Z', 'method': 'typed'}
    export = {'schema': 'matn-human-sample-answers/1',
              'manifest_key': json.dumps([['initial', digest(batch)]], separators=(',', ':')),
              'answers': {'a': answer}, 'history': [{'item_id': 'a', 'answer': answer}]}
    return batch, export


def test_partial_import_preserves_full_page_and_is_idempotent(tmp_path):
    batch, export = fixture(tmp_path)
    untouched = (tmp_path / 'fixture_p0001.json').read_bytes()
    assert import_answers(export, tmp_path, [batch]) == 1
    path = tmp_path / 'fixture_p0000.json'; first = path.read_bytes()
    gt = json.loads(first)
    assert gt['numbers'] == [] and gt['blocks'] == ['keep'] and gt['status'] == 'template'
    assert gt['sample_reviews']['initial']['answers'] == export['answers']
    assert import_answers(export, tmp_path, [batch]) == 1
    assert path.read_bytes() == first
    assert (tmp_path / 'fixture_p0001.json').read_bytes() == untouched


@pytest.mark.parametrize('failure', ['hash', 'unknown', 'unsigned', 'history', 'identity', 'conflict'])
def test_bad_export_never_changes_any_template(tmp_path, failure):
    batch, export = fixture(tmp_path)
    if failure == 'hash': export['manifest_key'] = 'wrong'
    if failure == 'unknown': export['answers']['unknown'] = export['answers']['a']
    if failure == 'unsigned': export['answers']['a']['verified_by'] = ''
    if failure == 'history': export['history'] = []
    if failure == 'identity':
        (tmp_path / 'fixture_p0000.json').write_text('{"doc_key":"wrong","page_index":0}')
    if failure == 'conflict':
        import_answers(export, tmp_path, [batch])
        export = copy.deepcopy(export)
        export['answers']['a']['value_as_printed'] = '18'
        export['history'][-1]['answer']['value_as_printed'] = '18'
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError): import_answers(export, tmp_path, [batch])
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
