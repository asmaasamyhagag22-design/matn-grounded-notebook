"""Problem selection and provenance separation; synthetic answers only."""
from copy import deepcopy
import pytest
from eval.reading.real.sample import digest
from eval.reading.real.targeted_audit import select_problems, render_targeted


def fixture():
    sample = {'items': [{'id': str(i), 'page': 'fixture_p0000', 'reader1': '17', 'reader2': '17'}
                        for i in range(6)], 'review_order': list(map(str, range(6)))}
    first = {'manifest_sha256': digest(sample), 'reviewer_type': 'model', 'human_verified': False,
             'answers': {str(i): {'kind': 'number', 'value_as_printed': '17', 'review_number': i+1}
                         for i in range(6)}}
    latest = deepcopy(first)
    latest['answers']['0']['value_as_printed'] = '19'  # changed and differs from both
    for r in (first, latest):
        r['answers']['1'].update(kind='illegible', value_as_printed=None)
        r['answers']['2']['value_as_printed'] = '18'  # same in snapshots; mismatch both
        r['answers']['3'].update(kind='not_number', value_as_printed=None)
    sample['items'][4]['reader2'] = None
    for r in (first, latest): r['manifest_sha256'] = digest(sample)
    return sample, first, latest


def test_selection_union_deduplicates_excludes_agreements_and_never_changes_answers():
    inputs = fixture(); before = deepcopy(inputs)
    plan = select_problems(*inputs)
    assert plan['review_order'] == ['0', '1', '2', '3', '4']
    assert plan['three_way_agreement_not_audited'] == ['5']
    assert plan['random_control_count'] == 0
    assert plan['reason_counts']['AI snapshots differ'] == 1
    assert plan['reason_counts']['Reader 2 unavailable'] == 1
    assert plan['initial_annotation'] == 'GPT (Codex)'
    assert plan['targeted_audit'] == 'pending: asmaa'
    assert inputs == before
    assert select_problems(*inputs) == plan


def test_changed_item_included_even_if_latest_agrees_with_both_readers():
    sample, first, latest = fixture()
    first['answers']['5']['value_as_printed'] = '16'
    assert '5' in select_problems(sample, first, latest)['review_order']


def test_bad_reference_identity_or_human_relabel_is_rejected():
    sample, first, latest = fixture()
    first['manifest_sha256'] = 'wrong'
    with pytest.raises(ValueError, match='frozen sample'): select_problems(sample, first, latest)
    first['manifest_sha256'] = digest(sample); first['human_verified'] = True
    with pytest.raises(ValueError, match='AI provenance'): select_problems(sample, first, latest)


def test_render_separates_audit_storage_and_exposes_current_ai_as_suggestion_only():
    html = render_targeted({'batch': 'targeted-audit', 'manifest_sha256': 'fixture', 'items': []})
    assert 'Problem items' in html and 'matn-targeted-audit-answers.json' in html
    assert 'value="asmaa"' in html and 'id="folder" hidden disabled' in html
    assert 'confirm-ai-after-scan-review' in html
    assert 'Initial annotation: GPT (Codex)' in html
    assert 'answers={}' in html and 'indexedDB' in html
