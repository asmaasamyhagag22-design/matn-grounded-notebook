"""V2 deterministic falsification. Fake L4 is NOT semantic model evidence."""
from copy import deepcopy
import pytest
from tests.verification.test_rules import doc
from tests.chat.test_engine import Pass
from matn_chat.reliable import build_reliable_handles
from matn_rag.ingest import prepare
from matn_storyboard.core import evidence_pack,digest,save_version
from matn_storyboard.units import upgrade_pack,UnitWorkflow,render


def setup(text='Alpha may expand unless demand falls.'):
    d=doc(text)
    handles=build_reliable_handles([d],prepare(d)[1])
    task=dict(goal='Explain policy',audience='Planners',language='English',scope='fixture',
        facets=[dict(id=str(i),label='Policy',query='policy') for i in range(4)],
        required_points=[dict(id='policy',facet='0',description='policy',critical=True)])
    pack=upgrade_pack([d],evidence_pack(task,[d],handles))
    return d,pack


def atom(pack,text,key=None):return dict(text=text,support=key or next(iter(pack['handles'])))
def draft(pack,a):return dict(slides=[dict(facet=str(i),units=[deepcopy(a)]) for i in range(4)])

@pytest.mark.parametrize('source,good,bad',[
 ('Alpha may expand unless demand falls.','Alpha may grow unless demand falls.','Alpha must expand unless demand falls.'),
 ('Alpha must not expand.','Alpha must not expand.','Alpha must expand.'),
 ('Alpha may expand only if demand grows.','Alpha may grow only if demand grows.','Alpha may grow if demand grows.'),
 ('Alpha revenue was 12 percent in 2024.','Alpha revenue was 12 percent in 2024.','Alpha revenue was 12 percent in 2025.'),
 ('Alpha revenue was 12 percent in 2024.','Alpha revenue was 12 percent in 2024.','Alpha revenue was 12 dollars in 2024.'),
 ('If the cohort had 80 nurses, 23 may need training by 2028.','If the cohort had 80 nurses, 23 may need training by 2028.','If the cohort had 80 doctors, 23 may need training by 2028.'),
 ('Alpha may expand unless demand falls.','Alpha may expand unless demand falls.','Alpha may expand.'),
])
def test_pairs(source,good,bad):
    d,p=setup(source);f=UnitWorkflow([d],p,Pass(),verifier={'test':'fake'})
    assert f.check(atom(p,good))['status']=='verified'
    assert f.check(atom(p,bad))['status']!='verified'


def test_unrelated_modality_is_context_not_target_force():
    d,p=setup('Beta will expand. Alpha may expand unless demand falls.')
    k=list(p['handles'])[1];f=UnitWorkflow([d],p,Pass(),verifier={'test':'fake'})
    result=f.check(atom(p,'Alpha may grow unless demand falls.',k))
    assert result['status']=='verified' and len(result['display']['context'])==1
    assert result['display']['context'][0]['quote']=='Beta will expand. '


def test_auto_context_and_visibility_cannot_be_forged_or_removed():
    d,p=setup('A cohort includes 80 nurses in 2028. Of these, 23 may need training.')
    k=list(p['handles'])[1];f=UnitWorkflow([d],p,Pass(),verifier={'test':'fake'})
    v=f.build(draft(p,atom(p,'Of these, 23 may need training.',k)))
    assert all(s['displayed'] for s in v['slides'])
    assert '80 nurses' in render(v)
    changed=deepcopy(v);changed['slides'][0]['checks'][0]['display']['context']=[]
    with pytest.raises(ValueError,match='VERSION'):render(changed)
    forged=deepcopy(p);forged['content_units'][k]['context']=[]
    with pytest.raises(ValueError,match='CONTEXT_BINDING'):UnitWorkflow([d],forged,Pass())


def test_wrong_denominator_or_population_same_number():
    d,p=setup('A cohort includes 80 nurses in 2028. Of these, 23 may need training.')
    k=list(p['handles'])[1];f=UnitWorkflow([d],p,Pass())
    for t in ['23 percent may need training.','23 doctors may need training.','23 out of 80 trainees may need training.']:
        assert f.check(atom(p,t,k))['status']!='verified'


def test_added_causality_and_partial_compound_not_authorized_by_high_fake_l4():
    d,p=setup('Alpha may expand. Beta may shrink.'); f=UnitWorkflow([d],p,Pass())
    assert f.check(atom(p,'Alpha may expand because Beta may shrink.'))['status']!='verified'
    assert f.check(atom(p,'Alpha may expand. Beta may shrink.'))['status']!='verified'


def test_source_context_bounds_leave_unresolved():
    for text in ['Their skills may change.', 'Alpha may expand. Beta may grow. Gamma may grow. Delta may grow. Those teams may grow.']:
        d,p=setup(text);k=list(p['handles'])[-1]
        assert p['content_units'][k]['state']=='unresolved'
        assert UnitWorkflow([d],p,Pass()).check(atom(p,p['handles'][k]['text'],k))['status']=='abstained'


def test_versions_invalidation_and_style_no_inference(tmp_path):
    class Count(Pass):
        calls=0
        def check(self,*a):self.calls+=1;return super().check(*a)
    d,p=setup();n=Count();f=UnitWorkflow([d],p,n,verifier={'test':'fake'})
    v=f.build(draft(p,atom(p,'Alpha may expand unless demand falls.')));path=save_version(tmp_path,v);original=path.read_bytes()
    assert n.calls==1 # identical native pair shared across slides/layers
    style=f.edit(v,[dict(op='style',key='accent',value='blue')]);assert n.calls==1
    assert len(style['reused_receipts'])==1
    factual=f.edit(v,[dict(op='replace_unit',slide=0,unit=0,value=atom(p,'Alpha may grow unless demand falls.'))])
    assert factual['slides'][0]['displayed'] and path.read_bytes()==original
    title=f.edit(v,[dict(op='factual_title',slide=0,value=atom(p,'Alpha must expand.'))])
    assert not title['slides'][0]['displayed']
    revised=deepcopy(p);next(iter(revised['sources'].values()))['revision']='v2'
    v2=UnitWorkflow([d],revised,n,verifier={'test':'fake'}).build(draft(p,atom(p,'Alpha may expand unless demand falls.')),parent=v)
    assert v2['invalidated_receipts'] and not v2['reused_receipts']


def test_partial_citation_single_sentence_compound_and_same_number_wrong_year():
    d,p=setup('Alpha may expand.');f=UnitWorkflow([d],p,Pass())
    assert f.check(atom(p,'Alpha may expand and Beta may shrink.'))['status']!='verified'
    d,p=setup('A cohort includes 80 nurses in 2028. Of these, 23 may need training.')
    k=list(p['handles'])[1]
    assert UnitWorkflow([d],p,Pass()).check(atom(p,'Of these, 23 may need training in 2029.',k))['status']!='verified'


def test_context_is_checked_by_native_as_visible_and_claim_separately():
    class Capture(Pass):
        def __init__(self):self.texts=[]
        def check(self,text,evidence,target):self.texts.append(text);return super().check(text,evidence,target)
    d,p=setup('Beta will expand. Alpha may expand.');n=Capture();f=UnitWorkflow([d],p,n)
    t='Alpha may grow.';k=list(p['handles'])[1];r=f.check(atom(p,t,k))
    assert r['status']=='verified' and n.texts==[t,'Beta will expand. '+t]


def test_context_cannot_replace_support_sentence_for_another_fact():
    class EvidenceAware(Pass):
        def check(self,text,evidence,target):
            from matn_verification.contracts import Check
            if 'Beta' in text and not any('Beta' in e.quote for e in evidence):
                return Check(target=target,layer='L4',verdict='reject',reasons=('entailment_failed',))
            return super().check(text,evidence,target)
    d,p=setup('Beta may expand. Alpha may expand.');k=list(p['handles'])[1]
    assert UnitWorkflow([d],p,EvidenceAware()).check(atom(p,'Beta may expand.',k))['status']!='verified'


def test_generic_person_counter_is_not_an_occupation_alias():
    d,p=setup('A cohort includes 80 people in 2028. Of these, 23 may need training.')
    k=list(p['handles'])[1];f=UnitWorkflow([d],p,Pass())
    assert f.check(atom(p,'23 individuals may need training.',k))['status']=='verified'
    assert f.check(atom(p,'23 doctors may need training.',k))['status']!='verified'


def test_such_as_enumeration_does_not_add_causality():
    d,p=setup('Alpha needs skills such as programming and data science.');f=UnitWorkflow([d],p,Pass())
    assert f.check(atom(p,'Alpha needs skills such as data science and programming.'))['status']=='verified'
    assert f.check(atom(p,'Alpha needs programming as Beta expands.'))['status']!='verified'


def test_readable_view_retains_every_checked_context_and_claim():
    from matn_storyboard.unit_markdown import readable
    d,p=setup('Beta will expand. Alpha may expand.');k=list(p['handles'])[1]
    v=UnitWorkflow([d],p,Pass()).build(draft(p,atom(p,'Alpha may grow.',k)))
    text=readable(v)
    for s in v['slides']:
        for c in s['checks']:
            assert c['display']['text'] in text
            assert all(x['quote'].strip() in text for x in c['display']['context'])
    assert '[1]' in text


def test_final_composition_sees_factual_title_and_all_units():
    from matn_storyboard.unit_composition import ComposedWorkflow
    from matn_verification.contracts import Check
    class Capture(Pass):
        def __init__(self):self.texts=[]
        def check(self,text,evidence,target):
            self.texts.append(text)
            if 'Alpha may expand. Alpha may grow.' in text:
                return Check(target=target,layer='L4',verdict='reject',reasons=('entailment_failed',))
            return super().check(text,evidence,target)
    d,p=setup('Alpha may expand.');n=Capture();f=ComposedWorkflow([d],p,n)
    original=f.build(draft(p,atom(p,'Alpha may grow.')))
    assert all(s['displayed'] for s in original['slides'])
    v=f.edit(original,[dict(op='factual_title',slide=0,value=atom(p,'Alpha may expand.'))])
    assert 'Alpha may expand. Alpha may grow.' in n.texts
    assert not v['slides'][0]['displayed'] and v['slides'][0]['composition']['status']=='abstained'
    assert not v['slides'][0]['checks'][-1]['reused']
    assert v['slides'][0]['checks'][-1]['binding']!=original['slides'][0]['checks'][0]['binding']
    # The same old pair remains usable on the three unaffected duplicate slides.
