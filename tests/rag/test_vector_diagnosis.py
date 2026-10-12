"""Diagnostic boundaries and statistics; never run live embeddings in tests."""
import sqlite3
import pytest
from eval.rag.vector_diagnosis import tune_only, ReadOnlyRepository, mean_pairs, hub_summary, best_rank, BudgetTransport


def test_tune_boundary_drops_check_before_consuming_fields():
    class Check(dict):
        def __getitem__(self, key):
            if key != 'split':
                raise AssertionError('check content consumed')
            return super().__getitem__(key)
    assert tune_only([Check(split='check'), {'split':'tune','id':'a'}]) == [{'split':'tune','id':'a'}]


def test_readonly_repository_cannot_write(tmp_path):
    path=tmp_path/'cache.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE chunks(id TEXT)')
    repo=ReadOnlyRepository(path)
    with pytest.raises(sqlite3.OperationalError):
        repo.db.execute("INSERT INTO chunks VALUES ('changed')")
    with pytest.raises(sqlite3.OperationalError):
        ReadOnlyRepository(tmp_path/'absent.sqlite')


def test_pair_mean_excludes_diagonal_and_weights_unordered_pairs():
    assert mean_pairs([[1.,0.],[0.,1.],[1.,0.]]) == {'pairs':3,'mean_cosine':pytest.approx(1/3)}
    assert mean_pairs([[1.,0.]]) == {'pairs':0,'mean_cosine':None}


def test_hubs_include_zero_occurrence_chunks_and_tied_ranks():
    rows=[{'chunk_id':x,'word_count':10,'kind':'body','source':'s'} for x in 'abc']
    result=hub_summary(rows, [['a','b'],['a','b']])
    assert result['occurrence_distribution']=={'0':1,'2':2}
    assert result['gini']==pytest.approx(1/3)
    assert result['length_pearson'] is None
    assert best_rank({'relevant_chunk_ids':['b','c']}, [('a',1),('b',.5)])==2
    assert best_rank({'relevant_chunk_ids':[]}, [('a',1)]) is None


def test_budget_refuses_201st_embedding_call_before_dispatch(tmp_path):
    transport=BudgetTransport(tmp_path)
    transport.calls=[{}]*200
    with pytest.raises(ValueError,match='EMBEDDING_CALL_BUDGET'):
        transport.request('/api/embed', {'input':['invented']})


def test_memory_sampling_includes_actual_llamacpp_runner_not_shells():
    from eval.rag.vector_diagnosis import is_server_process
    assert is_server_process('/usr/local/lib/ollama/llama-server --embedding -c 32768')
    assert is_server_process('/usr/local/bin/ollama serve')
    assert not is_server_process('bash -c ollama serve')
    assert not is_server_process('/usr/local/bin/ollama ps')
