import pytest
from jsonschema import Draft202012Validator, ValidationError
from matn_chat.generation import payload
from tests.chat.test_engine import doc,build_handles,prepare,Generator,answer,Retriever,Pass
from matn_chat.engine import ChatEngine


def test_c1b_decode_enum_prefix_residency_and_context():
    hs=build_handles((doc('Revenue was 12 percent.'),),prepare(doc('Revenue was 12 percent.'))[1])
    first=payload('q',hs);redraft=payload('q',hs,[{'slot':0,'failure_codes':['x']}])
    assert first['options']['num_ctx']==16384
    assert first['keep_alive']=='60m' and first['truncate'] is False
    assert redraft['prompt'].startswith(first['prompt'])
    for h in ['forged-block-id','s999','Revenue was 12 percent.']:
        with pytest.raises(ValidationError):Draft202012Validator(first['format']).validate(answer(handle=h))
    Draft202012Validator(first['format']).validate(answer())


def test_empty_enum_only_allows_insufficient():
    schema=payload('q',{})['format']
    Draft202012Validator(schema).validate({'sentences':[]})
    with pytest.raises(ValidationError):Draft202012Validator(schema).validate(answer())


def test_memory_guard_retries_once_after_unloading_and_defers_without_generation():
    from matn_chat.memory import MemoryGuard
    calls=[];samples=iter([{'available_bytes':10},{'available_bytes':20}])
    guard=MemoryGuard(sample=lambda:next(samples))
    assert guard.check(lambda:calls.append('close')) is False
    assert calls==['close'] and len(guard.samples)==2
    d=doc('Revenue was 12 percent.');g=Generator(answer())
    e=ChatEngine(Retriever(d),(d,),generator=g,entailment=Pass(),memory_guard=MemoryGuard(sample=lambda:{'available_bytes':0}))
    r=e.ask('n',['source1'],'q')
    assert r['state']=='deferred_memory' and not g.calls


def test_memory_guard_recovers_and_records_rss():
    from matn_chat.memory import MemoryGuard,sample_memory
    samples=iter([{'available_bytes':0},{'available_bytes':2*1024**3}]);g=MemoryGuard(sample=lambda:next(samples))
    assert g.check(lambda:None) and len(g.samples)==2
    s=sample_memory();assert s['available_bytes']>0 and 'ollama_runner_rss_bytes' in s and 'l4_worker_rss_bytes' in s


def test_per_attempt_ollama_duration_and_verification_recorded():
    class G(Generator):
        def generate(self,p):return {**super().generate(p),'prompt_eval_duration':2000000000,'eval_duration':3000000000}
    d=doc('Revenue was 12 percent.');e=ChatEngine(Retriever(d),(d,),generator=G(answer()),entailment=Pass())
    assert e.ask('n',['source1'],'q')['state']=='answered'
    assert e.trace[0]['timings']['prompt_eval_seconds']==2
    assert e.trace[0]['timings']['eval_seconds']==3
    assert e.trace[0]['timings']['verification_seconds']>=0


def test_context_overflow_fails_loudly_before_model_call():
    d=doc('Revenue was 12 percent.');g=Generator(answer())
    e=ChatEngine(Retriever(d),(d,),generator=g,entailment=Pass(),token_counter=lambda p:16384)
    r=e.ask('n',['source1'],'q')
    assert r['state']=='error' and r['error']=='context_budget_overflow' and not g.calls


def test_guarded_owned_l4_stays_resident_between_calls(monkeypatch):
    import matn_chat.engine as m
    from matn_chat.memory import MemoryGuard
    class Resident(Pass):
        def __init__(self):self.closed=0
        def close(self):self.closed+=1
    l4=Resident();monkeypatch.setattr(m,'MiniCheck',lambda:l4)
    d=doc('Revenue was 12 percent.');g=Generator(answer(),answer())
    e=ChatEngine(Retriever(d),(d,),generator=g,memory_guard=MemoryGuard(sample=lambda:{'available_bytes':3*1024**3}))
    e.ask('n',['source1'],'q');e.ask('n',['source1'],'q')
    assert l4.closed==0


def test_packet_resolves_known_handle_even_when_schema_error_prevents_verification():
    from eval.chat.realistic import render_packet
    row={'id':'q','cohort':'frozen60','split':'tune','question':'q','response':{'state':'error'},
         'handles':{'s1':{'citations':[{'quote':'exact evidence'}]}},
         'trace':[{'attempt':0,'parsed':answer(),'error':{'code':'schema_invalid'}}]}
    assert 'exact evidence' in render_packet([row])


def test_memory_deferred_during_redraft_is_not_generic_error():
    from matn_chat.engine import ChatFailure
    class G(Generator):
        def generate(self,p):
            if self.calls:raise ChatFailure('deferred_memory')
            return super().generate(p)
    d=doc('Revenue was 12 percent.');e=ChatEngine(Retriever(d),(d,),generator=G(answer('Revenue was 99 percent.')),entailment=Pass())
    assert e.ask('n',['source1'],'q')['state']=='deferred_memory'


def test_c1b_summary_prefix_timings_and_peak_memory():
    from eval.chat.c1b_summary import summarize_run
    row={'cohort':'frozen60','response':{'state':'insufficient_evidence','sentences':[],'dropped_sentences':1,'timings':{}},
         'trace':[{'attempt':0,'timings':{'prompt_eval_seconds':10.,'eval_seconds':3.,'verification_seconds':1.}},
                  {'attempt':1,'timings':{'prompt_eval_seconds':2.,'eval_seconds':4.,'verification_seconds':1.}}]}
    result=summarize_run([row],[{'available_bytes':100,'ollama_runner_rss_bytes':200,'l4_worker_rss_bytes':30}])
    assert result['prefix_cache']['pairs'][0]['redraft_to_first_ratio']==.2
    assert result['memory']['peak_combined_runner_l4_rss_bytes']==230


def test_c1b_collector_smoke_continues_and_resume_never_generates(tmp_path,monkeypatch):
    import json,time
    from pathlib import Path
    from types import SimpleNamespace
    import eval.chat.c1b as c
    d=doc('Revenue was 12 percent.')
    monkeypatch.chdir(tmp_path)
    source=Path('out/vnr-d2/confirmation.sqlite');source.parent.mkdir(parents=True);source.write_bytes(b'index')
    for name in ['out/rag-core/part2/query-cache.json','out/vnr-d2/query-cache.json']:
        p=Path(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
    snapshot=tmp_path/'snapshot.json';snapshot.write_text(d.model_dump_json())
    root=tmp_path/'run';root.mkdir();(root/'start.json').write_text(json.dumps({'started_wall':time.time(),'deadline_wall':time.time()+60}))
    (root/'preflight.json').write_text(json.dumps({'questions':[{}]*99,'overflows':[],'embedding_calls':0}))
    qs=[dict(id=f'q{i}',question='q',split='tune',cohort='frozen60',source=f's{i}') for i in range(3)]
    class R(Retriever):
        def __init__(self):super().__init__(d);self.db=SimpleNamespace(close=lambda:None);self.query_vectors={};self.queries=0
        def source_ids(self,n):return ['source1']
        def query(self,*a,**kw):self.queries+=1;return super().query(*a,**kw)
    class G(Generator):
        def __init__(self):super().__init__(answer(),answer(),answer())
        def request(self,path):assert path=='/api/ps';return {'models':[]}
    class Counter:
        def __call__(self,p):return len(p)
        def close(self):pass
    r=R();g=G()
    monkeypatch.setattr(c,'questions',lambda:qs);monkeypatch.setattr(c,'integrity',lambda root:None)
    monkeypatch.setattr(c,'load_documents',lambda:{'fixture':d});monkeypatch.setattr(c,'DEV_PATHS',{'fixture':str(snapshot)})
    monkeypatch.setattr(c,'ReadOnlyNotebook',lambda p:r);monkeypatch.setattr(c,'Search',lambda repo,embed:repo)
    monkeypatch.setattr(c,'query_cache',lambda:{});monkeypatch.setattr(c,'LocalGenerator',lambda:g)
    monkeypatch.setattr(c,'TokenCounter',Counter);monkeypatch.setattr(c,'baseline',lambda:{})
    class Worker(Pass):
        def close(self):pass
    monkeypatch.setattr(c,'ChatEngine',lambda search,docs,**kw:ChatEngine(search,docs,**kw,entailment=Worker()))
    # Existing CachedGeneration checks the concrete LocalGenerator class in its own module.
    assert c.collect(root,cap_seconds=60)['completed_question_checkpoints']==3
    saved={p.name:p.read_bytes() for p in (root/'questions').glob('*.json')}
    assert c.collect(root,cap_seconds=60)['completed_question_checkpoints']==3
    assert r.queries==3 and len(g.calls)==3
    assert {p.name:p.read_bytes() for p in (root/'questions').glob('*.json')}==saved
    assert json.loads((root/'smoke.json').read_text())['errors']==0


def test_memory_detects_llama_cpp_runner_and_ignores_shell_mentions(tmp_path):
    from matn_chat.memory import sample_memory
    (tmp_path/'meminfo').write_text('MemAvailable: 100 kB\n')
    for pid,argv,rss in [('1',['/usr/local/lib/ollama/llama-server','--offline'],20),
                         ('2',['/usr/local/bin/ollama','runner','--model','x'],30),
                         ('3',['python','-m','matn_verification.l4_worker','x'],40),
                         ('4',['bash','-c','echo ollama runner matn_verification.l4_worker'],90)]:
        p=tmp_path/pid;p.mkdir();(p/'cmdline').write_bytes(b'\0'.join(x.encode() for x in argv)+b'\0');(p/'status').write_text(f'VmRSS: {rss} kB\n')
    row=sample_memory(tmp_path)
    assert row['ollama_runner_rss_bytes']==50*1024 and row['l4_worker_rss_bytes']==40*1024
