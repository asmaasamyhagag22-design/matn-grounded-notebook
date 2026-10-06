"""Model-reference scoring cannot masquerade as signed human GT."""
import copy
import hashlib

import pytest

from eval.reading.real.sample import digest


def fixture(tmp_path):
    crop = tmp_path / 'crop.png'
    crop.write_bytes(b'fixture image bytes')
    sha = hashlib.sha256(crop.read_bytes()).hexdigest()
    manifest = {'items': [
        {'id': 'a', 'page': 'p', 'reader1': '10', 'flagged': True},
        {'id': 'b', 'page': 'p', 'reader1': '20', 'flagged': False},
        {'id': 'c', 'page': 'p', 'reader1': '30', 'flagged': False}],
        'review_order': ['c', 'a', 'b'],
        'populations': {'p': {'flagged': 1, 'accepted': 2}}}
    reference = {'schema': 'matn-gpt-sample-annotations/1',
                 'manifest_sha256': digest(manifest), 'reviewer_type': 'model',
                 'human_verified': False, 'answers': {}}
    for n, item_id in enumerate(manifest['review_order'], 1):
        reference['answers'][item_id] = {
            'review_number': n, 'kind': 'number', 'value_as_printed':
            {'a': '10', 'b': '21', 'c': '30'}[item_id],
            'verified_by': 'GPT fixture', 'reviewer_type': 'model', 'human_verified': False,
            'images': {'crop': 'crop.png', 'context_crop': 'crop.png',
                       'crop_sha256': sha, 'context_sha256': sha}}
    reference['answers']['c'].update(kind='illegible', value_as_printed=None)
    return manifest, reference


def test_model_scoring_keeps_provenance_illegible_and_inputs(tmp_path):
    from eval.reading.real.gpt_annotation import measure_reference
    manifest, reference = fixture(tmp_path)
    before = copy.deepcopy(reference)
    result = measure_reference(manifest, reference, tmp_path)
    assert result['human_verified'] is False and result['reviewer_type'] == 'model'
    assert result['flagged']['false_alarms'] == 1
    assert result['accepted']['silent_errors'] == 1
    assert result['accepted']['n'] == 1 and result['accepted']['illegible'] == 1
    assert result['differences'][0]['item_id'] == 'b'
    assert reference == before


@pytest.mark.parametrize('tamper', ['manifest', 'extra', 'missing', 'order', 'human', 'answer_human', 'image'])
def test_rejects_wrong_manifest_incomplete_review_false_provenance_and_changed_images(tmp_path, tamper):
    from eval.reading.real.gpt_annotation import measure_reference
    manifest, reference = fixture(tmp_path)
    if tamper == 'manifest': reference['manifest_sha256'] = 'wrong'
    if tamper == 'extra': reference['answers']['other'] = reference['answers']['a']
    if tamper == 'missing': del reference['answers']['a']
    if tamper == 'order': reference['answers']['a']['review_number'] = 1
    if tamper == 'human': reference['human_verified'] = True
    if tamper == 'answer_human': reference['answers']['a']['human_verified'] = True
    if tamper == 'image': (tmp_path / 'crop.png').write_bytes(b'changed')
    with pytest.raises(ValueError):
        measure_reference(manifest, reference, tmp_path)


def test_static_annotation_view_is_portable_escaped_and_has_no_write_script(tmp_path):
    from eval.reading.real.gpt_annotation import render_reference
    manifest, reference = fixture(tmp_path)
    reference['answers']['a']['note'] = '<script>injected</script>'
    html = render_reference(manifest, reference, tmp_path)
    assert html.count('<details>') == 3
    assert html.count('data:image/png;base64,') == 6
    assert '&lt;script&gt;injected' in html and '<script' not in html
    assert 'human_verified=false' in html


def test_closeout_states_complete_only_delegated_model_scope():
    from eval.reading.closeout_report import model_sample_closeout
    original = [('D2 — sampled GT complete', 'BLOCKED-ON-OWNER', 'owner review'),
                ('D3', 'BLOCKED-ON-OWNER', 'missing GAO'),
                ('D4 — measured on sample', 'BLOCKED-ON-OWNER', 'owner metrics'),
                ('F1', 'BLOCKED-ON-OWNER', 'real rates pending')]
    model = {'accepted': {'silent_errors': 4, 'n': 100}}
    rows = model_sample_closeout(original, model)
    assert rows[1] == original[1]
    assert all(r[1] == 'DONE' for r in (rows[0], rows[2], rows[3]))
    assert 'GPT' in rows[0][0] and 'human_verified=false' in rows[0][2]
    assert '4/100' in rows[2][2]
    assert original[0][1] == 'BLOCKED-ON-OWNER'
    assert model_sample_closeout(original, None) == original
