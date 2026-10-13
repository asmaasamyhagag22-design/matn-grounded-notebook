"""C0-only post-reading rebuild, guards and report; never selects a candidate."""
import argparse,hashlib,json,random,sqlite3,subprocess,sys,time
from pathlib import Path
from matn_contracts.structure import DocumentStructure
from matn_rag.sqlite import SQLiteRepository
from matn_rag.ingest import prepare
from matn_rag.embedding import Embedder,DIGEST,NUM_CTX
from matn_rag.search import Search
from matn_rag.contracts import canonical
from eval.rag.run import ReplayEmbedder,cache_load,Metered,verify_freeze,survey_summary
from eval.rag.metrics import grouped,rank,paired_exact
from eval.rag.r_lite_3_part1 import DEV,WEF
from eval.rag.r_lite_3_closure import read,save,OUT
ROOT=OUT/'retrieval'

def readonly(path):
 r=SQLiteRepository();r.db.close();r.db=sqlite3.connect('file:'+str(Path(path).resolve())+'?mode=ro',uri=True);r.db.row_factory=sqlite3.Row;return r

def cached_search(repo):
 s=Search(repo,ReplayEmbedder());cache_load(s,'out/rag-core/part2/query-cache.json');return s

def insert(repo,notebook,doc,base,embedder=None,allowed=None):
 meta,rows=prepare(doc);repo.create_notebook(notebook);sid=repo.add_source(notebook,doc.doc_id,meta,rows);pending=[]
 for row in rows:
  text=row['context_prefix']+'\n\n'+row['text'];v=base.get_embedding(DIGEST,'doc-input-v1',text)
  if v is None:v=repo.get_embedding(DIGEST,'doc-input-v1',text)
  if v is None:
   sha=hashlib.sha256(text.encode()).hexdigest()
   if embedder is None or allowed is not None and sha not in allowed:raise ValueError('UNCHANGED_INPUT_CACHE_MISSING:'+sha)
   pending.append((row['chunk_id'],text,sha))
  else:repo.put_embedding(DIGEST,'doc-input-v1',text,v);repo.link_embedding(sid,row['chunk_id'],'doc-input-v1',DIGEST,'doc-input-v1',text)
 for start in range(0,len(pending),8):
  batch=pending[start:start+8];vs=embedder.embed([t for _,t,_ in batch])
  for (cid,text,sha),v in zip(batch,vs,strict=True):
   repo.put_embedding(DIGEST,'doc-input-v1',text,v);repo.link_embedding(sid,cid,'doc-input-v1',DIGEST,'doc-input-v1',text)
  ledger=read(ROOT/'embedding-ledger.json') if (ROOT/'embedding-ledger.json').exists() else []
  ledger.append({'input_SHAs':[sha for _,_,sha in batch],'variant':'doc-input-v1','batch':len(batch),'num_ctx':NUM_CTX,'truncate':False});save(ROOT/'embedding-ledger.json',ledger)
 return sid

def clone(base,path,docs):
 if Path(path).exists():raise ValueError('GUARD_OUTPUT_EXISTS:'+str(path))
 r=SQLiteRepository(path)
 for d in docs:insert(r,'dev3',d,base)
 return r

def worker(db,output,notebook):
 verify_freeze();repo=readonly(db);s=cached_search(repo);ids=repo.source_ids(notebook);qs=read('eval/rag/frozen/questions.json')['items'];result=[]
 for q in qs:
  for mode in ('focused','survey'):result.append({'id':q['id'],'mode':mode,'result':s.query(notebook,ids,q['question'],mode,50)})
 save(output,result)

def gates(repo,docs,qs):
 ids=repo.source_ids('dev3');s=cached_search(repo);out={}
 for d in docs:
  _,rows=prepare(d);by={e.block.block_id:e for e in d.elements};chunks={c.chunk_id:c for c in d.chunks}
  for row in rows:
   for e in row['evidence']:
    p=e['payload'];b=by[p['block_id']];assert b.citable and 0<=p['start']<p['end']<=len(b.block.text)
    assert b.block.text[p['start']:p['end']] in chunks[p['primary_chunk_id']].text
   assert row['numeric_tokens']==[n.model_dump(mode='json') for n in chunks[row['chunk_id']].numeric_tokens]
 out['IX1']={'status':'PASS','scope':'all exact block-span evidence and numeric ledgers'}
 integrity=repo.integrity();assert integrity['chunks']==sum(len(d.chunks) for d in docs) and integrity['embedding_refs']==integrity['chunks'] and not integrity['orphan_embeddings'] and not integrity['foreign_key_errors']
 out['IX2']={'status':'PASS','variant':'C0 only, one embedding ref per chunk',**integrity}
 abc=clone(repo,ROOT/'delete-abc.sqlite',docs);ac=clone(repo,ROOT/'delete-ac.sqlite',[docs[0],docs[2]])
 sid=next(r['id'] for r in abc.source_rows('dev3') if r['doc_id']==docs[1].doc_id);abc.delete_source(sid)
 assert abc.canonical_export()==ac.canonical_export();left,right=cached_search(abc),cached_search(ac)
 for q in qs:assert canonical(left.query('dev3',abc.source_ids('dev3'),q['question'],depth=50))==canonical(right.query('dev3',ac.source_ids('dev3'),q['question'],depth=50))
 save(ROOT/'delete-canonical.json',json.loads(abc.canonical_export()));out['IX3']={'status':'PASS','all8_tables_byte_equal':True,'C0_question_pairs':len(qs)}
 for i in (0,1):subprocess.run([sys.executable,'-m','eval.rag.r_lite_3_closure_retrieval','worker','--db',str(ROOT/'dev3.sqlite'),'--output',str(ROOT/f'process-{i}.json')],check=True)
 assert (ROOT/'process-0.json').read_bytes()==(ROOT/'process-1.json').read_bytes();out['IX4']={'status':'PASS','processes':2,'C0_results':120,'cached_vectors':True}
 proof=read('out/rag-core/live-embedding-safety.json');assert proof['gate']=='PASS'
 out['IX5']={'status':'PASS','transport_guards_unchanged':True,'truncate_false_proof':proof,'changed_input_ledger':'embedding-ledger.json'}
 rng=random.Random(20261012);checks=0
 for q in qs:
  for mode in ('focused','survey'):
   a=s.query('dev3',ids,q['question'],mode,10);b=s.query('dev3',ids,q['question'],mode,50);assert a['hits']==b['hits'][:10];checks+=1
  selected=rng.sample(ids,rng.randint(1,2));assert all(h['source_id'] in selected for h in s.query('dev3',selected,q['question'],depth=50)['hits'])
 selected=ac.source_ids('dev3')
 for q in qs:assert canonical(s.query('dev3',selected,q['question'],depth=50))==canonical(right.query('dev3',selected,q['question'],depth=50))
 out['IX6']={'status':'PASS','C0_prefix_checks':checks,'subset_queries':len(qs),'independent_repository_pairs':len(qs)}
 surveys=read('eval/rag/frozen/survey.json')['items']
 for q in qs+surveys:
  r=s.query('dev3',ids,q['question'],mode='survey');assert all(x['hits']>=min(2,x['citable_count']) for x in r['summary'])
 out['IX7']={'status':'PASS','C0_survey_queries':len(qs)+len(surveys),'c0_c1_c_ge2_behavior_fixtures':'G2 tests (coverage counts, not retrieval candidates)'}
 save(ROOT/'gates.json',out);return out

def comparison(oldqs,newqs,old,new):
 lost=[];gained=[];rows=[]
 for a,b in zip(oldqs,newqs,strict=True):
  ra,rb=rank(a,old[a['id']]),rank(b,new[b['id']]);ha=ra is not None and ra<=10;hb=rb is not None and rb<=10
  if ha and not hb:lost.append(a['id'])
  if hb and not ha:gained.append(a['id'])
  rows.append({'id':a['id'],'old_rank':ra,'new_rank':rb,'split':a['split'],'source':a['source']})
 return {'old':grouped(oldqs,old),'new':grouped(newqs,new),'lost':lost,'gained':gained,'exact_discordant_p':paired_exact(len(lost),len(gained)),'per_question':rows,'report_only':True,'configuration':'C0','selection_or_retuning':False}

def run():
 verify_freeze();assert Path('docs/retrieval-selection-rule.md').exists();assert read(OUT/'reading-gates.json')['status']=='PASS'
 if (ROOT/'dev3.sqlite').exists():raise ValueError('RETRIEVAL_OUTPUT_EXISTS')
 ROOT.mkdir(parents=True,exist_ok=True);transport=Metered();embedder=Embedder(transport);embedder.check_digest()
 docs={k:DocumentStructure.model_validate(read(OUT/'production'/k/'05_document.json')) for k in (*DEV,WEF)}
 base=readonly('out/rag-core/part2/diagnostic.sqlite')
 interrupted=OUT/'retrieval-version-guard-failure'/'dev3.sqlite'
 if interrupted.exists():
  original=base;partial=readonly(interrupted)
  class CacheChain:
   def get_embedding(self,digest,variant,text):
    value=original.get_embedding(digest,variant,text)
    return partial.get_embedding(digest,variant,text) if value is None else value
  base=CacheChain()
 repo=SQLiteRepository(ROOT/'dev3.sqlite')
 allowed=set()
 for key in (*DEV,WEF):
  old=DocumentStructure.model_validate(read(Path('out/rag-core/section-rebuild')/key/'05_document.json'))
  inputs=lambda d:{hashlib.sha256((c.context_prefix+'\n\n'+c.text).encode()).hexdigest() for c in d.chunks}
  allowed|=inputs(docs[key])-inputs(old)
 save(ROOT/'allowed-changed-input-SHAs.json',sorted(allowed));save(ROOT/'embedding-ledger.json',[])
 for key in DEV:print('C0 build',key,flush=True);insert(repo,'dev3',docs[key],base,embedder,allowed)
 qs=read('eval/rag/frozen/questions.json')['items'];loc={r['question_id']:r['new_relevant_chunk_ids'] for r in read(OUT/'production-frozen.json')['per_question']}
 newqs=[{**q,'relevant_chunk_ids':loc[q['id']]} for q in qs];save(ROOT/'recomputed-questions-out-only.json',newqs)
 s=cached_search(repo);ids=repo.source_ids('dev3');results={q['id']:s.query('dev3',ids,q['question'],depth=50) for q in qs};save(ROOT/'frozen-C0-results.json',results)
 old=read('out/rag-core/part2/frozen-results.json')['questions']['hybrid'];save(ROOT/'frozen-comparison.json',comparison(qs,newqs,old,results));gates(repo,[docs[k] for k in DEV],newqs)
 four=SQLiteRepository(ROOT/'diagnostic.sqlite')
 for key in (*DEV,WEF):print('C0 diagnostic build',key,flush=True);insert(four,'dev4',docs[key],repo if key in DEV else base,embedder,allowed)
 fs=cached_search(four);fids=four.source_ids('dev4');fr={q['id']:fs.query('dev4',fids,q['question'],depth=50) for q in qs};save(ROOT/'diagnostic-C0-results.json',fr)
 before=read('out/rag-core/part2/diagnostic-results.json')['questions'];diag=comparison(qs,newqs,before,fr);diag['label']='WEF_DIAGNOSTIC_NOT_FROZEN';diag['survey']={q['id']:survey_summary(fs.query('dev4',fids,q['question'],mode='survey',depth=50)) for q in read('eval/rag/frozen/survey.json')['items']};save(ROOT/'diagnostic-comparison.json',diag)
 save(ROOT/'embedding-calls.json',transport.calls);verify_freeze();print('C0 REPORT COMPLETE; IX1-IX7 PASS',flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('stage',choices=['run','worker']);p.add_argument('--db');p.add_argument('--output');p.add_argument('--notebook',default='dev3');a=p.parse_args()
 if a.stage=='worker':worker(a.db,a.output,a.notebook)
 else:run()
