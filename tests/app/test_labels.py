"""Owner decisions persist independently; AI cannot bias the initial judgment."""
import json
import pytest
from matn_app.labels import LabelStore
from matn_app.store import write


def item():
    return dict(id='example',group='answer-development',text='A generated statement.',question='What happened?',
        source_title='Public report',source_type='PDF',span=dict(block_id='b',start=0,end=15,quote='Exact evidence.'),spans=[],context='Exact evidence. More context.',
        receipt=dict(status='rejected'),ai_verdict=dict(error=True,borderline=False,reason='Hidden until decision'))


def test_ai_and_verifier_are_hidden_until_owner_decides_and_each_click_persists(tmp_path):
    store=LabelStore(tmp_path);store.merge([item()]);first=store.public()['items'][0]
    assert 'ai_verdict' not in first and 'receipt' not in first and 'trace' not in first
    store.submit('example','Correct','Supported after reading context')
    restored=LabelStore(tmp_path);public=restored.public()['items'][0]
    assert public['owner_label']['note']=='Supported after reading context'
    assert public['ai_verdict']['reason']=='Hidden until decision'
    assert restored.summary()['false_blocks']['rate']==1
    assert restored.summary()['owner_labelled']==1
    assert json.loads((tmp_path/'owner-labels.json').read_text())['history']
    store.submit('example','Skip');assert 'ai_verdict' not in store.public()['items'][0]
    assert store.summary()['pending']==1 and store.summary()['owner_labelled']==0


def test_labels_cannot_be_reused_for_changed_evidence_or_waive_fixed_acceptance_gates(tmp_path):
    store=LabelStore(tmp_path);store.merge([item()])
    with pytest.raises(ValueError,match='LABEL_ITEM_CHANGED'):store.merge([dict(item(),text='Changed statement.')])
    write(tmp_path/'verdict-bases.json',dict(trial=dict(group='answer-development',fixed_gates_pass=True),historical=dict(group='answer-development',fixed_gates_pass=False)))
    assert store.summary()['verdicts']['trial']['status']=='FAIL'
    store.submit('example','Correct')
    assert store.summary()['verdicts']['trial']['status']=='PASS'
    assert store.summary()['verdicts']['historical']['status']=='FAIL'


def test_http_labels_use_existing_authenticated_local_api(tmp_path,monkeypatch):
    import threading
    from matn_app import labels
    from matn_app.server import make_server
    from matn_app.service import App
    from matn_app.smoke import _Client
    monkeypatch.setattr(labels,'DATA_ROOT',tmp_path)
    store=LabelStore(tmp_path/'labels');store.merge([item()])
    app=App(tmp_path/'app',fake=True);server=make_server(app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        client=_Client(server)
        assert 'ai_verdict' not in client.json('/api/labels')['items'][0]
        result=client.json('/api/labels',dict(id='example',decision='Wrong',note='Wrong actor'))
        assert result['saved'] and app.evaluation()['owner_labels']['owner_labelled']==1
        with client.open('/labels/') as r:assert b'Your judgment, saved.' in r.read()
        assert (tmp_path/'labels/index.html').is_file()
    finally:server.shutdown();server.server_close();thread.join(5);app.close()


def test_rule_specific_borderline_and_owner_decided_direct_answers(tmp_path):
    from scripts.recompute_verdicts import recompute
    a=dict(item(),id='a1',group='answers-v2',ai_verdict=dict(error=False,borderline=True))
    b=dict(item(),id='b1',group='answers-v2',ai_verdict=dict(error=False,borderline=False))
    store=LabelStore(tmp_path);store.merge([a,b])
    direct=dict(minimum=2,first_sentence=dict(Q1='a1',Q2='b1'),ai_direct=dict(Q1=True,Q2=False))
    write(tmp_path/'verdict-bases.json',dict(v2=dict(group='answers-v2',fixed_gates_pass=True,borderline_is_error=False,direct_answers=direct),
                                            old=dict(group='answers-v2',fixed_gates_pass=True)))
    value=recompute(tmp_path)['verdicts']
    assert value['v2']['status']=='FAIL' and value['v2']['direct_answers']==1 and value['v2']['AI_only']==2
    assert value['old']['status']=='FAIL' and value['old']['borderline']==1
    store.submit('b1','Correct')
    value=recompute(tmp_path)['verdicts']
    assert value['v2']['status']=='PASS' and value['v2']['owner_labelled']==1 and value['v2']['direct_answers']==2
    assert value['old']['status']=='FAIL'
    assert json.loads((tmp_path/'verdicts.json').read_text())['owner_labelled']==1
