"""General research selection and explicit scope regressions; no network/model calls."""
from matn_research.quality import axis_agreement,sentence_reason,authoritative_query,commercial_warning
from matn_app.clarification import known_senses,question,resolve
import pytest


def test_ambiguous_topics_never_choose_a_sense_or_default_audience():
    for topic in ('transformer','python','mercury'):
        pending=question(topic,known_senses(topic),False)
        assert pending['needs_meaning'] and pending['needs_audience']
        assert 3<=len(pending['options'])<=4 and pending['options'][-1]['label']=='Other'
        with pytest.raises(ValueError):resolve(pending,dict(choice='0'))
        intended,audience=resolve(pending,dict(choice='0',audience='Engineers'))
        assert intended==pending['options'][0]['topic'] and audience=='Engineers'
    assert question('Photovoltaic panels on public buildings',[],True) is None
    missing=question('Photovoltaic panels on public buildings',[],False)
    assert missing['question']=='Who is this briefing for?'
    assert resolve(missing,dict(choice='2'))[1]=='Decision-makers'


def test_fragments_and_dangling_pronouns_are_dropped_without_banning_specific_subjects():
    assert sentence_reason('For one thing, transformers contain hazardous material.','transformers')=='discourse_fragment'
    assert sentence_reason('In addition, the programme may reduce costs.','programme')=='discourse_fragment'
    assert sentence_reason('This can reduce costs.','procurement')=='unresolved_opening'
    assert sentence_reason('This approach can reduce costs.','procurement')=='unresolved_opening'
    assert sentence_reason('It improves public trust.','identity')=='unresolved_opening'
    assert sentence_reason('This regulation requires annual inspections.','transformers') is None
    assert sentence_reason('In addition to audits, agencies should review the source data.','audits') is None


def test_safety_is_not_regulatory_evidence_just_because_the_topic_matches():
    text='Dropping or mishandling a transformer can compromise insulation and cooling systems, making the transformer unsafe for operation.'
    assert not axis_agreement('Identify legal frameworks and liability assignments for transformer deployment.',text,topic='transformer',label='Regulatory Landscape')['passed']
    assert axis_agreement('Summarize safety protocols and public health hazards of transformer operations.',text,topic='transformer',label='Safety')['passed']
    assert axis_agreement('Identify legal frameworks and liability assignments.','Regulations require annual transformer inspections.',topic='transformer',label='Regulatory Landscape')['passed']


def test_query_hints_do_not_create_calls_or_topic_exceptions():
    for topic in ('soil quality','public transport','quantum computing'):
        hinted=authoritative_query(topic)
        assert hinted.startswith(topic) and 'site:gov' in hinted and 'site:edu' in hinted
    assert authoritative_query('site:gov soil quality')=='site:gov soil quality'


def test_commercial_majority_is_measured_on_unique_cited_sources_only():
    sources=[dict(id='S1',type='commercial-vendor'),dict(id='S2',type='commercial-vendor'),dict(id='S3',type='government')]
    assert commercial_warning(sources,[dict(source='S1'),dict(source='S1')])['share']==1
    assert commercial_warning(sources,[dict(source='S1'),dict(source='S3')])['warning'] is None
    assert commercial_warning(sources,[])['share'] is None


def test_production_selection_withholds_a_model_pick_on_the_wrong_axis(tmp_path,monkeypatch):
    import json
    from tests.research.test_fast_path import Generator,journey
    class WrongAxis(Generator):
        def generate(self,body):
            result=super().generate(body)
            if 'facets' in body['format']['properties']:
                value=json.loads(result['response'])
                value['facets'][0].update(label='Regulatory requirements',success='Identify legal frameworks and liability assignments for the proposed project.')
                result['response']=json.dumps(value)
            return result
    outcome=journey(tmp_path,monkeypatch,generator=WrongAxis(),gap=False,synthesis=False)
    assert outcome['verified_units']==3
    audit=json.loads((tmp_path/'select-0-axis-agreement.json').read_bytes())
    assert any(row['requirement']=='axis0' and row['model_selected'] and not row['passed'] for row in audit)
    draft=json.loads((tmp_path/'code-draft-0.json').read_bytes())['draft']
    assert draft['slides'][0]['units']==[]


def test_result_warning_counts_only_unique_cited_commercial_documents(monkeypatch):
    from matn_research.preview import source_balance
    import matn_research.source_type
    monkeypatch.setattr(matn_research.source_type,'for_records',lambda _:dict(d1=dict(label='commercial-vendor'),d2=dict(label='commercial-vendor'),d3=dict(label='government')))
    version=dict(slides=[dict(displayed=True,checks=[dict(display=dict(support=dict(doc_id=d))) for d in ('d1','d1','d2')])])
    balance=source_balance(version,[])
    assert balance['cited_sources']==2 and balance['share']==1
    assert balance['warning']=='Sources are mostly commercial; independent coverage is limited.'
