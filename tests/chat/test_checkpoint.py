import time
import pytest
from eval.chat.collect import CachedGeneration
from tests.chat.test_engine import Generator,answer


def test_generation_checkpoint_reuses_exact_raw_response_without_new_call(tmp_path):
    g=Generator(answer());c=CachedGeneration(tmp_path,g,deadline=time.time()+60,binding='binding')
    body={'prompt':'q','model':'qwen3.5:9b'}
    raw=c.generate(body);assert c.generate(body)==raw and len(g.calls)==1
    again=CachedGeneration(tmp_path,Generator(),deadline=time.time()+60,binding='binding')
    assert again.generate(body)==raw and again.cache_hits==1


def test_expired_cap_never_calls_model(tmp_path):
    g=Generator(answer());c=CachedGeneration(tmp_path,g,deadline=time.time()-1,binding='b')
    with pytest.raises(TimeoutError):c.generate({'prompt':'q'})
    assert not g.calls


def test_corrupted_checkpoint_is_never_silently_replaced(tmp_path):
    g=Generator(answer());c=CachedGeneration(tmp_path,g,deadline=time.time()+60,binding='b');body={'prompt':'q'}
    c.generate(body)
    p=next(p for p in tmp_path.glob('*.json') if not p.name.endswith('.input.json'));p.write_text('{}')
    with pytest.raises((ValueError,KeyError)):c.generate(body)
    assert p.read_text()=='{}' and len(g.calls)==1


def test_collection_resume_uses_completed_question_without_retrieval_or_generation(tmp_path,monkeypatch):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    import eval.chat.collect as c
    from tests.chat.test_engine import doc,Retriever,Generator,answer,Pass
    from matn_chat.engine import ChatEngine
    monkeypatch.chdir(tmp_path)
    source=Path('out/vnr-d2/confirmation.sqlite');source.parent.mkdir(parents=True);source.write_bytes(b'fixture-index')
    for name in ['out/rag-core/part2/query-cache.json','out/vnr-d2/query-cache.json']:
        p=Path(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
    d=doc('Revenue was 12 percent.');snapshot=tmp_path/'snapshot.json';snapshot.write_text(d.model_dump_json())
    q=dict(id='q1',question='q',split='tune',cohort='frozen60',source='fixture')
    class R(Retriever):
        def __init__(self):super().__init__(d);self.db=SimpleNamespace(close=lambda:None);self.queries=0;self.query_vectors={}
        def source_ids(self,n):return ['source1']
        def query(self,*a,**kw):
            self.queries+=1
            if self.queries>1:raise AssertionError('completed question queried again')
            return super().query(*a,**kw)
    r=R()
    class G(Generator):
        def __init__(self):super().__init__(answer())
    monkeypatch.setattr(c,'questions',lambda:[q]);monkeypatch.setattr(c,'integrity',lambda root:None)
    monkeypatch.setattr(c,'load_documents',lambda:{'fixture':d});monkeypatch.setattr(c,'DEV_PATHS',{'fixture':str(snapshot)})
    monkeypatch.setattr(c,'ReadOnlyNotebook',lambda p:r);monkeypatch.setattr(c,'Search',lambda repo,embed:repo)
    monkeypatch.setattr(c,'query_cache',lambda:{});monkeypatch.setattr(c,'LocalGenerator',G)
    monkeypatch.setattr(c,'baseline',lambda:{})
    monkeypatch.setattr(c,'ChatEngine',lambda search,docs,generator:ChatEngine(search,docs,generator=generator,entailment=Pass(),clock=lambda:0.))
    first=c.collect(tmp_path/'run',cap_seconds=60)
    saved=(tmp_path/'run/questions/q1.json').read_bytes()
    second=c.collect(tmp_path/'run',cap_seconds=60)
    assert first['completed_question_checkpoints']==second['completed_question_checkpoints']==1
    assert r.queries==1 and (tmp_path/'run/questions/q1.json').read_bytes()==saved
