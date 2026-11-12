"""Quote-first acceptance uses the real app answer path and local model doubles."""
import json

import pytest

from matn_app.answer_profile import load_answer_profile
from matn_app.answer_retrieval import ContextualHybridSearch
from matn_app.answer_v3 import ABSTENTION, RETRACTION, SourceChunk, load_policy, validate_quotes, verify_sentence
from matn_app.evidence import answer, ingest
from matn_verification.contracts import Check, Evidence
from tests.app.test_document_quality import Counter
from tests.reading.pdf_fixtures import write_pdf


def span(text):
    return Evidence(block_id='block', doc_id='doc', start=17, end=17+len(text), quote=text,
                    pdf_page_index=0, page_label=None, bbox=(0., 0., 1., 1.), bbox_precision='region')


def test_quote_validation_binds_offsets_and_never_accepts_changed_words_or_ids():
    source = span('Lead. It took\n10 minutes. Tail.')
    chunks = {'c1': SourceChunk('Report', source)}
    candidates = [dict(chunk_id=chunk, exact_text=quote) for chunk, quote in [
        ('c1', 'It took 10 minutes.'), ('c1', 'It took 11 minutes.'), ('c2', 'It took 10 minutes.'),
        ('c1', '1'), ('c1', 'Example 4'), ('c1', 'It took 10 minutes.'),
    ]]
    quotes = validate_quotes(candidates, chunks)
    assert list(quotes) == ['q1']
    assert quotes['q1'].quote == 'It took\n10 minutes.'
    assert quotes['q1'].start == 23 and quotes['q1'].end == 42


class Entailment:
    def check(self, text, refs, target):
        assert len(refs) == 1
        passed = 'dogs' not in text and 'The number' in refs[0].quote
        return Check(target=target, layer='L4', verdict='pass' if passed else 'reject',
                     reasons=() if passed else ('entailment_failed',))


@pytest.mark.parametrize(('sentence', 'status'), [
    ('There were 105 people and 2 million records.', 'verified'),
    ('There were one hundred and five people and 2,000,000 records.', 'verified'),
    ('There were 106 people and two million records.', 'rejected'),
    ('There were 105 people and two million dogs.', 'rejected'),
    ('There were 105 people and 2.1 million records.', 'rejected'),
])
def test_verifier_requires_supported_prose_and_numeric_presence(sentence, status):
    refs = (span('The number was one hundred and five people and two million records.'),
            span('A different quote.'))
    result = verify_sentence(sentence, refs, Entailment())
    assert result['status'] == status


def test_contextual_retrieval_uses_headers_and_exact_identifier_ranking():
    rows = [dict(chunk_id=key, context_prefix=header, text=text, source_id='a') for key, header, text in [
        ('x', 'Report / Figure 4', 'The process took 10 minutes.'),
        ('y', 'Report / Example 4', 'The process took 10 seconds.'),
        ('z', 'Report / Example 40', 'The process took 10 seconds.'),
    ]]
    class Repo:
        def selected_chunks(self, *_):
            return rows

        def vectors(self, _, variant):
            assert variant == 'doc-input-v1'
            return {}
    seen = []
    def lookup(texts):
        seen.extend(texts)
        return [[1.0]] * len(texts)
    search = ContextualHybridSearch(type('Search', (), dict(repo=Repo()))(), load_policy(),
                                    lookup=lookup, release=lambda: None)
    result = search.query('notebook', ['a'], 'What happened in Example 4 in 10 seconds?')
    assert result['hits'][0]['chunk_id'] == 'y'
    assert result['hits'][0]['exact_matches'] == 2
    assert any(text.startswith('Report / Example 4\n\n') for text in seen)


@pytest.fixture
def source_answer(tmp_path, monkeypatch):
    from matn_chat.engine import MiniCheck
    from matn_chat.streaming import StreamingGenerator

    monkeypatch.setattr('matn_app.answer_retrieval.HybridSearch._vectors',
                        lambda self, texts: [[1.0]] * len(texts))
    monkeypatch.setattr('matn_app.answer_retrieval.HybridSearch._release', lambda self: None)
    monkeypatch.setattr('matn_app.runtime.drain_generator', lambda _: None)
    monkeypatch.setattr('eval.chat.token_budget.TokenCounter', Counter)
    monkeypatch.setattr('matn_storyboard.runtime.sample_memory',
                        lambda: dict(available_bytes=4*1024**3, l4_worker_rss_bytes=0))
    monkeypatch.setattr('matn_chat.reliable.LocalReranker.rank',
                        lambda self, question, hits: [dict(hit, rerank_score=0.01) for hit in hits])
    monkeypatch.setattr(MiniCheck, 'check', lambda self, text, refs, target:
                        Check(target=target, layer='L4', verdict='pass'))
    text = 'Workers should receive ten minutes of training before operating equipment.'
    pdf = write_pdf(tmp_path/'source.pdf', f'BT /F1 12 Tf 72 600 Td ({text}) Tj ET\n'.encode())
    source = ingest(dict(inputs=[str(pdf)], workdir=str(tmp_path/'ingest'), fake=True))
    calls = []

    def run(selection, sentences=()):
        def generate(self, body, emit, **kwargs):
            props = body['format']['properties']
            assert body['options']['temperature'] == 0
            if 'answer_found' in props:
                calls.append('quote')
                cid = props['quotes']['items']['properties']['chunk_id']['enum'][0]
                response = selection(cid, text)
            else:
                calls.append('write')
                assert text in body['prompt']
                response = dict(sentences=[value if isinstance(value, dict) else dict(text=value, quote_ids=['q1'])
                                           for value in sentences])
            return dict(done=True, done_reason='stop', response=json.dumps(response))
        monkeypatch.setattr(StreamingGenerator, 'generate_stream', generate)
        folder = tmp_path/'answer'
        result = answer(dict(question='How much training should workers receive?',
                             catalogs=[source['catalog']], notebooks=[source['notebook']],
                             workdir=str(folder)))
        return result, folder, calls

    return run


def yes(cid, text):
    return dict(answer_found='yes', quotes=[dict(chunk_id=cid, exact_text=text)], related_quotes=[])


def test_bad_sentence_is_retracted_and_old_warnings_do_not_hide_good_sentence(source_answer):
    result, folder, calls = source_answer(yes, (
        'Workers should get 10 minutes of training. The instruction requires 999 hours of training.',
    ))
    assert calls == ['quote', 'write']
    assert result['status'] == 'partial_answer' and RETRACTION in result['text']
    assert '999' not in result['text'] and '[1]' in result['text']
    assert result['metrics']['dropped_sentences'] == 1
    citation, = result['citations']
    assert citation['page'] == 1 and 'ten minutes' in citation['span']['quote']
    assert citation['verification']['warnings']['on_question']['passed'] is False
    progress = json.loads((folder/'verified-progress.json').read_bytes())
    assert [row['text'] for row in progress['sentences']] == ['Workers should get 10 minutes of training.']


def test_bad_quote_short_circuits_writer_and_related_is_labelled(source_answer):
    def selection(cid, text):
        return dict(answer_found='yes', quotes=[dict(chunk_id=cid, exact_text='Eighty hours.')],
                    related_quotes=[dict(chunk_id=cid, exact_text=text)])
    result, folder, calls = source_answer(selection)
    assert calls == ['quote'] and result['status'] == 'abstained'
    assert result['text'].startswith(ABSTENTION + '\n\nRelated information:\n“')
    related, = result['citations']
    assert related['kind'] == 'related_information' and related['verification'] is None
    assert not (folder/'verified-progress.json').exists()


def test_all_retracted_means_abstained(source_answer):
    result, _, calls = source_answer(yes, ('The course takes 999 hours.',))
    assert calls == ['quote', 'write']
    assert result['status'] == 'abstained' and ABSTENTION in result['text']
    assert RETRACTION in result['text'] and not result['citations']



def test_bad_ids_do_not_discard_valid_quotes_or_sentences(source_answer):
    def selection(cid, text):
        picked = yes(cid, text)
        picked['quotes'].insert(0, dict(chunk_id='invented', exact_text=text))
        return picked
    result, _, calls = source_answer(selection, (
        dict(text='The training takes 90 hours.', quote_ids=['invented']),
        'Workers should receive 10 minutes of training.',
    ))
    assert calls == ['quote', 'write']
    assert result['status'] == 'partial_answer' and result['metrics']['dropped_sentences'] == 1
    assert '90 hours' not in result['text'] and '10 minutes' in result['text']


def test_quote_expansion_preserves_offsets_and_excludes_related_fragment():
    source = span('Lead. The event happened in Feb. 2020. Unfinished clause • A separate task.')
    chunks = {'c1': SourceChunk('Report', source)}
    quote = dict(chunk_id='c1', exact_text='happened in Feb. 2020')
    ref = validate_quotes([quote], chunks, expand=True)['q1']
    assert ref.quote == 'The event happened in Feb. 2020.'
    assert source.quote[ref.start-source.start:ref.end-source.start] == ref.quote
    fragment = dict(chunk_id='c1', exact_text='Unfinished clause')
    assert not validate_quotes([fragment], chunks, prefix='r', expand=True)
    combined = dict(chunk_id='c1', exact_text='Unfinished clause • A separate task.')
    assert not validate_quotes([combined], chunks, prefix='r', expand=True)


def test_unit_switch_distinguishes_percent_from_percentage_points():
    ref = span('The number increased by 54 percent.')
    text = 'The number increased by 54 percentage points.'
    assert verify_sentence(text, (ref,), Entailment())['status'] == 'verified'
    options = {'verify_number_units': True}
    assert verify_sentence(text, (ref,), Entailment(), components=options)['status'] == 'rejected'
    assert verify_sentence('The number increased by 54%.', (ref,), Entailment(),
                           components=options)['status'] == 'verified'


def test_named_scope_switch_checks_the_same_organization():
    ref = span('The number was reported by the National Benefits Office.')
    claim = 'The number was reported by the regional Benefits Office.'
    options = {'verify_named_scope': True}
    receipt = verify_sentence(claim, (ref,), Entailment(), components=options)
    assert receipt['scope_conflicts'] == [('benefits office', 'regional')]
    assert receipt['status'] == 'rejected'


def test_v3_component_switches_load_from_answer_profile(tmp_path):
    from matn_app.answer_profile import load_v3_policy

    profile = tmp_path/'profile.json'
    profile.write_text(json.dumps(dict(answer_path='v3', v3_components={'expand_quotes': True})))
    switches = load_v3_policy(load_answer_profile(profile)['v3_components'])['components']
    assert switches['expand_quotes']
    assert switches['verify_number_units'] == load_policy()['components']['verify_number_units']
    profile.write_text(json.dumps(dict(answer_path='v3', v3_components={'expand_quotes': 'yes'})))
    with pytest.raises(ValueError, match='ANSWER_V3_COMPONENTS'):
        load_answer_profile(profile)


def test_document_scope_requires_a_unique_metadata_match():
    from types import SimpleNamespace
    from matn_app.answer_retrieval import matched_document

    docs = [SimpleNamespace(doc_id=ident, title=title, elements=()) for ident,title in
            [('gao','gao_21_519sp'),('transit','Regional Transit Authority')]]
    policy = load_policy()
    assert matched_document('According to GAO, what changed?', docs, {}, policy) == 'gao'
    assert matched_document('According to the Regional Transit Authority, what changed?', docs, {}, policy) == 'transit'
    assert matched_document('Compare GAO and the Regional Transit Authority.', docs, {}, policy) is None
    assert matched_document('What does the report recommend?', docs, {}, policy) is None
    assert matched_document('What baseline does the report use?', docs, {}, policy) is None
    assert matched_document('Which benchmarks does the report use?', docs, {}, policy) is None
    assert matched_document('According to GAO, what does the other selected document add?',
                            docs, {}, policy) is None

    paper = SimpleNamespace(doc_id='paper',title='Towards Execution-Grounded Automated AI Research',elements=())
    docs.append(paper)
    assert matched_document('According to GAO’s AI accountability report, when was it issued?',
                            docs, {}, policy) == 'gao'
    assert matched_document('What minimum accuracy must an AI system reach?', docs, {}, policy) is None
    assert matched_document('What did Thai researchers learn?', docs, {}, policy) is None
    assert matched_document('According to Dana Taylor, what changed?', docs,
                            {'paper': {'authors': ['Dana Taylor']}},policy) == 'paper'


def test_unit_check_treats_sept_as_september():
    ref = span('The number was recorded in Sept. 2021.')
    options = {'verify_number_units':True}
    assert verify_sentence('The number was recorded in September 2021.', (ref,), Entailment(),
                           components=options)['status'] == 'verified'


def test_document_scope_prioritizes_matching_hits_without_excluding_the_others():
    from types import SimpleNamespace

    rows = [dict(chunk_id=key, source_id=key, doc_id=key, context_prefix=header, text=body)
            for key,header,body in [('gao','GAO report','A procedure in the report.'),
                                    ('other','Example 4','The answer for Example 4.')]]

    class Repo:
        def selected_chunks(self, *_):
            return rows

        def vectors(self, *_):
            return {}

    docs = [SimpleNamespace(doc_id=key,title=title,elements=()) for key,title in
            [('gao','gao_report'),('other','Another document')]]
    search = ContextualHybridSearch(SimpleNamespace(repo=Repo()), load_policy({'scope_documents':True}),
                                    documents=docs, lookup=lambda texts:[[1.]]*len(texts), release=lambda:None)
    result = search.query('notebook',['gao','other'],'According to GAO, what happened in Example 4?')
    assert [hit['doc_id'] for hit in result['hits']] == ['gao','other']
    assert search.coverage[-1]['matched_document'] == 'gao'


def test_simple_writer_uses_the_measured_contract_with_the_same_schema():
    from matn_app.answer_v3 import writer_payload

    profile = dict(load_answer_profile(),answer_path='v3')
    quotes = {'q1':span('The number was twenty.')}
    base = writer_payload('What was the number?',quotes,profile,load_policy({'simple_writer':False}))
    policy = load_policy({'simple_writer':True})
    candidate = writer_payload('What was the number?',quotes,profile,policy)
    contract, suffix = candidate['prompt'].split('\nQuestion: ',1)
    assert contract == policy['simple_writer_prompt']
    assert suffix == base['prompt'].split('\nQuestion: ',1)[1]
    assert candidate['format'] == base['format']
    assert candidate['options'] == base['options']


def test_packing_spreads_source_passages_without_changing_prompt_text(monkeypatch):
    from types import SimpleNamespace
    from matn_app.answer_v3 import QuoteFirstAnswerEngine

    a = SourceChunk('Report',span('First relevant sentence.'))
    b = SourceChunk('Report',span('More details from the first hit.').model_copy(update={'block_id':'second'}))
    c = SourceChunk('Report',span('A relevant sentence from another hit.').model_copy(update={'block_id':'third'}))
    groups = {'x':[a,b],'y':[c]}
    monkeypatch.setattr('matn_app.answer_v3.passage_chunks',
                        lambda docs,hits,policy: iter(chunk for hit in hits for chunk in groups[hit['chunk_id']]))
    engine = object.__new__(QuoteFirstAnswerEngine)
    engine.policy = dict(load_policy(),max_prompt_chunks=2)
    engine.components = {'spread_passages':True}
    engine.profile = dict(load_answer_profile(),answer_path='v3')
    engine.token_counter = lambda text:len(text)//3
    engine.passage_search = SimpleNamespace(source_metadata={})
    docs = [SimpleNamespace(doc_id='doc',title='gao_report',elements=())]
    packed = engine.pack_chunks(docs,[dict(chunk_id='x'),dict(chunk_id='y')],'According to GAO, which relevant sentence?')
    assert {chunk.span.block_id for chunk in packed.values()} == {'block','third'}
    assert [chunk.text for chunk in packed.values()] == [a.text,c.text]
    packed = engine.pack_chunks(docs,[dict(chunk_id='x'),dict(chunk_id='y')],'Which relevant sentence?')
    assert {chunk.span.block_id for chunk in packed.values()} == {'block','second'}
