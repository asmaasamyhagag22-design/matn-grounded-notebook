"""Offline structural contracts only. Every semantic engine here is Fake L4."""
from copy import deepcopy
import hashlib
import json
import time
import pytest
from matn_chat.readiness import write
from matn_research.models import LIMITS
from matn_research.providers import qualify
from matn_research.workflow import bind_analysis, analysis_gaps, cost_plan
from matn_research.reader import read_source
from matn_storyboard.planning import attach, payload, validate
from matn_storyboard.unit_composition import ComposedWorkflow
from eval.research.fixtures import FakeNative
from tests.storyboard.test_planning import fixture


def multi():
    d,p,a,_ = fixture('Roots need soil. Trees may shade seating. Trees may need watering. Shade may change with season.', target=1, context_sources=[])
    # Four real sentence supports in this declared fixture, split over four facets.
    p['task']['research_selection_mode']='bounded-multiple-v1'
    p['task']['required_points']=[dict(id='point'+f['id'],facet=f['id'],description='Fixture planning detail',critical=True) for f in p['task']['facets']]
    units=[(k,u) for k,u in p['content_units'].items() if u.get('state')=='bounded']
    assert len(units)>=4
    items=[]
    for f,(key,u) in zip(p['task']['facets'],units):
        items.append(dict(facet=f['id'], points=['point'+f['id']], support=key, state='reviewed', reason='Fixture support selected for a structural test',
                          context_sources=[],dependencies=[],conflict=''))
    return d,p,items


def test_missing_evidence_needs_no_fabricated_handle_and_records_action():
    _,p,items=multi()
    items[0].update(support=None,state='unknown',reason='No evidence of this requirement',
                    next_question='How is seating comfort evaluated?',next_action='Search a complementary primary source')
    pack=bind_analysis(p,dict(items=items))
    assert len(pack['content_plan']['items'])==3
    assert pack['missing_requirements'][0]['reason']=='No evidence of this requirement'
    assert analysis_gaps(pack,dict(items=items))[0]['next_question']=='How is seating comfort evaluated?'
    broken=deepcopy(items);broken[0]['state']='reviewed'
    with pytest.raises(ValueError,match='MISSING_EVIDENCE'):bind_analysis(p,dict(items=broken))
    broken=deepcopy(items);broken[0]['next_question']=''
    with pytest.raises(ValueError,match='NEXT_ACTION'):bind_analysis(p,dict(items=broken))


def test_multiple_atoms_are_separate_and_wrong_support_cannot_borrow():
    d,p,items=multi()
    # Select two distinct supports for the first facet, omit support for last.
    extra=deepcopy(items.pop());extra['facet']=items[0]['facet'];extra['points']=items[0]['points'];items.insert(1,extra)
    missing=dict(facet=p['task']['facets'][-1]['id'],support=None,state='unknown',reason='No independent detail available',
                 context_sources=[],dependencies=[],conflict='',next_question='What detail remains missing?',next_action='Search primary evidence')
    pack=bind_analysis(p,dict(items=items+[missing]))
    schema=payload(pack)['format']; assert schema['properties']['slides']['minItems']==4
    assert schema['properties']['slides']['items']['properties']['units']['maxItems']==2
    draft=dict(slides=[dict(facet=f['id'],units=[dict(text=pack['content_units'][i['support']]['support']['quote'],support=i['support'],context=dict(text='',sources=[]))
                             for i in pack['content_plan']['items'] if i['facet']==f['id']]) for f in p['task']['facets']])
    flow=ComposedWorkflow([d],pack,FakeNative());v=flow.build(draft)
    assert len(v['slides'][0]['checks'])==2
    bad=deepcopy(draft);bad['slides'][0]['units'][1]['support']=draft['slides'][1]['units'][0]['support']
    with pytest.raises(ValueError,match='SUPPORT_SELECTION'):flow.build(bad)
    bad=deepcopy(draft);bad['slides'][0]['units']*=2
    with pytest.raises(ValueError,match='UNIT_LIMIT'):flow.build(bad)


def test_each_atom_failure_vetoes_slide_before_composition():
    d,p,items=multi();extra=deepcopy(items.pop());extra['facet']=items[0]['facet'];extra['points']=items[0]['points'];items.insert(1,extra)
    pack=attach(p,[dict(i,points=[q['id'] for q in p['task']['required_points'] if q['facet']==i['facet']]) for i in items],reviewer='Fixture',selection_mode='bounded-multiple-v1')
    draft=dict(slides=[dict(facet=f['id'],units=[dict(text=pack['content_units'][i['support']]['support']['quote'],support=i['support'],context=dict(text='',sources=[])) for i in items if i['facet']==f['id']]) for f in p['task']['facets']])
    draft['slides'][0]['units'][1]['text']='Trees cool every building in the country.'
    from matn_verification.contracts import Check
    class RejectWrong(FakeNative):
        def check(self,text,evidence,target):
            return Check(target=target,layer='L4',verdict='reject' if 'every building' in text else 'pass',reasons=('unsupported_statement',) if 'every building' in text else ())
    v=ComposedWorkflow([d],pack,RejectWrong()).build(draft)
    assert not v['slides'][0]['displayed'] and v['slides'][0]['composition']['status']=='not_run'


@pytest.mark.parametrize('paygo_limit,usage,expected',[(0,0,'READY'),(100,0,'BLOCKED'),(None,0,'BLOCKED'),(0,995,'BLOCKED')])
def test_usage_qualification_never_infers_payg_disabled_from_zero_usage(monkeypatch,paygo_limit,usage,expected):
    monkeypatch.setenv('TAVILY_API_KEY','SECRET_SENTINEL')
    value=dict(account=dict(current_plan='Researcher',plan_limit=1000,plan_usage=usage,paygo_usage=0,paygo_limit=paygo_limit),key=dict(limit=1000,usage=usage))
    result=qualify(usage=value)
    assert result['status']==expected and 'SECRET_SENTINEL' not in str(result)


def test_research_generation_cap_is_six_without_changing_legacy_default():
    from matn_research.runtime import ResearchCalls
    from matn_storyboard.runtime import Calls
    assert ResearchCalls.call_limit(None,'generation')==LIMITS['generation']==6
    assert ResearchCalls.call_limit(None,'native')==LIMITS['native']==64
    assert Calls.call_limit(None,'generation')==4
    assert LIMITS['edit_native_reserve']==8


def test_long_source_is_preserved_and_pdf_outline_can_reach_after_page_six(tmp_path):
    from tests.research.pdf_fixtures import pdf_bytes, text
    raw=pdf_bytes([text('Shade evaluation at the intended seating area.\n'*12,x=40) for _ in range(9)],
                  outline=[(1,'Introduction',1),(1,'Seating evaluation',8)])
    def fetch(url,**kwargs):return dict(body=raw,final_url=url,content_type='application/pdf',fetched_at=time.time(),redirects=[])
    r=read_source('https://fixture.example/a.pdf',tmp_path,fetch=fetch,limits=dict(download_bytes=4000000,fetch_seconds=25,pdf_pages=2,source_characters=1,pdf_query='seating evaluation'))
    assert r['status']=='complete',r
    assert r['coverage']['read_pages']==[7,8] and r['coverage']['preliminary_page_text_scans']==0
    assert r['coverage']['extracted_characters']>1


def test_duplicate_mirror_cannot_replace_canonical_citation(tmp_path):
    from matn_research.preview import render
    from tests.research.test_journey import journey
    journey(tmp_path)
    reads=json.loads((tmp_path/'reading-status.json').read_bytes())
    canonical=next(r for r in reads if r.get('independent'))
    mirror=dict(canonical,independent=False,url='https://mirror.example/copy',final_url='https://mirror.example/copy')
    write(tmp_path/'reading-status.json',reads+[mirror])
    version=json.loads((tmp_path/'v1.json').read_bytes())
    html=render(tmp_path,version)
    assert 'href="'+canonical['final_url']+'">HTML text block' in html
    assert 'href="https://mirror.example/copy">HTML text block' not in html


def test_runtime_actually_admits_fifth_sixth_and_rejects_seventh(monkeypatch,tmp_path):
    from matn_research.runtime import ResearchCalls
    from matn_storyboard.budget import open_ledger
    v=open_ledger(tmp_path,experiment=3000)
    v['drained']=True;v['calls']['generation']=4
    v['phase_guard']=dict(running={'command':['fixture']})
    write(tmp_path/'ledger.json',v)
    monkeypatch.setattr('matn_storyboard.budget.phase_checkpoint',lambda *a,**k:time.time()+2000)
    monkeypatch.setattr('matn_storyboard.runtime.sample_memory',lambda:dict(available_bytes=8*1024**3,l4_worker_rss_bytes=0))
    c=ResearchCalls(tmp_path)
    assert c.reserve('generation',{})['ordinal']==5
    v=json.loads(c.path.read_bytes());v['drained']=True;write(c.path,v)
    assert c.reserve('generation',{})['ordinal']==6
    v=json.loads(c.path.read_bytes());v['drained']=True;write(c.path,v)
    with pytest.raises(TimeoutError,match='CAP'):c.reserve('generation',{})


def test_saved_settings_are_data_never_shell_execution(monkeypatch,tmp_path):
    from matn_research.providers import load_settings
    monkeypatch.delenv('TAVILY_API_KEY',raising=False)
    p=tmp_path/'tavily.env';p.write_text('export TAVILY_API_KEY="SECRET_SENTINEL"\nUNRELATED=$(touch /tmp/forbidden)\n')
    result=load_settings(p)
    assert result['key_present'] and 'SECRET_SENTINEL' not in str(result)


def test_followup_comes_from_reading_gap_in_existing_analysis_call(tmp_path):
    from eval.research.fixtures import Generator,Provider,BRIEF,fetch,LABEL
    from matn_research.workflow import run
    class ReadGap(Generator):
        def generate(self,body):
            raw=super().generate(body)
            if 'items' in body['format']['properties']:
                value=json.loads(raw['response']);value['items'][-1].update(next_question='Which seating location should the monitoring measure?',next_action='Search complementary primary monitoring guidance')
                raw['response']=json.dumps(value)
            return raw
    p=Provider();g=ReadGap(unknown=True)
    run(tmp_path,BRIEF,provider=p,generator=g,native=FakeNative(),counter=lambda t:len(t)//4,fetch=fetch,classification=LABEL)
    assert len(p.calls)==5
    assert p.calls[-1].endswith('Which seating location should the monitoring measure?')
    assert 'evaluation limitations' not in p.calls[-1]


def test_null_key_limit_does_not_invent_a_cap_or_enable_payg(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY','SECRET_SENTINEL')
    value=dict(account=dict(current_plan='Researcher',plan_limit=1000,plan_usage=0,paygo_limit=0),key=dict(limit=None,usage=0))
    assert qualify(usage=value)['status']=='READY'
    value['account']['paygo_limit']=100
    assert qualify(usage=value)['status']=='BLOCKED'


def test_frozen_requirements_journey_builds_eight_separately_checked_atoms(tmp_path):
    from eval.research.fixtures import Generator,Provider,BRIEF,TEXTS,LABEL
    from matn_research.workflow import run
    texts=TEXTS+['Trees may shelter seating from direct sun.','Trees need sufficient rooting space.','Tree guards should be inspected.','Tree growth should be monitored.']
    requirements=dict(goal=BRIEF['goal'],audience=BRIEF['audience'],language='English',scope=BRIEF['scope'],
        facets=[dict(id='axis'+str(i),label='Fixture axis '+str(i),query='Fixture planning question '+str(i)) for i in range(4)],
        required_points=[dict(id='p'+str(i),facet='axis'+str(i//2),description='Explicit fixture detail '+str(i),critical=True) for i in range(8)])
    class Eight(Generator):
        def generate(self,body):
            if 'facets' in body['format']['properties']:return super().generate(body)
            self.calls.append(body)
            data=json.JSONDecoder().raw_decode(body['prompt'].split('\n',1)[1])[0]
            if 'items' in body['format']['properties']:
                catalog=data['sources'];items=[]
                segments={r['id']:r['text'] for r in data['segments']}
                active={f['id'] for f in data['facets']}
                for i,text in enumerate(texts):
                    if 'axis'+str(i//2) not in active: continue
                    row=next(r for r in catalog if segments[r['support_segment']].strip()==text)
                    items.append(dict(facet='axis'+str(i//2),support=row['handle'],state='reviewed',points=['p'+str(i)],reason='Explicit fixture point support',context_sources=[],dependencies=[],conflict=''))
                value=dict(items=items)
            else:
                rows=data['content'];value=dict(slides=[dict(facet=f['id'],units=[dict(text=r['support'],support=r['plan']['support'],context=dict(text='',sources=[])) for r in rows if r['plan']['facet']==f['id']]) for f in requirements['facets']])
            return dict(done=True,done_reason='stop',thinking='',response=json.dumps(value))
    def fetch(url,**kwargs):return dict(body=(''.join('<p>'+t+'</p>' for t in texts)).encode(),final_url=url,content_type='text/html',fetched_at=time.time(),redirects=[])
    result=run(tmp_path,BRIEF,requirements=requirements,provider=Provider(),generator=Eight(),native=FakeNative(),counter=lambda t:len(t)//4,fetch=fetch,classification=LABEL)
    assert result['displayed_slides']==4
    version=json.loads((tmp_path/'v1.json').read_bytes())
    assert sum(len(s['checks']) for s in version['slides'])==8
    assert all(len(s['checks'])==2 and s['composition']['status']=='verified' for s in version['slides'])


def test_explicit_bounded_free_budget_accepts_proven_credits_without_inventing_payg(monkeypatch):
    monkeypatch.setenv('TAVILY_API_KEY','SECRET_SENTINEL')
    value=dict(account=dict(current_plan='Researcher',plan_limit=1000,plan_usage=0,paygo_limit=None,paygo_usage=0),key=dict(limit=None,usage=0))
    result=qualify(usage=value,free_credit_budget=12)
    assert result['status']=='READY' and result['payg_status']=='unknown'
    assert 'spending_enabled' not in result and 'owner_attested' not in result
    value['account']['plan_usage']=995
    assert qualify(usage=value,free_credit_budget=12)['status']=='BLOCKED'
    assert qualify(usage=value,free_credit_budget=13)['status']=='BLOCKED'


def test_html_numeric_chunk_provenance_matches_element_and_stays_unlinked():
    from matn_research.reader import html_document
    from matn_rag.ingest import prepare
    from matn_contracts.structure import DocumentStructure
    raw='<p>Trees grew 12 cm in 2032.</p>'
    d,_,_=html_document(raw,hashlib.sha256(raw.encode()).hexdigest(),'Fixture numeric HTML')
    prepare(d)
    assert all(n.status=='digital-unlinked' for c in d.chunks for n in c.numeric_tokens)
    data=d.model_dump(mode='json')
    data['chunks'][0]['numeric_tokens'][0]['bbox']['frame']='pdf_points'
    with pytest.raises(ValueError,match='NUMBER_LEDGER'):
        prepare(DocumentStructure.model_validate(data))


@pytest.mark.parametrize('plan,used',[('Project',0),('Researcher',999)])
def test_bounded_live_admission_cannot_override_current_usage_with_old_owner_proof(monkeypatch,tmp_path,plan,used):
    monkeypatch.setenv('TAVILY_API_KEY','SECRET_SENTINEL')
    proof=tmp_path/'proof.json'
    write(proof,dict(provider='tavily-search',plan='free',pay_as_you_go=False,spending_enabled=False,remaining_credits=1000,owner_attested=True,verified_at=time.time(),evidence_reference='Previous owner settings'))
    assert qualify(proof)['status']=='READY'
    usage=dict(account=dict(current_plan=plan,plan_limit=1000,plan_usage=used,paygo_limit=None),key=dict(limit=None,usage=used))
    assert qualify(proof,usage=usage,free_credit_budget=12)['status']=='BLOCKED'
