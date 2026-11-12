"""Week-loop follow-up to C1b: the live progress stream never keeps a sentence the final answer does not show."""
import json


def _stream(monkeypatch, answer_type, passes_contract, single=True, receipt='verified'):
    from matn_app import answer_engine
    seen = []
    engine = object.__new__(answer_engine.AppChatEngine)
    engine.__dict__.update(answer_plan=dict(answer_type=answer_type, sentences=[1]), handles={},
                           on_verified=lambda item, index: seen.append(item['text']), _status=lambda *a: None)
    item = dict(text='Unemployment fell to 7.5 percent.', reasons=[], receipt=dict(status=receipt))
    parent = answer_engine.AppChatEngine.__mro__[1]
    monkeypatch.setattr(parent, '_verify', lambda self, s, *a: [(dict(item), 0)])
    monkeypatch.setattr(answer_engine, 'copied_prose', lambda text, handles: not passes_contract)
    monkeypatch.setattr(answer_engine, 'sentence_spans', lambda text: [text] if single else [text, text])
    engine._verify(['s'], None, [], {}, [])
    return seen


def test_contract_passing_sentence_streams_on_a_direct_plan(monkeypatch):
    assert _stream(monkeypatch, 'direct', True) == ['Unemployment fell to 7.5 percent.']


def test_no_streaming_when_the_plan_says_not_in_sources(monkeypatch):
    assert _stream(monkeypatch, 'not in sources', True) == []


def test_no_streaming_for_a_source_copy_the_reply_contract_drops(monkeypatch):
    assert _stream(monkeypatch, 'direct', False) == []


def test_progress_file_is_reconciled_with_the_final_answer(tmp_path):
    from matn_app.evidence import _reconcile_progress
    path = tmp_path / 'verified-progress.json'
    rows = [dict(text='Kept.', at=2.0), dict(text='Dropped later.', at=1.0)]
    path.write_text(json.dumps(dict(first_at=1.0, sentences=rows)))
    _reconcile_progress(tmp_path, dict(status='partial_answer', citations=[dict(text='Kept.')]))
    value = json.loads(path.read_bytes())
    assert [s['text'] for s in value['sentences']] == ['Kept.'] and value['first_at'] == 2.0
    _reconcile_progress(tmp_path, dict(status='abstained', citations=[]))
    assert not path.exists()


def test_no_streaming_for_two_sentences_or_an_unverified_receipt(monkeypatch):
    assert _stream(monkeypatch, 'direct', True, single=False) == []
    assert _stream(monkeypatch, 'direct', True, receipt='rejected') == []


def test_withheld_sentences_leave_the_stream_before_background_drafting(tmp_path, monkeypatch):
    from tests.app.test_evidence import ingest_json
    from matn_app import evidence
    from matn_app.answer_profile import load_answer_profile
    _, source = ingest_json(tmp_path, {'finding': 'Unemployment declined to 7.5 percent nationally.'})
    work = tmp_path / 'answer'; seen = []

    def attempt(notebook, question, folder, **kwargs):
        if kwargs.get('direct', True):
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'verified-progress.json').write_text(json.dumps(dict(first_at=1.0, sentences=[dict(text='Off question.', at=1.0)])))
            return dict(state='answered', answer_plan=dict(answer_type='direct', sentences=[]), sentences=[],
                        withheld_off_question=[dict(text='Off question.')], receipts=[], app_calls=dict(generation=2, native=1)), []
        seen.append((work / 'verified-progress.json').exists())  # background drafting starts here
        return dict(state='insufficient_evidence', sentences=[], receipts=[], app_calls=dict(generation=1, native=0)), []
    monkeypatch.setattr(evidence, '_notebook_answer', attempt)
    value = evidence.answer(dict(question='What was unemployment in Alexandria?', catalogs=[source['catalog']],
                                 notebooks=['fixture.db'], workdir=str(work),
                                 answer_profile=dict(load_answer_profile(),answer_path='v2')))
    assert seen == [False] and not (work / 'verified-progress.json').exists() and not value['citations']
