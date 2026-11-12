"""Week-loop C1b (addendum-1 §6 gate): when the planner says 'not in sources', nothing generated is shown and no background is drafted."""


def _run(tmp_path, monkeypatch, answer_type, receipt='verified'):
    from tests.app.test_evidence import ingest_json
    from matn_app import evidence
    from matn_app.answer_profile import load_answer_profile
    _, source = ingest_json(tmp_path, {'finding': 'Unemployment declined to 7.5 percent nationally.'})
    catalog = evidence._load_catalog(source['catalog']); calls = []

    def attempt(notebook, question, folder, **kwargs):
        calls.append(str(question))
        return dict(state='partial_answer', answer_plan=dict(answer_type=answer_type, sentences=[]),
                    sentences=[dict(text='Unemployment fell to 7.5 percent nationally.', kind='generated_verified_unit', receipt_index=0,
                                    citations=[dict(doc_id=catalog.sources[0].doc_id, pdf_page_index=0,
                                                    quote='Unemployment declined to 7.5 percent nationally.')])],
                    receipts=[dict(status=receipt)], app_calls=dict(generation=2, native=1)), []
    monkeypatch.setattr(evidence, '_notebook_answer', attempt)
    value = evidence.answer(dict(question='What was unemployment in Alexandria?', catalogs=[source['catalog']],
                                 notebooks=['fixture.db'], workdir=str(tmp_path / 'answer'),
                                 answer_profile=dict(load_answer_profile(),answer_path='v2')))
    return value, calls


def test_planner_not_in_sources_shows_nothing_generated(tmp_path, monkeypatch):
    value, calls = _run(tmp_path, monkeypatch, 'not in sources')
    assert value['status'] == 'abstained' and value['answer_kind'] == 'no_verified_generated_answer'
    assert not value['citations'] and 'could not verify' in value['text']
    assert value['gate'] == 'planner_not_in_sources' and 'partial_answer' not in value['engine_states']


def test_planner_not_in_sources_drafts_no_background(tmp_path, monkeypatch):
    # Nothing verified: without the gate this is exactly when background coverage is drafted.
    value, calls = _run(tmp_path, monkeypatch, 'not in sources', receipt='rejected')
    assert len(calls) == 1 and value['status'] == 'abstained' and not value['citations']


def test_unverified_direct_plan_still_drafts_background(tmp_path, monkeypatch):
    value, calls = _run(tmp_path, monkeypatch, 'direct', receipt='rejected')
    assert len(calls) == 2 and value['gate'] is None


def test_direct_plan_stays_an_answer(tmp_path, monkeypatch):
    value, calls = _run(tmp_path, monkeypatch, 'direct')
    assert value['answer_kind'] == 'generated_answer' and value['status'] in ('answered', 'partial_answer')
    assert len(calls) == 1 and value['gate'] is None
