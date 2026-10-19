"""Spec gaps motivated by TUNE items; check-only observations do not set rules."""
import pytest
from tests.verification.test_rules import doc,request,result,layers,reasons
from matn_verification.numbers import parse


def test_retrieved_union_covers_adjacent_spans_but_never_a_gap():
    d=doc('Revenue increased steadily.');r=request(d);ref=r['claims'][0]['citations'][0]
    r['retrieved_spans']=[{**ref,'end':8,'quote':None},{**ref,'start':8,'quote':None}]
    assert layers(result(d,r))['L0']['verdict']=='pass'
    r['retrieved_spans'][1]['start']=9
    assert 'evidence_not_retrieved' in reasons(result(d,r))


@pytest.mark.parametrize('text', ['Revenue was 7.5 percent in Q1-FY2021/22.',
    'Revenue was 7.4 percent of GDP in FY2020/21.',
    'Revenue was US$18.4 billion in FY2020/21.',
    'At epoch 68, 119 out of 128 ideas were one of the two common ideas.'])
def test_approved_numeric_forms_include_their_fiscal_context(text):
    assert parse(text)[1]==()
    d=doc(text)
    assert 'unsupported_numeric_form' not in reasons(result(d,request(d)))
    # The assembled fixture has no ledger link for spelled numbers or fiscal periods;
    # grammar acceptance must not manufacture that provenance.


@pytest.mark.parametrize('evidence,claim',[
    ('Strengthening foundations will be crucial.','Strengthening foundations is crucial.'),
    ('Digitalization will need to be complemented with infrastructure.',
     'Digitalization needs to be complemented with infrastructure.'),
    ('Using the policy improved performance in all subsequent epochs.',
     'Using the policy improved performance.')])
def test_veto_only_no_mismatch_from_incidental_quantity_or_future_copula(evidence,claim):
    d=doc(evidence)
    assert layers(result(d,request(d,claim)))['L2']['verdict']=='pass'


def test_continued_sentence_is_one_edge_but_irrelevant_extra_is_still_checked():
    from matn_verification.rules import evidence_bundles
    d=doc('We conducted 34 interviews with entities experienced in',
          'designing, developing, and deploying AI systems.', 'Revenue was 12 percent.')
    refs=request(d,indices=(0,1,2))['claims'][0]['citations']
    groups=evidence_bundles([d],refs)
    assert list(map(len,groups))==[2,1]
    # An omitted block may never be bridged.
    assert list(map(len,evidence_bundles([d],[refs[0],refs[2]])))==[1,1]


def test_registry_subject_is_source_bound_and_pronouns_stay_unknown():
    from matn_verification.subjects import DOCUMENT_SUBJECTS
    registered=next(k for k,v in DOCUMENT_SUBJECTS.items() if v==('Egypt',))
    d=doc('Revenue increased.')
    d=d.model_copy(update={'doc_id':registered})
    assert layers(result(d,request(d,'Egypt revenue increased.')))['L3']['verdict']=='pass'
    assert layers(result(d,request(d,'France revenue increased.')))['L3']['verdict']=='reject'
    assert layers(result(d,request(d,'It increased.')))['L3']['verdict']=='unknown'


def test_registry_does_not_apply_egypt_subject_to_gao():
    from matn_verification.subjects import DOCUMENT_SUBJECTS
    assert DOCUMENT_SUBJECTS['sha256-fdbf041c7d1a188aff4520848b72b09dbe08ea813931ec16c72cfae104f208fc']==()
    assert DOCUMENT_SUBJECTS['sha256-86ae6315b99f2f3f0d8c6a3da9b0485fb731fe8d87dc558eeb81e51a621c38b4']==('Egypt',)


def test_fiscal_period_requires_every_digit_to_have_original_ledger_provenance():
    d=doc('Revenue was 7.5 percent in Q1-FY2021/22.')
    rr=result(d,request(d))
    assert layers(rr)['L1']['verdict']=='pass'
    e=d.elements[0]
    tokens=tuple(t for t in e.number_tokens if t.text!='22')
    d=d.model_copy(update={'elements':(e.model_copy(update={'number_tokens':tokens}),)})
    assert layers(result(d,request(d)))['L1']['verdict']=='unknown'


def test_future_event_prediction_still_has_a_modality_veto():
    d=doc('Revenue will be 12 percent.')
    assert 'modality_mismatch' in reasons(result(d,request(d,'Revenue is 12 percent.')))


def test_percent_denominator_and_ratio_roles_are_preserved():
    d=doc('Revenue was 7.4 percent of GDP.')
    assert 'scope_mismatch' in reasons(result(d,request(d,'Revenue was 7.4 percent.')))
    d=doc('The sample contained 119 out of 128 ideas.')
    assert 'scope_mismatch' in reasons(result(d,request(d,'The sample contained 128 out of 119 ideas.')))
    assert layers(result(d,request(d)))['L1']['verdict']=='pass'
