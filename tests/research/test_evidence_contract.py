"""Offline regressions: source availability and proposal shape, not model quality."""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator, ValidationError
import pytest

from matn_research.facets import IDAnalysis, expand, facet_specs, registry
from matn_research.workflow import Jobs, bind_analysis, catalogue, propose
from tests.verification.test_rules import doc


def task():
    return dict(goal='Explain sensor inspection and measurement', audience='Operators',
        language='English', scope='Declared synthetic fixture',
        facets=[dict(id='axis'+str(i), label='Inspection', query='How is inspection performed?') for i in range(4)],
        required_points=[dict(id='p'+str(i), facet='axis'+str(i), description='Inspection method', critical=False)
                         for i in range(4)])


def gap(facet='axis0'):
    return dict(facet=facet, support=None, state='unknown', points=[], dependencies=[],
        context_sources=[], reason='The supplied view does not establish the method.', conflict='',
        next_question='How was the measurement performed?', next_action='Find primary measurement methods')


@pytest.mark.parametrize('mutation', ['missing_question', 'missing_action', 'empty_question',
    'empty_action', 'blank_question', 'blank_action', 'reviewed', 'dependency'])
def test_wire_schema_and_python_reject_invalid_missing_evidence(mutation):
    item=gap()
    if mutation.startswith('missing_'): item.pop('next_'+mutation.split('_')[1])
    elif mutation.startswith('empty_'): item['next_'+mutation.split('_')[1]]=''
    elif mutation.startswith('blank_'): item['next_'+mutation.split('_')[1]]='   '
    elif mutation=='reviewed': item['state']='reviewed'
    else: item['dependencies']=[dict(segment='r1', dimension='condition', reason='Fixture irrelevant dependency')]
    value=dict(items=[item])
    with pytest.raises(ValidationError): Draft202012Validator(IDAnalysis.model_json_schema()).validate(value)
    with pytest.raises(ValueError): IDAnalysis.model_validate(value)


def test_supported_proposal_keeps_legacy_shape_and_unknown_is_not_promoted():
    item=gap(); item.update(support='s1')
    item.pop('next_question'); item.pop('next_action')
    value=dict(items=[item]); Draft202012Validator(IDAnalysis.model_json_schema()).validate(value)
    assert IDAnalysis.model_validate(value).items[0].state=='unknown'


def test_valid_gaps_bind_without_inventing_supports():
    d=doc('Sensors may require inspection.')
    pack,rows=catalogue([d],task()); reg,_=registry(pack,rows)
    value=dict(items=[gap(f['id']) for f in pack['task']['facets']])
    Draft202012Validator(IDAnalysis.model_json_schema()).validate(value)
    bound=bind_analysis(pack,expand(pack,reg,value,facet_specs(pack['task'])))
    assert not bound['content_plan']['items'] and len(bound['missing_requirements'])==4


def test_invalid_gap_fails_before_job_is_cached_as_complete(tmp_path):
    jobs=Jobs(tmp_path,task(),classification='Offline synthetic fixture')
    item=gap(); item.pop('next_action')
    class Fake:
        calls=0
        def generate(self, request):
            self.calls+=1
            return dict(done=True, done_reason='stop', response=json.dumps(dict(items=[item])))
    generator=Fake()
    with pytest.raises(ValidationError):
        propose(jobs,'invalid-gap','Fixture prompt',IDAnalysis.model_json_schema(),generator,lambda _:1)
    assert jobs.value['jobs']['invalid-gap']['status']=='failed'
    assert (tmp_path/'raw/invalid-gap.json').exists()
    with pytest.raises(ValueError, match='EXPLICIT_RETRY_REQUIRED'):
        propose(jobs,'invalid-gap','Fixture prompt',IDAnalysis.model_json_schema(),generator,lambda _:1)
    assert generator.calls==1


def long_document():
    return doc('Panels may absorb radiation. Panels may warm nearby air. '
        'Panels may shade the ground. Panels may block wind. '
        'Sensors measure surface temperature. Operators should inspect panels.')


def test_catalogue_audit_distinguishes_context_limit_from_lost_text():
    # antecedent-window-v1: an independent late sentence enters the pool with a
    # bounded (here empty) reading window instead of being dropped for length.
    d=long_document(); before=d.model_dump(mode='json')
    pack,rows=catalogue([d],task())
    audit=pack['research_packing']['availability']
    assert audit['counts']['sentences']==6
    assert audit['counts']['pool']==6
    late=audit['sentences'][-2:]
    assert all(r['first_unavailable'] is None and r['pool'] for r in late)
    units=[pack['content_units'][r['pool'][0]] for r in late]
    assert all(u['reason']=='antecedent_window' and u['context']==[] and u['context_role']=='reading_context' for u in units)
    assert len(rows)==6 and d.model_dump(mode='json')==before
    assert 'Sensors measure surface temperature' not in json.dumps(audit)


def test_late_pronoun_sentence_beyond_prefix_stays_unresolved():
    d=doc('Panels may absorb radiation. Panels may warm nearby air. '
        'Panels may shade the ground. Panels may block wind. They may also fail.')
    pack,rows=catalogue([d],task())
    late=pack['research_packing']['availability']['sentences'][-1]
    assert late['first_unavailable']=='content_unit' and late['unit_reasons']==['previous_sentence_limit']
    assert len(rows)==4


def test_late_connective_sentence_gets_minimal_window():
    d=doc('Panels may absorb radiation. Panels may warm nearby air. '
        'Panels may shade the ground. Sensors measure wind. In this case, operators should inspect panels.')
    pack,_=catalogue([d],task())
    unit=next(u for u in pack['content_units'].values() if u.get('support',{}).get('quote','').startswith('In this case'))
    assert unit['state']=='bounded' and unit['reason']=='antecedent_window'
    assert [c['quote'].strip() for c in unit['context']]==['Sensors measure wind.']


def test_catalogue_audit_explains_ineligible_and_cross_block_units():
    from matn_reading.structure.document import assemble
    from tests.reading.structure.conftest import record, snapshot
    d=assemble(snapshot([record('Sensor notes',kind='header'),
        record('Panels may shelter',order=1),record('the sensor during exposure.',order=2)]))
    pack,_=catalogue([d],task()); audit=pack['research_packing']['availability']
    header=next(r for r in audit['sentences'] if r['block_id']==d.elements[0].block.block_id)
    assert header['first_unavailable']=='eligibility' and 'evidence_not_citable' in header['reasons']
    tail=[r for r in audit['sentences'] if r['block_id']!=header['block_id']]
    assert all(r['first_unavailable']=='content_unit' for r in tail)
    assert all('continued_or_multi_span_support' in r['unit_reasons'] for r in tail)


def test_audit_rejects_changed_source_or_content_unit():
    from matn_research.catalogue_audit import availability
    d=long_document(); pack,_=catalogue([d],task())
    forged=deepcopy(pack); next(iter(forged['handles'].values()))['citations'][0]['quote']='Changed'
    with pytest.raises(ValueError,match='PACK_SPAN'): availability([d],forged)
    forged=deepcopy(pack); next(iter(forged['content_units'].values()))['state']='bounded-forged'
    with pytest.raises(ValueError,match='UNIT_CONTEXT_BINDING'): availability([d],forged)


def test_offline_trace_uses_saved_inputs_and_never_overwrites(tmp_path):
    from eval.research.catalogue_trace import trace
    d=long_document(); pack,_=catalogue([d],task())
    p=tmp_path/'input.json'; source=tmp_path/'document.json'; out=tmp_path/'audit.json'
    p.write_text(json.dumps(pack)); source.write_text(d.model_dump_json())
    before=(p.read_bytes(),source.read_bytes())
    summary=trace(p,[source],out)
    assert summary['counts']['pool']==6  # antecedent-window-v1 keeps late independent sentences
    assert json.loads(out.read_bytes())==pack['research_packing']['availability']
    with pytest.raises(FileExistsError,match='NEW_AUDIT'): trace(p,[source],out)
    with pytest.raises(ValueError,match='DUPLICATE_DOCUMENT'): trace(p,[source,source],tmp_path/'duplicate.json')
    assert before==(p.read_bytes(),source.read_bytes())


def test_offline_trace_refuses_sealed_gold_before_reading(tmp_path):
    from eval.research.catalogue_trace import trace
    sealed=tmp_path/'eval/gold/test/missing.json'
    with pytest.raises(ValueError,match='SEALED_TEST_INPUT'):
        trace(sealed,[tmp_path/'missing-document.json'],tmp_path/'audit.json')
    assert not (tmp_path/'audit.json').exists()
