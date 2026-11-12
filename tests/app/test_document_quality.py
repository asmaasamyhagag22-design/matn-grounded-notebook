import json
import http.client
import pytest
from pathlib import Path


@pytest.fixture(autouse=True)
def isolated_hybrid(monkeypatch):
    # These orchestration tests fake the generator/native verifier; embeddings
    # must be fake too. Real hybrid inference is measured separately.
    monkeypatch.setattr('matn_app.answer_retrieval.HybridSearch._vectors',lambda self,texts:[[1.0]+[0.0]*1023 for t in texts])
    monkeypatch.setattr('matn_app.answer_retrieval.HybridSearch._release',lambda self:None)


class Counter:
    def __call__(self,prompt):return 100
    def close(self):pass


def test_salience_model_only_ranks_ids_then_code_verifies_exact_copies(tmp_path,monkeypatch):
    from tests.verification.test_rules import doc
    from matn_app.evidence import _pdf_catalog
    from matn_verification.contracts import Check
    from matn_chat.generation import LocalGenerator
    from matn_chat.engine import MiniCheck
    events=[]
    texts=[f'Agency {name} should assess operational risks before adopting a new system.' for name in ('Alpha','Beta','Gamma','Delta','Epsilon','Zeta')]
    document=doc(*texts)
    def generate(self,body):
        events.append('rank')
        ids=body['format']['properties']['ranking']['items']['enum']
        return dict(done=True,done_reason='stop',response=json.dumps(dict(ranking=list(reversed(ids)),publisher=None,date=None,type=None)))
    monkeypatch.setattr(LocalGenerator,'generate',generate)
    monkeypatch.setattr('eval.chat.token_budget.TokenCounter',Counter)
    monkeypatch.setattr('matn_app.runtime.drain_generator',lambda _:events.append('drain'))
    def native(self,text,evidence,target):
        events.append('verify')
        return Check(target=target,layer='L4',verdict='pass')
    monkeypatch.setattr(MiniCheck,'check',native)
    file=tmp_path/'source.pdf';file.write_bytes(b'%PDF-public-test')
    catalog,counts=_pdf_catalog(document,file,tmp_path/'ranked',fake=False)
    assert counts['generation_calls']==1 and len(catalog.units)==5
    assert catalog.units[0].text==texts[-1]
    assert all(u.text in texts and u.span.quote==u.text for u in catalog.units)
    assert events.index('rank')<events.index('drain')<events.index('verify')


def test_disconnected_local_call_recovers_once_then_surfaces_retryable_partial(tmp_path,monkeypatch):
    from tests.reading.pdf_fixtures import write_pdf
    from matn_app.evidence import ingest,answer
    from matn_chat.streaming import StreamingGenerator
    calls=[]
    def disconnected(*args,**kwargs):
        calls.append('attempt')
        raise http.client.RemoteDisconnected('connection closed before response')
    monkeypatch.setattr(StreamingGenerator,'generate_stream',disconnected)
    monkeypatch.setattr('matn_app.runtime.drain_generator',lambda _:None)
    monkeypatch.setattr('eval.chat.token_budget.TokenCounter',Counter)
    monkeypatch.setattr('matn_storyboard.runtime.sample_memory',lambda:dict(available_bytes=4*1024**3,l4_worker_rss_bytes=0))
    pdf=write_pdf(tmp_path/'source.pdf',b'BT /F1 12 Tf 72 600 Td (Workers should receive training before operating equipment.) Tj ET\n')
    source=ingest(dict(inputs=[str(pdf)],workdir=str(tmp_path/'ingest'),fake=True))
    folder=tmp_path/'answer'
    result=answer(dict(question='What should workers receive?',catalogs=[source['catalog']],notebooks=[source['notebook']],workdir=str(folder)))
    assert len(calls)==2 and result['retryable'] is True and result['failures']
    assert result['status']=='abstained' and 'Retry this question' in result['text']
    assert (folder/'recovered.jsonl').exists()
    assert result['metrics']['model_calls']==2


def test_verified_preview_is_source_bound_and_raw_number_invention_is_never_previewed(tmp_path,monkeypatch):
    from tests.reading.pdf_fixtures import write_pdf
    from matn_app.answer_profile import load_answer_profile
    from matn_app.evidence import ingest,answer
    from matn_chat.streaming import StreamingGenerator
    from matn_chat.engine import MiniCheck
    from matn_verification.contracts import Check
    monkeypatch.setattr('matn_app.runtime.drain_generator',lambda _:None)
    monkeypatch.setattr('eval.chat.token_budget.TokenCounter',Counter)
    monkeypatch.setattr('matn_storyboard.runtime.sample_memory',lambda:dict(available_bytes=4*1024**3,l4_worker_rss_bytes=0))
    monkeypatch.setattr(MiniCheck,'check',lambda self,text,evidence,target:Check(target=target,layer='L4',verdict='pass'))
    pdf=write_pdf(tmp_path/'source.pdf',b'BT /F1 12 Tf 72 600 Td (Workers should receive training before operating equipment.) Tj ET\n')
    source=ingest(dict(inputs=[str(pdf)],workdir=str(tmp_path/'ingest'),fake=True))
    for name,claim in [('good','Workers should receive training before they operate equipment.'),('copy','Workers should receive training before operating equipment.'),('bad','Workers should receive 999 percent training.')]:
        def generate(self,body,emit,**kwargs):
            handle=body['format']['properties']['sentences']['items']['properties']['handles']['items']['enum'][0]
            if 'answer_type' in body['format']['properties']:
                return dict(done=True,done_reason='stop',thinking='',response=json.dumps(dict(answer_type='direct',sentences=[dict(handles=[handle],part=0)])))
            return dict(done=True,done_reason='stop',thinking='',response=json.dumps(dict(sentences=[dict(claim=claim,handles=[handle],part=0)])))
        monkeypatch.setattr(StreamingGenerator,'generate_stream',generate)
        folder=tmp_path/name
        result=answer(dict(question='What should workers receive?',catalogs=[source['catalog']],notebooks=[source['notebook']],
                           workdir=str(folder),answer_profile=dict(load_answer_profile(),answer_path='v2')))
        progress=folder/'verified-progress.json'
        if name=='good':
            assert progress.exists() and result['status']=='answered'
        if name in ('copy','bad'):
            assert not progress.exists() and not result['citations']
        if progress.exists():
            value=json.loads(progress.read_bytes())
            assert value['first_at'] and all(s['status']=='verified' and s['binding'] and s['spans'] for s in value['sentences'])
            assert all('999' not in s['text'] for s in value['sentences'])
        assert '999' not in result['text']


def test_question_during_first_upload_does_not_start_research(tmp_path,monkeypatch):
    import threading,time
    from matn_app.service import App
    app=App(tmp_path/'app',fake=True);started=threading.Event();release=threading.Event()
    conversation=app.store.create()['id']
    monkeypatch.setattr(app,'_plan',lambda *a:(_ for _ in ()).throw(AssertionError('Must not plan research')))
    try:
        app.jobs.submit(conversation,'Reading files',lambda j,e:(started.set(),release.wait(3)))
        assert started.wait(1)
        job=app.action(conversation,dict(text='What are the findings?'))
        limit=time.monotonic()+2
        while time.monotonic()<limit:
            state=app.store.get(conversation)
            if next(j for j in state['jobs'] if j['id']==job['id'])['status']=='complete':break
            time.sleep(.01)
        assert not state['plans']
        assert state['messages'][-1]['result']['status']=='processing'
        assert state['messages'][-1]['result']['retryable']
    finally:
        release.set();app.close()
