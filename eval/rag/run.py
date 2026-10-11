"""Three-source frozen evaluation then separate WEF diagnostic; offline metric replay.

Run: python -m eval.rag.run ; replay: python -m eval.rag.run --reproduce
All inputs are explicitly enumerated dev structures, never PDFs or generic gold globs.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import random
import resource
import subprocess
import sys
import time
import numpy as np
from matn_contracts.structure import DocumentStructure
from matn_rag.contracts import canonical
from matn_rag.embedding import Embedder,DIGEST,MODEL,NUM_CTX,query_input,QUERY_INPUT_VERSION
from matn_rag.transport import LoopbackTransport
from matn_rag.ingest import ingest,prepare
from matn_rag.sqlite import SQLiteRepository
from matn_rag.search import Search
from .metrics import grouped,rank,paired_exact

ROOT=Path('out/rag-core/part2');FROZEN=Path('eval/rag/frozen');DEV=('2601-14525v1','gao-21-519sp','wb-eem-2021-12');WEF='wef-future-of-jobs-2025'


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(canonical(value)+b'\n')


def load(path):return json.loads(Path(path).read_text())


def verify_freeze():
    m=load(FROZEN/'manifest.json')
    for file,sha in m['sha256'].items():
        if hashlib.sha256((FROZEN/file).read_bytes()).hexdigest()!=sha:raise ValueError('FROZEN_ARTIFACT_CHANGED')


class Metered(LoopbackTransport):
    def __init__(self):super().__init__();self.calls=[]
    def request(self,path,payload=None):
        start=time.perf_counter();result=super().request(path,payload)
        if path=='/api/embed':
            self.calls.append({'batch_count':len(payload['input']),'wall_seconds':time.perf_counter()-start,
                'num_ctx':payload['options']['num_ctx'],'truncate':payload['truncate'],
                'max_input_chars':max(map(len,payload['input'])),'max_input_words':max(len(t.split()) for t in payload['input']),
                'prompt_eval_count':result.get('prompt_eval_count'),'total_duration_ns':result.get('total_duration')})
            if len(self.calls)%16==0:print('embedding_batches',len(self.calls),'inputs',sum(c['batch_count'] for c in self.calls),flush=True)
        return result


def cache_save(search,path):
    save(path,{'digest':DIGEST,'input_version':QUERY_INPUT_VERSION,'entries':[{'key':list(k),'vector':v} for k,v in sorted(search.query_vectors.items())]})


def cache_load(search,path):
    data=load(path)
    if data['digest']!=DIGEST or data['input_version']!=QUERY_INPUT_VERSION:raise ValueError('CACHE_VERSION')
    search.query_vectors={tuple(r['key']):r['vector'] for r in data['entries']}


class ReplayEmbedder:
    def check_digest(self):return None  # parent pins live digest before spawning; only frozen cache inputs here
    def embed(self,texts):raise ValueError('REPLAY_MODEL_CALL_REFUSED')


def worker(db,cache,output,notebook):
    verify_freeze();repo=SQLiteRepository(db);search=Search(repo,ReplayEmbedder());cache_load(search,cache);qs=load(FROZEN/'questions.json')['items'];rows=[]
    for q in qs:
        for mode in ('focused','survey'):
            for ab in ('bm25','vector','hybrid','no-prefix'):
                rows.append({'id':q['id'],'mode':mode,'ablation':ab,'result':search.query(notebook,repo.source_ids(notebook),q['question'],mode,50,ab)})
    save(output,rows)


def clone(base,path,notebook,documents):
    repo=SQLiteRepository(path);repo.create_notebook(notebook)
    for d in documents:
        metadata,rows=prepare(d);sid=repo.add_source(notebook,d.doc_id,metadata,rows)
        for variant in ('doc-input-v1','doc-input-no-prefix-v1'):
            for row in rows:
                text=row['context_prefix']+'\n\n'+row['text'] if variant=='doc-input-v1' else row['text']
                vector=base.get_embedding(DIGEST,variant,text)
                if vector is None:raise ValueError('CLONE_CACHE_MISSING')
                repo.put_embedding(DIGEST,variant,text,vector);repo.link_embedding(sid,row['chunk_id'],variant,DIGEST,variant,text)
    return repo


def gates(repo,docs,search,qs,query_cache):
    by_source={r['doc_id']:r['id'] for r in repo.source_rows('dev3')};ids=repo.source_ids('dev3');out={}
    for d in docs:
        metadata,rows=prepare(d);by={e.block.block_id:e for e in d.elements};chunks={c.chunk_id:c for c in d.chunks}
        for row in rows:
            for e in row['evidence']:
                p=e['payload'];b=by[p['block_id']]
                assert b.citable and 0<=p['start']<p['end']<=len(b.block.text)
                assert b.block.text[p['start']:p['end']] in chunks[p['primary_chunk_id']].text
            assert row['numeric_tokens']==[n.model_dump(mode='json') for n in chunks[row['chunk_id']].numeric_tokens]
    out['IX1']={'status':'PASS','scope':'all indexed evidence spans and exact numeric ledgers; separator/prefix/repeat/exclusion fixtures separately tested'}
    integrity=repo.integrity();assert integrity['chunks']==sum(len(d.chunks) for d in docs) and integrity['embedding_refs']==2*integrity['chunks'] and not integrity['orphan_embeddings'] and not integrity['foreign_key_errors']
    out['IX2']={'status':'PASS',**integrity}
    ab=clone(repo,ROOT/'delete-abc.sqlite','dev3',docs);ac=clone(repo,ROOT/'delete-ac.sqlite','dev3',[docs[0],docs[2]])
    b=next(r['id'] for r in ab.source_rows('dev3') if r['doc_id']==docs[1].doc_id);ab.delete_source(b)
    assert ab.canonical_export()==ac.canonical_export();left=Search(ab,ReplayEmbedder());right=Search(ac,ReplayEmbedder());cache_load(left,query_cache);cache_load(right,query_cache)
    for q in qs:
        assert canonical(left.query('dev3',ab.source_ids('dev3'),q['question'],depth=50))==canonical(right.query('dev3',ac.source_ids('dev3'),q['question'],depth=50))
    save(ROOT/'delete-canonical.json',json.loads(ab.canonical_export()));out['IX3']={'status':'PASS','all_repository_tables_byte_identical':True,'frozen_question_search_pairs':len(qs),'canonical_sha256':hashlib.sha256(ab.canonical_export()).hexdigest()}
    outputs=[]
    for index in (0,1):
        target=ROOT/f'process-{index}.json';subprocess.run([sys.executable,'-m','eval.rag.run','--worker','--db',str(ROOT/'dev3.sqlite'),'--cache',str(query_cache),'--output',str(target)],check=True);outputs.append(target)
    assert outputs[0].read_bytes()==outputs[1].read_bytes();out['IX4']={'status':'PASS','processes':2,'results':len(qs)*2*4,'cached_query_and_document_vectors':True,'sha256':hashlib.sha256(outputs[0].read_bytes()).hexdigest(),'timing_manifest_excluded':True}
    live=load('out/rag-core/live-embedding-safety.json');assert live['gate']=='PASS';out['IX5']={'status':'PASS','live_truncate_false':live,'fixtures':'host/proxy/redirect/egress/digest/cache/vector validation'}
    rng=random.Random(20261012);subset_checks=0;prefix_checks=0
    for q in qs:
        for ablation in ('bm25','vector','hybrid','no-prefix'):
            for mode in ('focused','survey'):
                base=10;ten=search.query('dev3',ids,q['question'],mode,base,ablation);fifty=search.query('dev3',ids,q['question'],mode,50,ablation)
                assert ten['hits']==fifty['hits'][:base];prefix_checks+=1
        selected=rng.sample(ids,rng.randint(1,2));before=search.query('dev3',selected,q['question'],depth=50)
        assert all(h['source_id'] in selected for h in before['hits']);subset_checks+=1
    # An independent repository containing only the selection establishes selected statistics/vectors independence.
    selected_docs=[docs[0],docs[2]];reduced=clone(repo,ROOT/'selected-ac.sqlite','dev3',selected_docs);rsearch=Search(reduced,ReplayEmbedder());cache_load(rsearch,query_cache)
    selected=reduced.source_ids('dev3')
    for q in qs:
        for ablation in ('bm25','vector','hybrid','no-prefix'):
            assert canonical(search.query('dev3',selected,q['question'],depth=50,ablation=ablation))==canonical(rsearch.query('dev3',selected,q['question'],depth=50,ablation=ablation))
    out['IX6']={'status':'PASS','random_subset_queries':subset_checks,'selected_vs_independent_repository_pairs':len(qs)*4,'prefix_pairs':prefix_checks,'unselected_add_delete_fixture':True}
    for q in qs:
        s=search.query('dev3',ids,q['question'],mode='survey')
        assert all(r['hits']>=min(2,r['citable_count']) for r in s['summary'])
    out['IX7']={'status':'PASS','depth_B':10,'frozen_questions':len(qs),'c0_c1_c_ge2_fixture':True}
    save(ROOT/'gates.json',out);return out


def cost(timings,calls,wall,chunks,peak_rss_kib=None):
    return {'build_wall_seconds':wall,'chunks':chunks,'embedding_calls':len(calls),'embedding_inputs':sum(c['batch_count'] for c in calls),
        'embedding_wall_seconds':sum(c['wall_seconds'] for c in calls),'embedding_inputs_per_second':sum(c['batch_count'] for c in calls)/sum(c['wall_seconds'] for c in calls) if calls else None,
        'latency_seconds_p50':float(np.quantile(timings,.5)) if timings else None,'latency_seconds_p95':float(np.quantile(timings,.95)) if timings else None,
        'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss if peak_rss_kib is None else peak_rss_kib,'num_ctx':NUM_CTX,'batch_size':8}


def evaluate(search,notebook,qs,survey,path,source_doc_ids):
    selected=search.repo.source_ids(notebook);bysource={r['doc_id']:r['id'] for r in search.repo.source_rows(notebook)};results={ab:{} for ab in ('bm25','vector','hybrid','no-prefix')};own={};timings=[]
    for i,q in enumerate(qs):
        for ab in results:
            start=time.perf_counter();results[ab][q['id']]=search.query(notebook,selected,q['question'],depth=50,ablation=ab);timings.append(time.perf_counter()-start)
        own[q['id']]=search.query(notebook,[bysource[source_doc_ids[q['source']]]],q['question'],depth=50)
        if i%10==0:print('frozen_questions_evaluated',i+1,flush=True)
    surveys={q['id']:search.query(notebook,selected,q['question'],mode='survey',depth=50) for q in survey}
    save(path,{'questions':results,'own_source':own,'survey':surveys});return results,own,surveys,timings


def reproduce():
    verify_freeze();qs=load(FROZEN/'questions.json')['items'];raw=load(ROOT/'frozen-results.json')
    if (ROOT/'frozen-cost-events.json').exists():save(ROOT/'frozen-cost.json',cost(**load(ROOT/'frozen-cost-events.json')))
    metrics={ab:grouped(qs,result) for ab,result in raw['questions'].items()};lost=[];gained=[]
    for q in qs:
        a=rank(q,raw['own_source'][q['id']]);b=rank(q,raw['questions']['hybrid'][q['id']]);own=a is not None and a<=10;all_=b is not None and b<=10
        if own and not all_:lost.append(q['id'])
        if all_ and not own:gained.append(q['id'])
    metrics['own_vs_all3']={'lost':lost,'gained':gained,'exact_discordant_p':paired_exact(len(lost),len(gained))}
    tune=metrics['hybrid']['split/tune'];gap=tune['hit']['50']['rate']-tune['hit']['5']['rate'];metrics['reranker_rule']={'tune_hit50_minus_hit5':gap,'propose_only':gap>=.15,'nothing_built':True}
    survey_summary={};tsv=['survey_id\trank\tsource_id\tchunk_id\tmatched_terms\tpreview']
    for qid,result in raw['survey'].items():
        base=max(10,3*len(result['summary']));hits=result['hits'][:base];counts=Counter(h['source_id'] for h in hits)
        survey_summary[qid]={'base_depth':base,'hits':len(hits),'unmatched_slots':sum(not h['matched_lexical_terms'] for h in hits),'sources':[{**s,'hits':counts[s['source_id']],'coverage_shortfall':max(0,2-counts[s['source_id']])} for s in result['summary']]}
        for position,h in enumerate(hits,1):tsv.append('\t'.join([qid,str(position),h['source_id'],h['chunk_id'],','.join(h['matched_lexical_terms']),' '.join(h['text'].split())[:200]]))
    metrics['survey']=survey_summary
    (ROOT/'survey-hits.tsv').write_text('\n'.join(tsv)+'\n')
    save(ROOT/'metrics.json',metrics)
    if (ROOT/'diagnostic-results.json').exists():
        diag=load(ROOT/'diagnostic-results.json');lost=[];gained=[];slots=Counter();totalslots=0
        for q in qs:
            a=rank(q,raw['questions']['hybrid'][q['id']]);b=rank(q,diag['questions'][q['id']]);three=a is not None and a<=10;four=b is not None and b<=10
            if three and not four:lost.append(q['id'])
            if four and not three:gained.append(q['id'])
            for h in diag['questions'][q['id']]['hits'][:10]:
                totalslots+=1
                if h['doc_id']==diag['wef_doc_id'] and h['kind']=='table':slots[q['id']]+=1
        diagnostic={'label':'DIAGNOSTIC_NOT_FROZEN','hit10_lost':lost,'hit10_gained':gained,'exact_discordant_p':paired_exact(len(lost),len(gained)),
                    'wef_table_top10_slots':sum(slots.values()),'total_top10_slots':totalslots,'wef_table_slot_share':sum(slots.values())/totalslots,
                    'wef_table_slots_per_question':dict(slots),'survey':{k:v['summary'] for k,v in diag['survey'].items()}}
        save(ROOT/'diagnostic-metrics.json',diagnostic)
    return metrics


def run():
    verify_freeze();ROOT.mkdir(parents=True,exist_ok=True)
    if (ROOT/'dev3.sqlite').exists():raise ValueError('RUN_OUTPUT_EXISTS; choose a fresh run directory, do not overwrite evidence')
    transport=Metered();embedder=Embedder(transport);embedder.check_digest();qs=load(FROZEN/'questions.json')['items'];survey=load(FROZEN/'survey.json')['items']
    docs=[DocumentStructure.model_validate_json(Path(f'out/rag-core/section-rebuild/{s}/05_document.json').read_bytes()) for s in DEV]
    repo=SQLiteRepository(ROOT/'dev3.sqlite');start=time.perf_counter()
    for source,d in zip(DEV,docs,strict=True):
        print('building',source,len(d.chunks),flush=True);ingest(repo,'dev3',d,embedder)
    buildwall=time.perf_counter()-start;buildcalls=list(transport.calls)
    search=Search(repo,embedder);results,own,surveys,timings=evaluate(search,'dev3',qs,survey,ROOT/'frozen-results.json',dict(zip(DEV,[d.doc_id for d in docs],strict=True)))
    cache_save(search,ROOT/'query-cache.json');save(ROOT/'frozen-cost-events.json',{'timings':timings,'calls':buildcalls,'wall':buildwall,'chunks':repo.integrity()['chunks'],'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss});save(ROOT/'frozen-cost.json',cost(timings,buildcalls,buildwall,repo.integrity()['chunks']))
    gate_results=gates(repo,docs,search,qs,ROOT/'query-cache.json');print('IX1-IX7 PASS',flush=True)
    # Drift uses an independently seeded set of50 original document inputs, one fresh reembed each.
    inputs=sorted([(sid,c['chunk_id'],c['context_prefix']+'\n\n'+c['text']) for sid in repo.source_ids('dev3') for c in repo.selected_chunks('dev3',[sid])])
    selected=random.Random(20261012).sample(inputs,50);drift=[];changed={}
    fresh=embedder.embed([t for sid,cid,t in selected])
    alternate=clone(repo,ROOT/'drift.sqlite','dev3',docs)
    for (sid,cid,text),v in zip(selected,fresh,strict=True):
        old=repo.get_embedding(DIGEST,'doc-input-v1',text);drift.append({'source_id':sid,'chunk_id':cid,'max_abs':max(abs(a-b) for a,b in zip(old,v,strict=True)),'l2':math.sqrt(math.fsum((a-b)**2 for a,b in zip(old,v,strict=True)))})
        key=alternate.db.execute('SELECT key FROM refs WHERE source=? AND chunk=? AND variant=?',(sid,cid,'doc-input-v1')).fetchone()[0]
        with alternate.db:alternate.db.execute('UPDATE embeddings SET vector=? WHERE key=?',(canonical(v).decode(),key))
    asearch=Search(alternate,ReplayEmbedder());cache_load(asearch,ROOT/'query-cache.json')
    for q in qs:
        hits=asearch.query('dev3',alternate.source_ids('dev3'),q['question'])['hits'];old=results['hybrid'][q['id']]['hits'][:10]
        if [h['chunk_id'] for h in hits]!=[h['chunk_id'] for h in old]:changed[q['id']]={'before':[h['chunk_id'] for h in old],'after':[h['chunk_id'] for h in hits]}
    save(ROOT/'drift.json',{'seed':20261012,'texts':drift,'top10_changes':changed,'retuned':False})
    longest=max(inputs,key=lambda row:len(row[2]));measured=transport.request('/api/embed',{'model':MODEL,'input':[longest[2]],'truncate':False,'options':{'num_ctx':NUM_CTX}})
    save(ROOT/'context.json',{'num_ctx':NUM_CTX,'longest_by_characters':{'chunk_id':longest[1],'chars':len(longest[2]),'whitespace_words':len(longest[2].split()),'server_prompt_eval_count':measured.get('prompt_eval_count')},'maximum_observed_batch_prompt_eval_count':max((c['prompt_eval_count'] or 0) for c in buildcalls),'note':'Batch prompt_eval_count is an upper bound on each input in that batch, not a per-input maximum token measurement.'})
    reproduce();print('Frozen3 metrics complete; starting WEF DIAGNOSTIC',flush=True)
    subprocess.run([sys.executable,'-m','eval.rag.run','--diagnostic'],check=True)
    reproduce();save(ROOT/'embedding-calls.json',transport.calls);verify_freeze();print('COMPLETE',flush=True)


def diagnostic_run():
    verify_freeze();transport=Metered();embedder=Embedder(transport);embedder.check_digest()
    repo=SQLiteRepository(ROOT/'dev3.sqlite');qs=load(FROZEN/'questions.json')['items'];survey=load(FROZEN/'survey.json')['items']
    docs=[DocumentStructure.model_validate_json(Path(f'out/rag-core/section-rebuild/{s}/05_document.json').read_bytes()) for s in DEV]
    copying=time.perf_counter();diagnostic=clone(repo,ROOT/'diagnostic.sqlite','diagnostic',[*docs]);basecopywall=time.perf_counter()-copying;wd=DocumentStructure.model_validate_json(Path(f'out/rag-core/section-rebuild/{WEF}/05_document.json').read_bytes());diags=Search(diagnostic,embedder);cache_load(diags,ROOT/'query-cache.json');start=time.perf_counter();offset=len(transport.calls);ingest(diagnostic,'diagnostic',wd,embedder);diagbuild=time.perf_counter()-start;diagcalls=transport.calls[offset:]
    diagresults={};diagtimes=[]
    for i,q in enumerate(qs):
        start=time.perf_counter();diagresults[q['id']]=diags.query('diagnostic',diagnostic.source_ids('diagnostic'),q['question'],depth=50);diagtimes.append(time.perf_counter()-start)
        if i%10==0:print('diagnostic_questions',i+1,flush=True)
    diagsurvey={q['id']:diags.query('diagnostic',diagnostic.source_ids('diagnostic'),q['question'],mode='survey',depth=50) for q in survey}
    save(ROOT/'diagnostic-results.json',{'label':'DIAGNOSTIC_NOT_FROZEN','wef_doc_id':wd.doc_id,'questions':diagresults,'survey':diagsurvey})
    save(ROOT/'diagnostic-cost.json',{'label':'DIAGNOSTIC_NOT_FROZEN','incremental_wef_build':cost(diagtimes,diagcalls,diagbuild,len(wd.chunks)),'four_source_chunk_count':diagnostic.integrity()['chunks'],'four_source_notebook_build_wall_seconds':basecopywall+diagbuild,'cold_equivalent_build_wall_seconds':load(ROOT/'frozen-cost.json')['build_wall_seconds']+diagbuild,'cost_note':'Dedicated diagnostic process peak RSS. Three-source vectors reused: actual four-source notebook build is cached baseline copy plus WEF ingestion; cold-equivalent estimate adds prior measured frozen build plus WEF, not an independent cold measurement.'})
    save(ROOT/'diagnostic-embedding-calls.json',transport.calls)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--reproduce',action='store_true');parser.add_argument('--worker',action='store_true');parser.add_argument('--diagnostic',action='store_true');parser.add_argument('--db');parser.add_argument('--cache');parser.add_argument('--output');args=parser.parse_args()
    if args.worker:worker(args.db,args.cache,args.output,'dev3')
    elif args.diagnostic:diagnostic_run()
    elif args.reproduce:reproduce()
    else:run()
