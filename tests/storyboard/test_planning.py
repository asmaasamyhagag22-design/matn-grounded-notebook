"""Causal construction tests. All L4 here is Fake L4, not semantic evidence."""
from copy import deepcopy
import pytest
from matn_storyboard.core import digest
from matn_storyboard.planning import attach, payload
from matn_storyboard.units import upgrade_pack
from matn_storyboard.unit_composition import ComposedWorkflow
from tests.storyboard.test_units import setup, atom
from tests.storyboard.test_scoped_entities import Capture


def fixture(text='Cooling is necessary for safe operation.', target=0, dependencies=(), context_sources=()):
    # Exactly four separate support sentences, preserving the existing task API.
    n=text.count('.')
    text += ' '+ ' '.join(['Robots may stop.', 'Pilots must not land.', 'Firms may invest.'][:4-n])
    d,p=setup(text);p=upgrade_pack([d],p,selected_display=True)
    keys=list(p['handles']);keys.insert(0,keys.pop(target))
    items=[dict(facet=str(i),support=k,points=['policy'] if i==0 else [],state='reviewed',
                reason='Selected to answer this facet; reviewed source scope.',context_sources=list(context_sources) if i==0 else [],
                dependencies=list(dependencies) if i==0 else []) for i,k in enumerate(keys)]
    p=attach(p,items,reviewer='Synthetic fixture author; Fake L4')
    a=atom(p,p['content_units'][keys[0]]['support']['quote'],keys[0]);a['context']=dict(text='',sources=[])
    draft=dict(slides=[dict(facet=str(i),units=[dict(text=p['content_units'][k]['support']['quote'],support=k,context=dict(text='',sources=[]))]) for i,k in enumerate(keys)])
    return d,p,a,draft


def dependency(pack,source,quote,dimension):
    key=pack['content_plan']['items'][0]['support'];u=pack['content_units'][key]
    c=u['support'] if source=='support' else u['context'][source]
    start=c['start']+c['quote'].index(quote)
    return dict(source=source,start=start,end=start+len(quote),quote=quote,dimension=dimension,reason='Explicit truth-condition needed for this point')


def scoped():
    d,p,a,draft=fixture('A cohort includes 72 technicians in 2032. Of these, 18 may need training and coaching.',target=1,context_sources=[0])
    deps=[dependency(p,0,q,k) for q,k in [('72','denominator'),('technicians','population'),('2032','period')]]
    p=attach(p,[dict(i,dependencies=deps) if j==0 else i for j,i in enumerate(p['content_plan']['items'])],reviewer='AI fixture review')
    a['context']=dict(text='A cohort includes 72 technicians in 2032.',sources=[0])
    draft['slides'][0]['units']=[deepcopy(a)]
    return d,p,a,draft


@pytest.mark.parametrize('old,new', [('72','73'),('technicians','teachers'),('2032','2033'),('A cohort includes 72 technicians in 2032.','')])
def test_required_scope_survives_or_abstains(old,new):
    d,p,a,_=scoped();f=ComposedWorkflow([d],p,Capture())
    assert f.check(a)['status']=='verified'
    a['context']['text']=a['context']['text'].replace(old,new)
    r=f.check(a)
    assert r['status']=='abstained' and any(x.startswith('planned_dependency_missing') for x in r['reasons'])


def test_true_irrelevant_context_excluded_before_and_after_writing():
    d,p,a,_=fixture('Robots may stop. Cooling is necessary for safe operation.',target=1)
    assert not p['content_plan']['items'][0]['context_sources']
    a['context']=dict(text='Robots may stop.',sources=[0]);n=Capture()
    r=ComposedWorkflow([d],p,n).check(a)
    assert r['status']=='abstained' and 'context_outside_content_plan' in r['reasons'] and n.calls==[]
    assert 'context_for_writing' in payload(p)['prompt']


@pytest.mark.parametrize('source,good,bad',[
 ('Cooling is necessary for safe operation.','Cooling is required for safe operation.','Cooling improves safe operation.'),
 ('If pressure rises, valves would close.','If pressure rises, valves would close.','Valves will close.'),
 ('Pilots do not need to land.','Pilots do not need to land.','Pilots need to not land.'),
 ('Robots may stop.','Robots may stop.','Robots must stop.'),
])
def test_existing_operator_contract_not_relaxed(source,good,bad):
    d,p,a,_=fixture(source);f=ComposedWorkflow([d],p,Capture())
    assert f.check(dict(a,text=good))['status']=='verified'
    assert f.check(dict(a,text=bad))['status']!='verified'


def test_shortening_cannot_delete_reviewed_condition():
    d,p,a,_=fixture('If pressure rises, valves would close.')
    deps=[dependency(p,'support','If pressure rises','condition')]
    items=deepcopy(p['content_plan']['items']);items[0]['dependencies']=deps;p=attach(p,items,reviewer='fixture')
    f=ComposedWorkflow([d],p,Capture())
    assert f.check(a)['status']=='verified'
    assert 'planned_dependency_missing:condition' in f.check(dict(a,text='Valves would close.'))['reasons']


def test_context_alias_cannot_license_claim():
    d,p,a,_=fixture('National Audit Council (NAC) may review plans. Firms may invest.',target=1,context_sources=[0])
    a['context']=dict(text='NAC may review plans.',sources=[0]);a['text']='NAC may invest.'
    r=ComposedWorkflow([d],p,Capture()).check(a)
    assert r['status']=='abstained' and 'new_entity' in r['reasons']


def test_immutable_factual_and_style_versions_and_partial_invalidation():
    d,p,a,draft=scoped();n=Capture();f=ComposedWorkflow([d],p,n);v1=f.build(draft);before=digest(v1)
    a['text']='Of these, 18 may need training.' # factual subset: omit coaching
    v2=f.edit(v1,[dict(op='replace_unit',slide=0,unit=0,value=a)])
    assert len(v2['invalidated_receipts'])==1 and len(v2['reused_receipts'])==3
    assert len(v2['invalidated_composition_receipts'])==1
    calls=len(n.calls);v3=f.edit(v2,[dict(op='style',key='density',value='compact')])
    assert len(n.calls)==calls and all(s['displayed'] for s in v3['slides']) and digest(v1)==before


def test_context_edit_invalidates_only_affected_receipts():
    d,p,a,draft=scoped();f=ComposedWorkflow([d],p,Capture());v=f.build(draft)
    a['context']['text']='A cohort includes 72 teachers in 2032.'
    child=f.edit(v,[dict(op='replace_unit',slide=0,unit=0,value=a)])
    assert len(child['invalidated_receipts'])==1 and len(child['reused_receipts'])==3
    assert not child['slides'][0]['displayed']


def test_plan_revision_invalidates_only_that_item():
    d,p,a,draft=scoped();v=ComposedWorkflow([d],p,Capture()).build(draft)
    items=deepcopy(p['content_plan']['items']);items[0]['state']='unknown'
    p2=attach(p,items,reviewer='Changed dependency review')
    child=ComposedWorkflow([d],p2,Capture()).build(draft,parent=v)
    assert len(child['invalidated_receipts'])==1 and len(child['reused_receipts'])==3
    assert not child['slides'][0]['displayed']


def test_plan_cannot_forge_span_or_swap_facet_support():
    d,p,a,draft=scoped();bad=deepcopy(p);bad['content_plan']['items'][0]['dependencies'][0]['quote']='73'
    with pytest.raises(ValueError,match='CONTENT_PLAN_SPAN'):ComposedWorkflow([d],bad,Capture())
    draft['slides'][0]['units'][0]['support']=p['content_plan']['items'][1]['support']
    with pytest.raises(ValueError,match='CONTENT_PLAN_SUPPORT_SELECTION'):ComposedWorkflow([d],p,Capture()).build(draft)


def test_plan_cli_preparation_keeps_source_folder_and_binds_new_output(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from matn_storyboard import __main__ as cli
    d,p,_,_=scoped();source=tmp_path/'saved';source.mkdir()
    (source/'input.json').write_text(json.dumps(dict(notebook='saved.sqlite',sources='all')))
    (source/'evidence-pack.json').write_text(json.dumps(p))
    before={f.name:f.read_bytes() for f in source.iterdir()};closed=[]
    monkeypatch.setattr(cli,'load',lambda *args:(SimpleNamespace(db=SimpleNamespace(close=lambda:closed.append(True))),None,None,[d],None))
    out=tmp_path/'planned';review=dict(reviewer='New construction review',items=p['content_plan']['items'])
    cli.plan(source,review,out)
    assert {f.name:f.read_bytes() for f in source.iterdir()}==before
    inputs=json.loads((out/'input.json').read_text());pack=json.loads((out/'evidence-pack.json').read_text())
    assert inputs['pack_sha256']==digest(pack) and pack['content_plan']['reviewer']==review['reviewer']
    assert closed==[True]


def test_typographic_equivalence_preserves_words_numbers_and_source_offsets():
    d,p,a,_=fixture('Workers’ training may improve.')
    items=deepcopy(p['content_plan']['items']);items[0]['dependencies']=[dependency(p,'support','Workers’ training','population')]
    p=attach(p,items,reviewer='fixture');f=ComposedWorkflow([d],p,Capture())
    assert not any(x.startswith('planned_dependency_missing') for x in f.check(dict(a,text="Workers' training may improve."))['reasons'])
    assert 'planned_dependency_missing:population' in f.check(dict(a,text="Teachers' training may improve."))['reasons']


def test_writer_sees_contiguous_dependency_excerpt_and_original_stays_in_pack():
    import json
    from matn_storyboard.planning import writing_context
    d,p,a,_=scoped();item=p['content_plan']['items'][0];u=p['content_units'][item['support']]
    projected=writing_context(u,item)
    assert projected[0]['text']=='72 technicians in 2032'
    assert u['context'][0]['quote'].startswith('A cohort includes')
    body=payload(p);assert 'A cohort includes' not in json.loads(body['prompt'].split('\n',1)[1])['content'][0]['context_for_writing'][0]['text']
