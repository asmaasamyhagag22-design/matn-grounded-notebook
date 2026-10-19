"""Chat gates over native stored structures and cached generation; no inference."""
import copy
import json
import subprocess
import sys
import pytest
from matn_chat.handles import build_handles
from matn_chat.engine import ChatEngine, INSUFFICIENT
from matn_chat.generation import payload, LocalGenerator, GENERATOR_DIGEST
from matn_verification.contracts import Check
from matn_verification.rules import fingerprint
from tests.verification.test_rules import doc
from matn_rag.ingest import prepare


class Retriever:
    def __init__(self,d):
        self.document=d;self.repo=self
    def source_rows(self,notebook):return [dict(id='source1',doc_id=self.document.doc_id,metadata=json.dumps({'fingerprint':fingerprint(self.document)}))]
    def validate_selection(self,notebook,selected):
        if selected!=['source1']:raise ValueError('selection')
    def query(self,notebook,selected,question,**kw):
        assert kw==dict(mode='focused',depth=10,ablation='no-prefix')
        return dict(hits=prepare(self.document)[1],mode='focused',ablation='no-prefix')


class Generator:
    def __init__(self,*outputs):self.outputs=list(outputs);self.calls=[]
    def generate(self,p):
        self.calls.append(p)
        value=self.outputs[len(self.calls)-1]
        return dict(done=True,done_reason='stop',response=json.dumps(value),thinking='')


class Pass:
    def check(self,text,evidence,target):return Check(target=target,layer='L4',verdict='pass')


def answer(text='Revenue was 12 percent.',handle='s1'):
    return {'sentences':[{'text':text,'handles':[handle]}]}


def engine(d,g):return ChatEngine(Retriever(d),(d,),generator=g,entailment=Pass(),clock=lambda:0.)


def test_handles_copy_authoritative_sentence_spans_not_chunk_separators():
    d=doc('Revenue was 12 percent. Costs were 8 percent.','Employment increased.')
    hs=build_handles((d,),prepare(d)[1])
    assert list(hs)==['s1','s2','s3']
    assert hs['s1']['citations'][0]['quote']=='Revenue was 12 percent. '
    assert hs['s2']['citations'][0]['start']==len('Revenue was 12 percent. ')
    assert all('\n\n' not in h['text'] for h in hs.values())
    assert all(c['bbox'] and c['pdf_page_index']==0 for h in hs.values() for c in h['citations'])


def test_continued_adjacent_sentence_has_one_handle_without_separator_evidence():
    d=doc('Revenue increased because','demand increased.','Costs decreased.')
    hs=build_handles((d,),prepare(d)[1]);assert len(hs)==2
    assert len(hs['s1']['citations'])==2
    assert hs['s1']['text']=='Revenue increased because demand increased.'
    assert all(c['quote']!='\n\n' for c in hs['s1']['citations'])


def test_excluded_block_and_unretrieved_gap_cannot_form_a_handle():
    d=doc('Revenue increased because','intervening content','demand increased.')
    hits=prepare(d)[1]
    hits=copy.deepcopy(hits)
    for h in hits:h['evidence']=[s for s in h['evidence'] if s['payload']['block_id']!=d.elements[1].block.block_id]
    hs=build_handles((d,),hits)
    assert all(len(h['citations'])==1 for h in hs.values())
    assert 'intervening content' not in str(hs)


def test_handle_cannot_expand_partial_retrieval_to_whole_sentence():
    d=doc('Revenue was 12 percent.')
    hits=copy.deepcopy(prepare(d)[1]);hits[0]['evidence'][0]['payload']['start']=8
    assert build_handles((d,),hits)=={}


def test_prompt_contract_has_handles_only_and_explicit_settings():
    d=doc('Revenue was 12 percent.');hs=build_handles((d,),prepare(d)[1]);p=payload('What?',hs)
    assert p['stream'] is False and p['think'] is False and p['truncate'] is False
    assert p['options']['temperature']==0 and p['options']['num_ctx']==16384
    assert p['format']['properties']['sentences']['items']['properties']['handles']['maxItems']==3
    assert d.elements[0].block.block_id not in p['prompt']
    assert 'block_id' not in str(p['format']) and 'offset' not in str(p['format'])


def test_verified_only_with_exact_code_copied_citations():
    d=doc('Revenue was 12 percent.');g=Generator(answer());e=engine(d,g)
    r=e.ask('n',['source1'],'What revenue?')
    assert r['state']=='answered' and r['sentences'][0]['text']=='Revenue was 12 percent.'
    assert r['sentences'][0]['citations'][0]['block_id']==d.elements[0].block.block_id
    assert r['sentences'][0]['citations'][0]['quote']==d.elements[0].block.text
    assert r['receipts'][0]['receipt']['status']=='verified'
    assert r['dropped_sentences']==0 and len(g.calls)==1


@pytest.mark.parametrize('handle',['s999','sha256-forged','s0'])
def test_unknown_or_forged_handles_reject_and_never_leak_candidate(handle):
    d=doc('Revenue was 12 percent.');g=Generator(answer('FORGED CLAIM',handle),{'sentences':[]});e=engine(d,g)
    r=e.ask('n',['source1'],'q')
    assert r['state']=='insufficient_evidence' and r['dropped_sentences']==1
    assert r['receipts'][0]['receipt']['status']=='rejected'
    assert 'FORGED CLAIM' not in json.dumps(r)
    assert e.trace[0]['sentences'][0]['text']=='FORGED CLAIM'


@pytest.mark.parametrize('bad',[{'text':'free text'},{'sentences':[{'text':'Claim','handles':[]}]},{'sentences':[{'text':'Claim','handles':['s1'],'start':0}]}])
def test_schema_invalid_is_error_without_redraft(bad):
    d=doc('Revenue was 12 percent.');g=Generator(bad);r=engine(d,g).ask('n',['source1'],'q')
    assert r['state']=='error' and not r['sentences'] and len(g.calls)==1


def test_only_failed_sentence_is_redrafted_once_with_same_handles():
    d=doc('Revenue was 12 percent.','Costs were 8 percent.')
    first={'sentences':[answer()['sentences'][0],answer('Costs were 99 percent.','s2')['sentences'][0]]}
    g=Generator(first,answer('Costs were 8 percent.','s2'));e=engine(d,g);r=e.ask('n',['source1'],'q')
    assert r['state']=='answered' and len(r['sentences'])==2 and r['dropped_sentences']==0
    assert len(g.calls)==2 and 'number_not_in_evidence' in g.calls[1]['prompt']
    assert e.trace[1]['redraft_slots']==[1]
    assert r['discarded_candidates']==1


def test_redraft_bound_and_empty_answer_paths():
    d=doc('Revenue was 12 percent.');g=Generator(answer('Revenue was 99 percent.'),answer('Revenue was 98 percent.'))
    r=engine(d,g).ask('n',['source1'],'q')
    assert len(g.calls)==2 and not r['sentences'] and r['state']=='insufficient_evidence'
    assert r['message']==INSUFFICIENT and r['dropped_sentences']==1
    g=Generator({'sentences':[]});r=engine(d,g).ask('n',['source1'],'q')
    assert len(g.calls)==1 and r['state']=='insufficient_evidence'


def test_missing_l4_never_displays_text():
    from matn_verification.contracts import NotRunEntailment
    d=doc('Revenue was 12 percent.');g=Generator(answer(),{'sentences':[]})
    r=ChatEngine(Retriever(d),(d,),generator=g,entailment=NotRunEntailment()).ask('n',['source1'],'q')
    assert not r['sentences']


def test_incomplete_generation_fails_closed():
    class Incomplete:
        def generate(self,p):return dict(done=False,response=json.dumps(answer()),done_reason='length')
    d=doc('Revenue was 12 percent.');assert engine(d,Incomplete()).ask('n',['source1'],'q')['state']=='error'


def test_remote_generation_endpoint_refused():
    with pytest.raises(ValueError):LocalGenerator('https://outside.invalid:11434')


def test_two_process_determinism_with_cached_outputs_and_fixed_clock():
    code="from tests.chat.test_engine import *;from matn_rag.contracts import canonical;d=doc('Revenue was 12 percent.');print(canonical(engine(d,Generator(answer())).ask('n',['source1'],'q')).decode())"
    assert subprocess.check_output([sys.executable,'-c',code])==subprocess.check_output([sys.executable,'-c',code])


def test_killed_worker_cleanup_does_not_escape_fail_closed_api(monkeypatch):
    from matn_chat.engine import MiniCheck
    class Killed:
        def close(self):raise BrokenPipeError('worker died')
    m=MiniCheck();m.adapter=Killed();m.close()
    assert m.adapter is None


def test_repair_cannot_duplicate_an_already_kept_sentence():
    d=doc('Revenue was 12 percent.','Costs were 8 percent.')
    first={'sentences':[answer()['sentences'][0],answer('Costs were 99 percent.','s2')['sentences'][0]]}
    r=engine(d,Generator(first,answer())).ask('n',['source1'],'q')
    assert len(r['sentences'])==1 and r['dropped_sentences']==1


def test_generator_digest_mismatch_never_calls_generate(monkeypatch):
    g=LocalGenerator();paths=[]
    def request(path,data=None):
        paths.append(path)
        return {'models':[{'name':'qwen3.5:9b','digest':'changed'}]}
    monkeypatch.setattr(g,'request',request)
    with pytest.raises(ValueError,match='DIGEST'):g.generate(payload('q',{}))
    assert paths==['/api/tags']


def test_schema_invalid_redraft_counts_all_identifiable_discarded_candidates():
    d=doc('Revenue was 12 percent.','Costs were 8 percent.')
    first={'sentences':[answer()['sentences'][0],answer('Costs were 99 percent.','s2')['sentences'][0]]}
    bad={'sentences':[{'text':'Costs were 8 percent.','handles':[]}]}
    r=engine(d,Generator(first,bad)).ask('n',['source1'],'q')
    assert r['state']=='error' and r['sentences']==[]
    assert r['dropped_sentences']==2 and r['discarded_candidates']==3
