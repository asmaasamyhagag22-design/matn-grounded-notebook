"""Synthetic-only checks of owner export integrity and mixed-reference provenance."""
import copy
import json
import pytest
from eval.reading.real.sample import digest, statistics
from eval.reading.real.targeted_audit import select_problems
from eval.reading.real.targeted_measure import validate_export, build_mixed_reference


def fixture():
    sample = {'items': [
        {'id': 'a', 'page': 'fixture_p0000', 'reader1': '10', 'reader2': '10', 'flagged': True},
        {'id': 'b', 'page': 'fixture_p0000', 'reader1': '20', 'reader2': '21', 'flagged': False},
        {'id': 'c', 'page': 'fixture_p0000', 'reader1': '30', 'reader2': '30', 'flagged': False}],
        'review_order': ['a', 'b', 'c'], 'populations': {'fixture_p0000': {'flagged': 1, 'accepted': 2}}}
    latest = {'manifest_sha256': digest(sample), 'reviewer_type': 'model', 'human_verified': False,
              'answers': {i['id']: {'kind': 'number', 'value_as_printed': i['reader2'], 'review_number': n,
                         'verified_by': 'model fixture', 'reviewer_type': 'model', 'human_verified': False}
                         for n, i in enumerate(sample['items'], 1)}}
    first = copy.deepcopy(latest); first['answers']['a']['value_as_printed'] = '12'
    plan = select_problems(sample, first, latest)
    answers = {i: {'kind': 'number', 'value_as_printed': v, 'verified_by': 'asmaa',
                  'verified_at': '2026-10-10T12:00:00Z', 'method': 'typed'} for i, v in [('a', '10'), ('b', '20')]}
    export = {'schema': 'matn-human-sample-answers/1',
              'manifest_key': json.dumps([[plan['batch'], digest(plan)]], separators=(',', ':')),
              'answers': answers, 'history': [{'item_id': i, 'answer': copy.deepcopy(a)} for i, a in answers.items()]}
    return sample, first, latest, plan, export


def test_mixed_reference_keeps_owner_values_and_never_signs_agreement_as_human():
    args = fixture(); before = copy.deepcopy(args)
    mixed = build_mixed_reference(*args)
    assert args == before
    assert mixed['provenance_statement'] == 'initial annotation: model family A; targeted audit: asmaa'
    assert mixed['human_audited_ids'] == ['a', 'b']
    assert mixed['unaudited_three_way_agreement_ids'] == ['c']
    assert mixed['all_items_human_verified'] is False
    assert mixed['answers']['b']['human_verified'] is True
    assert mixed['answers']['b']['value_as_printed'] == '20'
    assert mixed['answers']['b']['verified_at'] == args[-1]['answers']['b']['verified_at']
    assert mixed['answers']['c']['human_verified'] is False
    assert mixed['answers']['c']['verified_by'] == 'model fixture'
    assert len(mixed['changes_from_latest_ai']) == 1
    result = statistics(args[0], mixed['answers'])
    assert result['flagged']['false_alarms'] == 1
    assert result['accepted']['silent_errors'] == 0
    assert result['accepted']['rule_of_three_upper_approx'] == 1.5


@pytest.mark.parametrize('tamper', ['identity', 'missing', 'extra', 'unsigned', 'history', 'time'])
def test_tampered_or_partial_owner_export_is_rejected(tamper):
    *_, plan, export = fixture()
    if tamper == 'identity': export['manifest_key'] = 'wrong'
    if tamper == 'missing': del export['answers']['a']
    if tamper == 'extra': export['answers']['z'] = export['answers']['a']
    if tamper == 'unsigned': export['answers']['a']['verified_by'] = 'model'
    if tamper == 'history': export['history'] = []
    if tamper == 'time': export['answers']['a']['verified_at'] = 'not-a-date'
    with pytest.raises(ValueError): validate_export(export, plan)


def test_owner_abstention_is_separate_not_overridden_by_ai():
    args = list(fixture()); export = args[-1]
    export['answers']['b'].update(kind='illegible', value_as_printed=None)
    export['history'][-1]['answer'] = copy.deepcopy(export['answers']['b'])
    mixed = build_mixed_reference(*args)
    result = statistics(args[0], mixed['answers'])
    assert mixed['answers']['b']['kind'] == 'illegible'
    assert result['accepted']['illegible'] == 1 and result['accepted']['n'] == 1


def test_changed_frozen_plan_is_rejected():
    args = list(fixture()); args[-2]['three_way_agreement_not_audited'] = []
    with pytest.raises(ValueError, match='Changed frozen'): build_mixed_reference(*args)


def test_import_preserves_exact_export_bytes_and_refuses_overwrite(monkeypatch, tmp_path):
    from eval.reading.real import targeted_measure as module
    sample, first, latest, plan, export = fixture()
    plan_path = tmp_path / 'plan.json'; plan_path.write_text(json.dumps(plan))
    incoming = tmp_path / 'export.json'; incoming.write_text(json.dumps(export, indent=3)+'\n')
    archived = tmp_path / 'owner.json'
    monkeypatch.setattr(module, 'PLAN', plan_path); monkeypatch.setattr(module, 'ANSWERS', archived)
    monkeypatch.setattr(module, 'load_inputs', lambda: [sample, first, latest])
    module.import_export(incoming)
    assert archived.read_bytes() == incoming.read_bytes()
    original = archived.read_bytes(); module.import_export(incoming)
    export['answers']['b']['value_as_printed'] = '19'
    export['history'][-1]['answer']['value_as_printed'] = '19'
    incoming.write_text(json.dumps(export))
    with pytest.raises(ValueError, match='immutable'): module.import_export(incoming)
    assert archived.read_bytes() == original
