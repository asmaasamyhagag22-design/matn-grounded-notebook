"""Reply-contract regressions use hostile/faulty model outputs and bound evidence."""
from matn_app.answer_engine import copied_prose
from matn_app.answer_retrieval import HybridSearch,HybridBlockRanker


def test_copy_cannot_be_laundered_by_bullets_or_a_cropped_sentence():
    handles={'s1':dict(text='• Agencies should review the data before deploying an AI system.')}
    assert copied_prose('Agencies should review the data before deploying an AI system.',handles)
    assert copied_prose('Agencies should review the data before deploying an AI system',handles)
    assert not copied_prose('Agencies should review data before an AI system is deployed.',handles)


def test_hybrid_queries_every_source_and_semantic_results_survive_block_ranking():
    class Search:
        repo=object()
        def query(self,notebook,sources,question,**kwargs):
            return dict(hits=[dict(chunk_id=sources[0],source_id=sources[0],text='A supported statement.',section_path=[])])
    seen=[]
    def lookup(texts):
        seen.append(texts);return [[1.,0.] for text in texts]
    search=HybridSearch(Search(),lookup=lookup,release=lambda:None)
    result=search.query('notebook',['first','second'],'Unmatched phrase')
    ranked=HybridBlockRanker().rank('Unmatched phrase',result['hits'])
    assert len(seen)==2 and {h['source_id'] for h in ranked}=={'first','second'}
    assert all(row['hybrid_candidates']==1 for row in search.coverage[0]['sources'])


def test_one_sources_actor_cannot_take_another_sources_action():
    from matn_app.answer_engine import actor_transfer
    quotes=['Agency Alpha should improve staffing.','Agency Beta should reduce costs.']
    assert actor_transfer('Agency Alpha should reduce costs.',quotes)
    assert actor_transfer('Agency Beta audits Agency Alpha.',['Agency Alpha audits Agency Beta.'])
    assert not actor_transfer('Agency Alpha should improve staffing.',quotes)
    assert not actor_transfer('Agency Beta should reduce operational costs.',quotes)


def test_checklist_questions_and_merged_columns_cannot_supply_a_written_claim():
    from matn_app.answer_engine import AppChatEngine
    e=object.__new__(AppChatEngine);e.region_labels={}
    handles={str(i):dict(text=t,citations=[dict(block_id=str(i),doc_id='source')]) for i,t in enumerate([
        '• What governance should the agency define?',
        '• To what extent has the entity clarified roles • Review organizational documents.',
        'Entities should define a governance structure with clear goals.'
    ])}
    assert list(e.select_body_handles('What governance structure?',handles))==['2']


def test_decoder_binds_actor_and_modal_without_forcing_a_source_copy():
    import pytest
    from jsonschema import Draft202012Validator
    from matn_app.answer_engine import compact_payload
    h={'s1':dict(text='Entities should define a governance structure with clear goals.',source_title='Report')}
    validator=Draft202012Validator(compact_payload('What governance?',h)['format'])
    validator.validate(dict(sentences=[dict(claim='Entities should define clear goals in their governance structure.',handles=['s1'],part=0)]))
    with pytest.raises(Exception):
        validator.validate(dict(sentences=[dict(claim='The report states that entities should define governance.',handles=['s1'],part=0)]))


def test_missing_fact_gets_generated_verified_background_not_an_excerpt(tmp_path,monkeypatch):
    import json
    from tests.app.test_evidence import ingest_json
    from matn_app import evidence
    _,source=ingest_json(tmp_path,{'finding':'Entities should review their data.'})
    catalog=evidence._load_catalog(source['catalog']);calls=[]
    def attempt(notebook,question,folder,**kwargs):
        calls.append(str(question))
        if len(calls)==1:return dict(state='insufficient_evidence',sentences=[],receipts=[],app_calls=dict(generation=0,native=0)),[]
        return dict(state='answered',sentences=[dict(text='Entities should review data before using it.',kind='generated_verified_unit',receipt_index=0,
            citations=[dict(doc_id=catalog.sources[0].doc_id,pdf_page_index=0,quote='Entities should review their data.')])],receipts=[dict(status='verified')],app_calls=dict(generation=2,native=1)),[]
    monkeypatch.setattr(evidence,'_notebook_answer',attempt)
    value=evidence.answer(dict(question='How many agencies were certified in 2099?',catalogs=[source['catalog']],notebooks=['fixture.db'],workdir=str(tmp_path/'answer')))
    assert value['status']=='partial_answer' and value['answer_kind']=='generated_source_coverage'
    assert '2099' not in calls[1] and 'not verified' in value['message']
    assert 'Entities should review their data.' not in value['text']
    assert value['citations'] and value['metrics']['model_calls']==2
