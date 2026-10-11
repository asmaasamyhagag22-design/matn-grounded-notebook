"""Backend-neutral repository and ranking contracts, before implementation."""
import json
import importlib
import pytest


def api(module, name):
    try:
        obj = getattr(importlib.import_module(module), name, None)
    except ModuleNotFoundError:
        obj = None
    assert callable(obj), f'Missing behavior: {module}.{name}'
    return obj


def chunk(cid, text, source='doc'):
    return {'chunk_id': cid, 'doc_id': source, 'text': text, 'context_prefix': 'scope', 'kind': 'body',
            'section_path': ['heading'], 'evidence': [{'block_id': cid+'-block', 'start': 0, 'end': len(text)}],
            'numeric_tokens': [], 'unavailable_tables': [], 'coverage_flags': [], 'prev_chunk_id': None, 'next_chunk_id': None}


def populate(repo, notebook='n', omit=()):
    repo.create_notebook(notebook)
    for source, texts in [('A', ['alpha 24% alpha', 'beta alpha']), ('B', ['beta', 'gamma']), ('C', ['alpha', 'delta'])]:
        if source in omit: continue
        repo.add_source(notebook, source, {'fingerprint': source, 'versions': {'tokenizer': 'rag-tokenizer-v1', 'index': 'rag-index-v1'}},
                        [chunk(source+str(i), text, source) for i, text in enumerate(texts)])
    return repo.source_ids(notebook)


def test_lifecycle_canonical_delete_and_shared_cache(tmp_path, repository_factory):
    Repo = repository_factory
    a, b = Repo(tmp_path/'a.db'), Repo(tmp_path/'b.db')
    ids = populate(a)
    populate(b, omit=('B',))
    for repo in (a, b):
        repo.put_embedding('digest', 'version', 'same', [1., 0.])
        repo.link_embedding(repo.source_ids('n')[0], 'A0', 'version', 'digest', 'version', 'same')
    a.link_embedding(ids[1], 'B0', 'version', 'digest', 'version', 'same')
    a.delete_source(ids[1])
    assert a.canonical_export() == b.canonical_export()
    assert a.integrity()['orphan_embeddings'] == 0
    assert a.integrity()['embedding_count'] == 1
    a.delete_source(ids[0])
    assert a.integrity()['embedding_count'] == 0


def test_idempotent_and_versions_refused(tmp_path, repository_factory):
    Repo = repository_factory
    repo = Repo(tmp_path/'a.db');ids = populate(repo);before = repo.canonical_export()
    assert repo.add_source('n', 'A', {'fingerprint': 'A', 'versions': {'tokenizer': 'rag-tokenizer-v1', 'index': 'rag-index-v1'}}, []) == ids[0]
    assert repo.canonical_export() == before
    with pytest.raises(ValueError, match='VERSION'):
        repo.add_source('n', 'X', {'fingerprint': 'X', 'versions': {'tokenizer': 'bad', 'index': 'rag-index-v1'}}, [])


def test_selected_bm25_and_alias_positions():
    score = api('matn_rag.scoring', 'bm25')
    rows = [chunk('a', '24% 24% alpha'), chunk('b', 'beta')]
    result = score(rows, '24 24 24%')
    assert result[0][0] == 'a' and result[0][1] > 0
    assert result == score(rows, '24 24%')
    assert score([rows[0]], 'alpha')[0][1] != score(rows, 'alpha')[0][1]


def test_search_prefix_coverage_zero_and_selection_independence(tmp_path, repository_factory):
    Repo = repository_factory
    Search = api('matn_rag.search', 'Search')
    repo = Repo(tmp_path/'a.db');ids = populate(repo)
    search = Search(repo, None, lexical_only=True)
    kwargs = dict(notebook='n', selected=ids[:1], question='alpha', ablation='bm25')
    a = search.query(**kwargs, depth=10);b = search.query(**kwargs, depth=50)
    assert a['hits'] == b['hits'][:10]
    assert all(h['source_id'] == ids[0] for h in a['hits'])
    repo.delete_source(ids[1]);assert search.query(**kwargs, depth=10) == a
    with pytest.raises(ValueError): search.query('n', [], 'alpha')
    with pytest.raises(ValueError): search.query('n', ['unknown'], 'alpha')
    repo.add_source('n', 'empty', {'fingerprint': 'empty', 'versions': {'tokenizer': 'rag-tokenizer-v1', 'index': 'rag-index-v1'}}, [])
    zero = repo.source_ids('n')[-1]
    z = search.query('n', [zero], 'alpha', mode='survey', ablation='bm25')
    assert z['hits'] == [] and z['summary'][0]['no_citable_content']
    assert z['summary'][0]['coverage_shortfall'] == 2
    s = search.query('n', repo.source_ids('n'), 'alpha', mode='survey', ablation='bm25')
    assert all(r['hits'] >= min(2, r['citable_count']) for r in s['summary'])
    assert 'coverage_shortfall' not in search.query(**kwargs)['summary'][0]


def test_loaded_version_mismatch_is_refused_before_search(tmp_path):
    Repo=api('matn_rag.sqlite','SQLiteRepository');Search=api('matn_rag.search','Search')
    repo=Repo(tmp_path/'a.db');ids=populate(repo)
    metadata={'fingerprint':'A','versions':{'tokenizer':'obsolete','index':'rag-index-v1'}}
    with repo.db:repo.db.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(metadata),ids[0]))
    with pytest.raises(ValueError,match='VERSION'):Search(repo,None,True).query('n',[ids[0]],'alpha')


def test_survey_reserves_absent_global_candidates_and_c1(tmp_path, repository_factory):
    Repo=repository_factory;Search=api('matn_rag.search','Search')
    repo=Repo(tmp_path/'a.db');repo.create_notebook('n');meta={'fingerprint':'f','versions':{'tokenizer':'rag-tokenizer-v1','index':'rag-index-v1'}}
    a=repo.add_source('n','large',meta,[chunk(f'A{i:03}','alpha') for i in range(65)])
    b=repo.add_source('n','small',meta,[chunk('Z1','unmatched')])
    search=Search(repo,None,True);ten=search.query('n',[a,b],'alpha','survey',10,'bm25');fifty=search.query('n',[a,b],'alpha','survey',50,'bm25')
    assert ten['hits']==fifty['hits'][:10]
    reserved=next(h for h in ten['hits'] if h['chunk_id']=='Z1')
    assert reserved['coverage_slot'] and reserved['rrf_score']==0 and reserved['bm25_rank'] is None
    summary=next(s for s in ten['summary'] if s['source_id']==b)
    assert summary['hits']==1 and summary['coverage_shortfall']==1
    with pytest.raises(ValueError,match='DEPTH'):search.query('n',[a,b],'alpha','survey',9,'bm25')
