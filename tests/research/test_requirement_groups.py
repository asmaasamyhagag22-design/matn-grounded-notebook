"""Real product binding/plan/build path and requirement-keyed selection controls.

Fake native isolates structural regressions; never model-quality evidence.
"""
from copy import deepcopy
import pytest
from matn_research.requirement_selection import schema, prompt, expand, schedule
from matn_research.facets import registry, facet_specs
from matn_research.workflow import bind_analysis
from matn_storyboard.planning import trim_reading_plan
from matn_storyboard.units import UnitWorkflow, upgrade_pack
from tests.storyboard.test_units import setup, atom
from tests.chat.test_engine import Pass


def reading_pack(text):
    d,p=setup(text);p=upgrade_pack([d],p,selected_display=True)
    p['task']['research_selection_mode']='bounded-multiple-v1'
    return d,p


def bound_context(text):
    d,p=reading_pack(text);key=list(p['handles'])[-1];unit=p['content_units'][key]
    facet=p['task']['facets'][0]['id']
    # Actual whole-context wire expansion -> content plan -> display constructor.
    reg,wire=registry(p,[dict(handle=key)])
    short=next(iter(reg['supports']))
    fs=facet_specs(p['task'])[:1]
    point=fs[0]['points'][0]
    v=dict(wire,requirements=[point],requirement_supports={point['id']:[short]},facet_supports={facet:[short]})
    raw={point['id']:dict(candidate=short,state='reviewed',conflict=False,reason='Useful scoped source statement.',next_question='What remains unknown?',next_action='Find remaining evidence.')}
    expanded=expand(p,reg,raw,fs,v)
    # Other axes abstain naturally in this structural control.
    for f in p['task']['facets'][1:]:
        expanded['items'].append(dict(facet=f['id'],support=None,state='unknown',reason='No evidence.',context_sources=[],dependencies=[],conflict='',points=[],next_question='Which evidence?',next_action='Find evidence.'))
    return d,p,key,bind_analysis(p,expanded)


def test_real_reading_context_plan_is_trimmed_before_construct_and_verification(monkeypatch):
    monkeypatch.setattr('matn_verification.rules._linked',lambda t:False)
    text='The trial ran for three years and cut plant losses by 50%. Crews should check soil moisture during establishment.'
    d,p,key,bound=bound_context(text)
    plan,audit=trim_reading_plan([d],bound)
    assert audit and plan['content_plan']['items'][0]['dependencies']==[]
    assert bound['content_plan']['items'][0]['dependencies']  # Original remains auditable.
    assert plan['content_units']==p['content_units']
    f=UnitWorkflow([d],plan,Pass(),verifier={'test':'fake'})
    from matn_storyboard.planning import construct
    a=construct(plan,atom(plan,plan['content_units'][key]['support']['quote'],key))
    receipt=f.check(a)
    assert receipt['status']=='verified'
    assert receipt['display']['context']==[]
    assert not any('planned_dependency_missing' in r for r in receipt['reasons'])
    # Unlinked numbers in the CLAIM are still rejected.
    a['text']='Crews should check soil moisture for three years during establishment.'
    assert f.check(a)['status']!='verified'


def test_explicit_semantic_dependency_cannot_be_trimmed(monkeypatch):
    monkeypatch.setattr('matn_verification.rules._linked',lambda t:False)
    d,p,key,bound=bound_context('The trial ran for three years and cut plant losses by 50%. Crews should check soil moisture during establishment.')
    bound['content_plan']['items'][0]['dependencies'][0]['dimension']='period'
    plan,audit=trim_reading_plan([d],bound)
    assert audit==[] and plan['content_plan']['items'][0]['dependencies']


def test_requirement_keys_and_candidates_are_not_interchangeable():
    v=dict(requirements=[dict(id='p1'),dict(id='p2')],requirement_supports=dict(p1=['s1'],p2=['s2']))
    s=schema([],v)
    assert s['required']==['p1','p2']
    assert s['properties']['p1']['properties']['candidate']['enum']==[None,'s1']
    assert s['properties']['p2']['properties']['candidate']['enum']==[None,'s2']


def test_group_scheduler_reserves_a_view_for_each_requirement():
    from tests.research.test_requirement_views import wire
    task=dict(goal='Explain operations',audience='Managers',scope='Public briefing',facets=[dict(id='ops',label='Operations',query='operations')],
              required_points=[dict(id='a',facet='ops',description='Inspect equipment'),dict(id='b',facet='ops',description='Schedule maintenance')])
    w=wire(['Teams should inspect equipment regularly.','Teams should schedule preventive maintenance.'])
    plan=schedule(task,{},w,lambda s:len(s)//4,generation_cap=4,rankings=dict(a=['s1'],b=['s2']),draft_calls=2)
    v=plan['batches'][0]['wire']
    assert v['requirement_supports']==dict(a=['s1'],b=['s2'])
    assert all(r['token_share']>0 for r in plan['facet_views'].values())
    assert plan['batches'][0]['budget']['measured']['input_with_framing']<=2560
    assert 'one named field for EVERY' in prompt(task,[],v)


def test_c1_ranking_uses_project_bm25_and_equal_rrf(monkeypatch):
    from matn_research import requirement_selection as r
    from tests.research.test_requirement_views import wire
    # Orthogonal vectors make the lexical and vector rank agree exactly.
    monkeypatch.setattr(r,'vectors',lambda texts,**kw:[[1.,0.],[0.,1.],[1.,0.]])
    result=r.rank_requirements(dict(required_points=[dict(id='q',description='Inspect equipment')]),
        wire(['Teams should inspect equipment regularly.','Teams should schedule preventive maintenance.']))
    assert result['q'][0]=='s1'


def test_actual_analysis_driver_handles_repeated_facet_groups_without_checkpoint_collision(tmp_path,monkeypatch):
    import json
    from matn_research import requirement_selection as r
    from matn_research.workflow import analyse_facets, Jobs
    from tests.research.test_structural_contracts import multi
    from eval.research.fixtures import BRIEF,LABEL
    _,p,_=multi();p['task']['required_points']=[dict(id='p'+str(i),facet=f['id'],description='Fixture operations',critical=True) for f in p['task']['facets'] for i in range(int(f['id'])*4,int(f['id'])*4+4)]
    monkeypatch.setattr(r,'prepare_rankings',lambda task,wire,*a:{q['id']:[wire['sources'][int(q['facet'])]['handle']] for q in task['required_points']})
    requests=[]
    class G:
        def generate(self,body):
            requests.append(body)
            return dict(done=True,done_reason='stop',response=json.dumps({q:dict(candidate=None,source_support='unresolved',conflict=False,reason='No suitable source.',next_question='What is missing?',next_action='Find evidence.') for q in body['format']['required']}))
    # No journal: production default is six; explicit test cap permits 8 groups + writers.
    monkeypatch.setitem(__import__('matn_research.models',fromlist=['LIMITS']).LIMITS,'generation',14)
    jobs=Jobs(tmp_path,BRIEF,classification=LABEL)
    value=analyse_facets(jobs,p,[],0,G(),lambda _:1,local_slots='requirements')
    assert len(requests)==8 and len(value['items'])==16
    assert len([k for k in jobs.value['jobs'] if k.startswith('facet-0-')])==8
    assert all(i['support'] is None for i in value['items'])


def test_new_source_support_decision_requires_explicit_model_support():
    from matn_research.requirement_selection import POLICY
    from jsonschema import Draft202012Validator, ValidationError
    v=dict(projection=POLICY,requirements=[dict(id='p1')],requirement_supports=dict(p1=['s1']))
    s=schema([],v)
    assert 'state' not in s['properties']['p1']['properties']
    assert s['properties']['p1']['properties']['source_support']['enum']==['supported','unresolved']
    value=dict(p1=dict(candidate='s1',source_support='unresolved',conflict=False,reason='Unclear relevance.',next_question='What remains missing?',next_action='Find evidence.'))
    Draft202012Validator(s).validate(value)
    value['p1']['state']='reviewed'
    with pytest.raises(ValidationError):Draft202012Validator(s).validate(value)


def test_nonnull_unresolved_source_statement_is_not_promoted():
    from matn_research.requirement_selection import POLICY
    d,p=reading_pack('Maintenance teams should inspect equipment after use.')
    key=next(iter(p['handles']));reg,w=registry(p,[dict(handle=key)]);sid=next(iter(reg['supports']));fs=facet_specs(p['task'])[:1];point=fs[0]['points'][0]
    v=dict(w,projection=POLICY,requirements=[point],requirement_supports={point['id']:[sid]},facet_supports={fs[0]['id']:[sid]})
    raw={point['id']:dict(candidate=sid,source_support='unresolved',conflict=False,reason='The relevance remains unresolved.',next_question='What establishes relevance?',next_action='Find direct evidence.')}
    result=expand(p,reg,raw,fs,v)
    assert result['items'][0]['support']==key
    assert result['items'][0]['state']=='unknown' and result['items'][0]['points']==[]
