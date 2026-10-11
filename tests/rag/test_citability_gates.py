"""IX1/2/3/4/6/7 regressions with native contract objects, never sealed PDFs."""
import json
import subprocess
import sys
from pathlib import Path
import random
import pytest
from tests.reading.structure.conftest import record, snapshot
from matn_reading.structure.document import assemble
from matn_reading.structure.coverage import resolve_citation
from matn_rag.ingest import prepare
from matn_rag.sqlite import SQLiteRepository
from matn_rag.search import Search
from matn_rag.contracts import canonical
from tests.rag.test_repository_search import chunk, populate


def test_primary_citation_excludes_separator_prefix_and_excluded_blocks():
    doc=assemble(snapshot([record('First 12.'),record('Next sentence.',order=1),record('hidden.',visibility='hidden',order=2)]))
    metadata,records=prepare(doc)
    assert len(records)==len(doc.chunks)
    assert all(e['payload']['block_id'] not in doc.excluded_blocks for r in records for e in r['evidence'])
    by={e.block.block_id:e.block.text for e in doc.elements}
    assert all(by[e['payload']['block_id']][e['payload']['start']:e['payload']['end']] for r in records for e in r['evidence'])
    assert all(e['kind']=='pdf_block_span' for r in records for e in r['evidence'])
    assert [n for r in records for n in r['numeric_tokens']]==[n.model_dump(mode='json') for c in doc.chunks for n in c.numeric_tokens]
    for c in doc.chunks:
        for m in c.offset_map:
            if m.kind=='separator':
                with pytest.raises(ValueError,match='SEPARATOR'):resolve_citation(c,m.start,m.end,doc.chunks)
    with pytest.raises(TypeError):prepare(doc.model_dump())


def test_canonical_delete_equivalence_and_results_for_all_fixture_queries(tmp_path):
    a,b=SQLiteRepository(tmp_path/'a.db'),SQLiteRepository(tmp_path/'b.db')
    ids=populate(a);populate(b,omit=('B',));a.delete_source(ids[1])
    assert a.canonical_export()==b.canonical_export()
    for q in ('alpha','beta','24%','unknown'):
        for mode in ('focused','survey'):
            assert canonical(Search(a,None,True).query('n',a.source_ids('n'),q,mode,ablation='bm25'))==canonical(Search(b,None,True).query('n',b.source_ids('n'),q,mode,ablation='bm25'))


def test_selection_independence_random_subsets_and_prefix(tmp_path):
    repo=SQLiteRepository(tmp_path/'a.db');ids=populate(repo)
    search=Search(repo,None,True);rng=random.Random(20261012)
    for _ in range(12):
        selected=rng.sample(ids,rng.randint(1,3))
        for mode in ('focused','survey'):
            base=max(10,3*len(selected)) if mode=='survey' else 10
            a=search.query('n',selected,'alpha',mode,base,'bm25');b=search.query('n',selected,'alpha',mode,50,'bm25')
            assert a['hits']==b['hits'][:base]
            assert all(h['source_id'] in selected for h in b['hits'])
    selected=ids[:1];before=search.query('n',selected,'alpha',ablation='bm25')
    repo.add_source('n','unselected',{'fingerprint':'u','versions':{'tokenizer':'rag-tokenizer-v1','index':'rag-index-v1'}},[chunk('u','alpha '*100)])
    assert search.query('n',selected,'alpha',ablation='bm25')==before


def test_cross_notebook_cache_survives_one_tenant_delete(tmp_path):
    r=SQLiteRepository(tmp_path/'a.db');populate(r,'one');populate(r,'two')
    ids=[r.source_ids(n)[0] for n in ('one','two')]
    r.put_embedding('d','v','shared',[1.,0.])
    for sid in ids:r.link_embedding(sid,'A0','v','d','v','shared')
    r.delete_source(ids[0]);assert r.integrity()['embedding_count']==1
    assert r.integrity()['embedding_refs']==1 and not r.integrity()['foreign_key_errors']


def test_two_process_json_determinism(tmp_path):
    path=tmp_path/'repo.db';repo=SQLiteRepository(path);populate(repo);repo.db.close()
    script="from matn_rag.sqlite import SQLiteRepository;from matn_rag.search import Search;from matn_rag.contracts import canonical;import sys;r=SQLiteRepository(sys.argv[1]);sys.stdout.buffer.write(canonical(Search(r,None,True).query('n',r.source_ids('n'),'alpha',mode='survey',ablation='bm25')))"
    assert subprocess.check_output([sys.executable,'-c',script,str(path)])==subprocess.check_output([sys.executable,'-c',script,str(path)])
