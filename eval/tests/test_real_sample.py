"""Synthetic fixtures only: immutable draws, blind payload, and owner-only sample statistics."""
import json
import pytest


def test_constrained_proportional_quotas_and_seeded_draw():
    from eval.reading.real.sample import allocate, draw
    populations = {f'p{i}': n for i, n in enumerate([32, 40, 35, 1, 340, 45])}
    quotas = allocate(populations, 80)
    assert sum(quotas.values()) == 80
    assert quotas['p3'] == 1
    assert all(quotas[p] >= min(5, n) for p, n in populations.items())
    assert quotas['p4'] >= 54  # proportional, rather than equal page quotas
    groups = {p: list(range(n)) for p, n in populations.items()}
    a = draw(groups, 80, 20261006, 'initial:flagged')
    assert a == draw(dict(reversed(list(groups.items()))), 80, 20261006, 'initial:flagged')
    assert a != draw(groups, 80, 20261007, 'initial:flagged')
    assert len(a) == len(set(a)) == 80
    with pytest.raises(ValueError, match='population'):
        allocate({'p': 4}, 5)


def test_manifest_freeze_never_overwrites_even_after_answers(tmp_path):
    from eval.reading.real.sample import freeze, digest
    path = tmp_path / 'sample.json'
    data = {'seed': 1, 'items': [{'id': 'a'}]}
    freeze(path, data)
    original = path.read_bytes()
    freeze(path, data)
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match='immutable'):
        freeze(path, {'seed': 2})
    assert path.read_bytes() == original
    assert digest(data) == digest(json.loads(original))


def test_blind_payload_has_only_drawn_items_and_no_classification():
    from eval.reading.real.sample import blind_payload
    manifest = {'batch': 'fixture', 'seed': 20261006, 'items': [
        {'id': 'a', 'page': 'doc_p0000', 'token_index': 1, 'flagged': True,
         'reader1': '20', 'reader2': '28', 'layer': '20', 'context': 'Year 20',
         'bbox': [1, 2, 3, 4]}], 'review_order': ['a']}
    payload = blind_payload(manifest, {'a': {'crop': 'a.png', 'context_crop': 'line.png'}})
    assert len(payload['items']) == 1
    assert not any(k in json.dumps(payload) for k in ('flagged', 'token_index', 'seed', 'reasons'))
    assert payload['items'][0]['reader2'] == '28'
    assert 'chosen' not in payload['items'][0]


def test_wilson_and_exact_one_sided_binomial_upper():
    from eval.reading.real.sample import wilson, binomial_upper
    assert wilson(0, 100)[1] == pytest.approx(.03699349820698568)
    assert binomial_upper(0, 100) == pytest.approx(1 - .05 ** .01)
    assert binomial_upper(1, 100) == pytest.approx(.0465598114535389)
    assert binomial_upper(100, 100) == 1
    assert wilson(0, 0) is None and binomial_upper(0, 0) is None
    assert wilson(50, 100)[0] == pytest.approx(1 - wilson(50, 100)[1])


def test_measure_excludes_illegible_requires_every_owner_answer_and_preserves_input():
    from eval.reading.real.sample import statistics
    items = [{'id': str(i), 'page': 'doc_p0000', 'reader1': str(i), 'flagged': i < 3}
             for i in range(6)]
    manifest = {'items': items, 'populations': {'doc_p0000': {'flagged': 3, 'accepted': 3}}}
    answers = {str(i): {'kind': 'number', 'value_as_printed': str(i), 'verified_by': 'Fixture reviewer'}
               for i in range(6)}
    answers['1'] = {'kind': 'illegible', 'value_as_printed': None, 'verified_by': 'Fixture reviewer'}
    answers['2']['value_as_printed'] = '99'
    answers['5']['kind'] = 'not_number'; answers['5']['value_as_printed'] = None
    before = json.dumps(answers)
    result = statistics(manifest, answers)
    assert result['flagged']['n'] == 2 and result['flagged']['false_alarms'] == 1
    assert result['flagged']['illegible'] == 1
    assert result['accepted']['n'] == 3 and result['accepted']['silent_errors'] == 1
    assert result['pages']['doc_p0000']['accepted']['n'] == 3
    assert json.dumps(answers) == before
    with pytest.raises(ValueError, match='BLOCKED-ON-OWNER'):
        statistics(manifest, {k: v for k, v in answers.items() if k != '0'})
    answers['0']['verified_by'] = ''
    with pytest.raises(ValueError, match='owner'):
        statistics(manifest, answers)


def test_prediction_hash_and_gt_batch_identity_are_enforced(tmp_path):
    from eval.reading.real.sample import validate_records, read_answers, digest
    record = tmp_path / 'doc_p0000.json'; record.write_text('{}', encoding='utf8')
    import hashlib
    manifest = {'batch': 'fixture', 'records': {'doc_p0000': hashlib.sha256(record.read_bytes()).hexdigest()},
                'items': [{'id': 'a', 'page': 'doc_p0000'}]}
    validate_records(manifest, tmp_path)
    record.write_text('{"changed":true}', encoding='utf8')
    with pytest.raises(ValueError, match='changed'):
        validate_records(manifest, tmp_path)
    gt = {'doc_key': 'doc', 'page_index': 0, 'sample_reviews': {'fixture': {
        'manifest_sha256': digest(manifest), 'answers': {}}}}
    (tmp_path / 'doc_p0000.json').write_text(json.dumps(gt), encoding='utf8')
    assert read_answers(manifest, tmp_path) == {}
    gt['sample_reviews']['fixture']['manifest_sha256'] = 'wrong'
    (tmp_path / 'doc_p0000.json').write_text(json.dumps(gt), encoding='utf8')
    with pytest.raises(ValueError, match='manifest'):
        read_answers(manifest, tmp_path)


def test_gao_extension_cannot_change_initial_draw(monkeypatch, tmp_path):
    from eval.reading.real import sample
    initial = tmp_path / 'initial.json'; gao = tmp_path / 'gao.json'
    data = {'items': [{'id': 'original'}]}
    initial.write_text(json.dumps(data), encoding='utf8')
    extension = {'items': [{'id': 'gao-only'}], 'initial_manifest_sha256': sample.digest(data)}
    gao.write_text(json.dumps(extension), encoding='utf8')
    monkeypatch.setattr(sample, 'INITIAL', initial); monkeypatch.setattr(sample, 'GAO', gao)
    assert sample.manifests()[0] == data
    extension['initial_manifest_sha256'] = 'wrong'
    gao.write_text(json.dumps(extension), encoding='utf8')
    with pytest.raises(ValueError, match='another initial'):
        sample.manifests()


def test_sample_html_never_embeds_population_or_unselected_predictions():
    from eval.reading.real.sample_review import render_sample_html
    html = render_sample_html([{'batch': 'fixture', 'manifest_sha256': 'abc', 'items': []}])
    assert '__SAMPLE_DATA__' not in html
    assert '"flagged"' not in html and '"accepted"' not in html
    assert 'createWritable' in html and 'showDirectoryPicker' in html
    assert 'localStorage' not in html  # disk is authoritative on resume
    assert '<script src=' not in html and 'https://' not in html


def test_all_illegible_and_empty_strata_have_no_invented_rate():
    from eval.reading.real.sample import statistics
    manifest = {'items': [{'id': 'a', 'page': 'p', 'reader1': '1', 'flagged': True}],
                'populations': {'p': {'flagged': 1, 'accepted': 0}}}
    result = statistics(manifest, {'a': {'kind': 'illegible', 'verified_by': 'Fixture'}})
    assert result['flagged']['n'] == 0 and result['flagged']['rate'] is None
    assert result['accepted']['exact_binomial_upper_95'] is None
    assert result['population_weighted_point_estimates'] == {'flagged': None, 'accepted': None}


def test_sample_measurement_publishes_only_signed_fixture_and_blocks_pending_gao(monkeypatch, tmp_path):
    from eval.reading.real import sample
    from eval.reading import closeout
    here = tmp_path / 'eval/reading/real'; (here / 'gt').mkdir(parents=True)
    (tmp_path / 'reports').mkdir()
    out = tmp_path / 'out'; out.mkdir()
    fixture = {'batch': 'initial', 'sources': {'fixture': 'sha'}, 'records': {},
               'items': [{'id': 'a', 'page': 'fixture_p0000', 'reader1': '20', 'flagged': False}],
               'populations': {'fixture_p0000': {'flagged': 0, 'accepted': 1}}}
    gt = {'doc_key': 'fixture', 'page_index': 0, 'status': 'template', 'numbers': []}
    path = here / 'gt/fixture_p0000.json'; path.write_text(json.dumps(gt), encoding='utf8')
    monkeypatch.setattr(sample, 'HERE', here); monkeypatch.setattr(closeout, 'OUT', out)
    monkeypatch.setattr(sample, 'GAO', tmp_path / 'absent-gao.json')
    monkeypatch.setattr(sample, 'require_verified', lambda doc: tmp_path / 'fixture.pdf')
    monkeypatch.setattr(sample, 'manifests', lambda: [fixture])
    with pytest.raises(ValueError, match='BLOCKED-ON-OWNER'):
        sample.measure_samples()
    assert not (out / 'real-sample-metrics.json').exists()
    gt['sample_reviews'] = {'initial': {'manifest_sha256': sample.digest(fixture), 'answers': {
        'a': {'kind': 'number', 'value_as_printed': '20', 'verified_by': 'Synthetic fixture'}}}}
    path.write_text(json.dumps(gt), encoding='utf8'); before = path.read_bytes()
    sample.measure_samples()
    result = json.loads((out / 'real-sample-metrics.json').read_text(encoding='utf8'))
    assert result['batches'][0]['accepted']['silent_errors'] == 0
    assert result['gao'].startswith('BLOCKED-ON-OWNER')
    assert (tmp_path / 'reports/step4c-sample-metrics.md').exists()
    assert path.read_bytes() == before
    # A newly frozen but unreviewed extension does not block the completed initial batch.
    gao = {'batch': 'gao', 'sources': {}, 'records': {},
           'items': [{'id': 'g', 'page': 'fixture_p0000', 'reader1': '21', 'flagged': True}],
           'populations': {'fixture_p0000': {'flagged': 1, 'accepted': 0}}}
    monkeypatch.setattr(sample, 'manifests', lambda: [fixture, gao])
    sample.GAO.write_text('{}', encoding='utf8')
    sample.measure_samples()
    result = json.loads((out / 'real-sample-metrics.json').read_text(encoding='utf8'))
    assert result['batches'][0]['batch'] == 'initial' and len(result['batches']) == 1
    assert result['blocked'][0]['batch'] == 'gao'
    assert result['gao'].startswith('BLOCKED-ON-OWNER')


def test_review_generation_requires_a_committed_unchanged_manifest(monkeypatch, tmp_path):
    from eval.reading.real import sample_review
    from types import SimpleNamespace
    here = tmp_path / 'eval/reading/real'; here.mkdir(parents=True)
    path = here / 'sample.json'; path.write_text('{"items":[]}', encoding='utf8')
    monkeypatch.setattr(sample_review, 'HERE', here)
    monkeypatch.setattr(sample_review.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout=b''))
    with pytest.raises(ValueError, match='Commit this frozen sample'):
        sample_review.require_committed(path)
    monkeypatch.setattr(sample_review.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=b'{"items":[]}'))
    sample_review.require_committed(path)
    path.write_text('{"items":[1]}', encoding='utf8')
    with pytest.raises(ValueError, match='Commit this frozen sample'):
        sample_review.require_committed(path)


def test_portable_review_embeds_images_without_changing_the_draw(tmp_path):
    from eval.reading.real.sample_review import embedded_assets
    from PIL import Image
    folder = tmp_path / 'review_assets'; folder.mkdir()
    Image.new('RGB', (3, 3), 'white').save(folder / 'number.png')
    assets = {'frozen-id': {'crop': 'review_assets/number.png', 'context_crop': 'review_assets/number.png'}}
    before = json.dumps(assets)
    result = embedded_assets(assets, tmp_path)
    assert list(result) == ['frozen-id'] and json.dumps(assets) == before
    assert result['frozen-id']['crop'].startswith('data:image/png;base64,')
    import base64
    assert base64.b64decode(result['frozen-id']['crop'].split(',', 1)[1]) == (folder / 'number.png').read_bytes()
