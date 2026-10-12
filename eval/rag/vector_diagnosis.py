"""Tune-only, read-only vector diagnosis. Live: --live; offline replay: no flags.

Frozen DB is opened mode=ro; no raw check-split results are loaded. A/F alone
can call the model; every dispatched embedding input is hashed and persisted.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import subprocess
import threading
import time

import numpy as np
from matn_rag.contracts import canonical
from matn_rag.embedding import Embedder, DIGEST, MODEL, query_input, QUERY_INPUT_VERSION
from matn_rag.scoring import bm25, cosine, fuse, terms_and_length
from matn_rag.sqlite import SQLiteRepository
from matn_rag.transport import LoopbackTransport

OUT=Path('out/rag-core/vector-diagnosis')
BASE=Path('out/rag-core/part2')
DEV=('2601-14525v1','gao-21-519sp','wb-eem-2021-12')
EOS='<|endoftext|>'
VARIANTS=('space','no_space','space_eos','no_space_eos')


def sha(data):
    return hashlib.sha256(data if isinstance(data,bytes) else data.encode()).hexdigest()


def save(path,value):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_bytes(canonical(value)+b'\n')


def load(path):
    return json.loads(Path(path).read_text())


def tune_only(items):
    return [q for q in items if q['split']=='tune']


class ReadOnlyRepository(SQLiteRepository):
    def __init__(self,path):
        self.db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA query_only=ON')
        self.revision=0


class BudgetTransport(LoopbackTransport):
    def __init__(self,out):
        super().__init__(timeout=180)
        self.out=Path(out);self.calls=[];self.phase=None
    def request(self,path,payload=None):
        if path!='/api/embed':
            return super().request(path,payload)
        if len(self.calls)>=200:
            raise ValueError('EMBEDDING_CALL_BUDGET')
        record={'call':len(self.calls)+1,'phase':self.phase,
                'input_sha256':[sha(t) for t in payload['input']],
                'input_count':len(payload['input']),'num_ctx':payload['options']['num_ctx'],
                'truncate':payload['truncate'],'status':'DISPATCHED'}
        self.calls.append(record);save(self.out/'embedding-calls.json',self.calls)
        start=time.perf_counter()
        try:
            response=super().request(path,payload)
        except Exception as exc:
            record.update(status='FAILED',error=str(exc),wall_seconds=time.perf_counter()-start)
            save(self.out/'embedding-calls.json',self.calls)
            raise
        record.update(status='OK',wall_seconds=time.perf_counter()-start,
                      prompt_eval_count=response.get('prompt_eval_count'),
                      total_duration_ns=response.get('total_duration'))
        save(self.out/'embedding-calls.json',self.calls)
        if len(self.calls)%10==0:
            print('diagnostic embedding calls',len(self.calls),flush=True)
        return response


def best_rank(question,ranking):
    relevant=set(question['relevant_chunk_ids'])
    return next((i for i,(cid,score) in enumerate(ranking,1) if cid in relevant),None)


def mean_pairs(vectors):
    a=np.asarray(vectors,dtype=np.float64)
    n=len(a);pairs=n*(n-1)//2
    # Algebraic all-unordered-pairs mean; no sampling and no diagonal.
    return {'pairs':pairs,'mean_cosine':float((np.sum(np.sum(a,axis=0)**2)-np.sum(a*a))/(2*pairs)) if pairs else None}


def pearson(a,b):
    if len(a)<2 or np.std(a)==0 or np.std(b)==0:return None
    return float(np.corrcoef(a,b)[0,1])


def hub_summary(rows,top_lists):
    counts=Counter(cid for ids in top_lists for cid in ids)
    values=np.asarray(sorted(counts[r['chunk_id']] for r in rows),dtype=np.float64)
    total=float(values.sum());n=len(values)
    gini=float(np.sum((2*np.arange(1,n+1)-n-1)*values)/(n*total)) if total else 0.
    ranked=sorted(rows,key=lambda r:(-counts[r['chunk_id']],r['chunk_id']))
    kinds=defaultdict(list)
    for row in rows:kinds[row['kind']].append(counts[row['chunk_id']])
    return {'slots':int(total),'chunks':n,'unique_retrieved':sum(values>0).item(),
            'occurrence_distribution':{str(k):v for k,v in sorted(Counter(map(int,values)).items())},
            'gini':gini,'population_skewness':float(np.mean((values-values.mean())**3)/np.std(values)**3) if np.std(values) else None,
            'top20_slot_share':sum(counts[r['chunk_id']] for r in ranked[:20])/total if total else None,
            'length_pearson':pearson([r['word_count'] for r in rows],[counts[r['chunk_id']] for r in rows]),
            'kind':{k:{'chunks':len(v),'slots':sum(v),'mean_occurrence':sum(v)/len(v)} for k,v in sorted(kinds.items())},
            'top20':[{k:r[k] for k in ('chunk_id','kind','word_count','source')}|{'k_occurrence':counts[r['chunk_id']]} for r in ranked[:20]]}


def query_variant(question,variant):
    text=query_input(question)
    if variant.startswith('no_space'):text=text.replace('\nQuery: ','\nQuery:',1)
    return text+(EOS if variant.endswith('_eos') else '')


def inputs():
    # Filter at the only frozen question boundary; no check fields/ranks inspected.
    qs=tune_only(load('eval/rag/frozen/questions.json')['items'])
    if len(qs)!=27:raise ValueError('TUNE_COUNT_CHANGED')
    repo=ReadOnlyRepository(BASE/'dev3.sqlite');selected=repo.source_ids('dev3')
    rows=repo.selected_chunks('dev3',selected)
    source_ids={r['doc_id']:r['id'] for r in repo.source_rows('dev3')}
    source_by_id={}
    structure={}
    for source in DEV:
        d=load(f'out/rag-core/section-rebuild/{source}/05_document.json')
        source_by_id[source_ids[d['doc_id']]]=source
        for c in d['chunks']:structure[c['chunk_id']]=c
    for r in rows:
        r.update(source=source_by_id[r['source_id']],section_id=structure[r['chunk_id']]['section_id'],
                 word_count=structure[r['chunk_id']]['word_count'])
    needed={sha(query_input(q['question'])) for q in qs}
    cache=load(BASE/'query-cache.json')
    if cache['digest']!=DIGEST or cache['input_version']!=QUERY_INPUT_VERSION:raise ValueError('CACHE_VERSION')
    qvecs={e['key'][2]:e['vector'] for e in cache['entries'] if e['key'][2] in needed}
    if set(qvecs)!=needed:raise ValueError('TUNE_QUERY_CACHE_MISSING')
    vectors={variant:repo.vectors(selected,variant) for variant in ('doc-input-v1','doc-input-no-prefix-v1')}
    by={r['chunk_id']:r for r in rows}
    for variant,vs in vectors.items():
        if len(vs)!=len(rows):raise ValueError('VECTOR_INTEGRITY')
        for r in rows:
            text=r['context_prefix']+'\n\n'+r['text'] if variant=='doc-input-v1' else r['text']
            stored=repo.db.execute('SELECT inputs.text,embeddings.digest,embeddings.version,embeddings.text_sha256 FROM inputs JOIN refs USING(source,chunk,variant) JOIN embeddings ON embeddings.key=refs.key WHERE source=? AND chunk=? AND variant=?',(r['source_id'],r['chunk_id'],variant)).fetchone()
            if tuple(stored)!=(text,DIGEST,variant,sha(text)):raise ValueError('EMBEDDING_PATH_INPUT_MISMATCH')
    return qs,repo,rows,by,qvecs,vectors


def quality(qs,ranks):
    reachable=[q for q in qs if q['reachable']]
    return {'total':len(qs),'reachable':len(reachable),'hit':{str(k):{'successes':sum(ranks[q['id']] is not None and ranks[q['id']]<=k for q in reachable),'n':len(reachable)} for k in (1,5,10,20,50)}}


def offline():
    qs,repo,rows,by,qvecs,vectors=inputs();ranking={};summary={};hub_lists=[];arxiv=defaultdict(Counter)
    for prefix,variant in ((True,'doc-input-v1'),(False,'doc-input-no-prefix-v1')):
        records=[(r['chunk_id'],*terms_and_length(r['context_prefix']+'\n\n'+r['text'] if prefix else r['text'])) for r in rows]
        stats=repo.source_stats(repo.source_ids('dev3'),variant)
        streams={ab:{} for ab in ('bm25','vector','hybrid')}
        for q in qs:
            lexical=bm25(rows,q['question'],prefix,stats,records)
            vector=cosine(rows,qvecs[sha(query_input(q['question']))],vectors[variant])
            fused=fuse(lexical,vector)
            for ab,stream in (('bm25',lexical),('vector',vector),('hybrid',fused)):
                streams[ab][q['id']]=best_rank(q,stream)
            ranking[(prefix,q['id'])]=(lexical,vector,fused)
            if prefix:
                hub_lists.append([cid for cid,score in vector[:10]])
                if q['source']==DEV[0]:
                    for ab,stream in (('vector',vector),('hybrid',fused)):
                        arxiv[ab].update(by[cid]['kind'] for cid,score in stream[:10])
        summary['prefix' if prefix else 'no_prefix']={ab:quality(qs,ranks) for ab,ranks in streams.items()}
    pairwise={}
    for variant,vs in vectors.items():
        groupdoc=defaultdict(list);groupsec=defaultdict(list)
        for r in rows:
            v=vs[(r['source_id'],r['chunk_id'])]
            groupdoc[r['source']].append(v);groupsec[(r['source'],r['section_id'])].append(v)
        sec=[mean_pairs(v) for v in groupsec.values()];count=sum(s['pairs'] for s in sec)
        pairwise[variant]={'documents':{k:mean_pairs(v) for k,v in sorted(groupdoc.items())},
                           'same_section':{'pairs':count,'mean_cosine':sum(s['pairs']*s['mean_cosine'] for s in sec if s['pairs'])/count if count else None,'groups':len(groupsec)}}
    hubs=hub_summary(rows,hub_lists)
    foot=[r for r in rows if r['source']==DEV[0] and r['kind']=='footnote']
    if len(foot)!=137:raise ValueError('ARXIV_FOOTNOTE_COUNT_CHANGED')
    def pages(r):return sorted({e['payload']['pdf_page_index'] for e in r['evidence']})
    rng=random.Random(20261012);sample=rng.sample(sorted(foot,key=lambda r:r['chunk_id']),10)
    footrecord={'count':len(foot),'page_index_convention':'zero-based PDF indices; assignment by minimum evidence page',
                'by_page':dict(sorted(Counter(min(pages(r)) for r in foot).items())),
                'by_10_page_range':dict(sorted(Counter(f'{min(pages(r))//10*10}-{min(pages(r))//10*10+9}' for r in foot).items())),
                'length_words':{'min':min(r['word_count'] for r in foot),'median':float(np.median([r['word_count'] for r in foot])),
                                'p95':float(np.quantile([r['word_count'] for r in foot],.95)),'max':max(r['word_count'] for r in foot)},
                'seed':20261012,'excerpts':[{'chunk_id':r['chunk_id'],'pages':pages(r),'word_count':r['word_count'],
                                          'text_excerpt':r['text'][:600],'context_prefix':r['context_prefix']} for r in sample]}
    misses=[]
    for q in qs:
        l,v,f=ranking[(True,q['id'])];fr=best_rank(q,f)
        if fr is None or fr>50:
            misses.append({'id':q['id'],'reachable':q['reachable'],'bm25_rank_full975':best_rank(q,l),
                           'vector_rank_full975':best_rank(q,v),'fused_rank_union_top50':fr,
                           'target_ranks':[{'chunk_id':cid,'bm25':next((i for i,(c,s) in enumerate(l,1) if c==cid),None),
                                            'vector':next((i for i,(c,s) in enumerate(v,1) if c==cid),None),
                                            'fused':next((i for i,(c,s) in enumerate(f,1) if c==cid),None)} for cid in q['relevant_chunk_ids']]})
    examples=[]
    for source in DEV:
        q=next(q for q in qs if q['source']==source and q['relevant_chunk_ids'])
        r=by[q['relevant_chunk_ids'][0]]
        examples.append({'question_id':q['id'],'chunk_id':r['chunk_id'],'query_input':query_input(q['question']),
                         'doc_input_v1':r['context_prefix']+'\n\n'+r['text'],'document_instruction':None})
    result={'label':'TUNE_ONLY_DIAGNOSTIC','questions':len(qs),'reachable':sum(q['reachable'] for q in qs),
            'B':{'retrieval':summary,'pairwise':pairwise},'C':hubs,'D':{'arxiv_tune_questions':sum(q['source']==DEV[0] for q in qs),
            'top10_kinds':{k:dict(v) for k,v in arxiv.items()},'footnotes':footrecord},'E':misses,'A1_exact_inputs':examples,
            'tune_ranks':[{'id':q['id'],'prefix':{ab:best_rank(q,s) for ab,s in zip(('bm25','vector','hybrid'),ranking[(True,q['id'])])},
                           'no_prefix':{ab:best_rank(q,s) for ab,s in zip(('bm25','vector','hybrid'),ranking[(False,q['id'])])}} for q in qs]}
    if (OUT/'live-vectors.json').exists():result['A']=live_analysis(qs,rows,by,qvecs,vectors,load(OUT/'live-vectors.json'))
    if (OUT/'memory.json').exists():
        result['F']=[{'num_ctx':x['requested_num_ctx'], 'stable_after':x['after'],
                      'observed_peak_server_rss_kib':x['observed_peak_server_rss_kib']} for x in load(OUT/'memory.json')]
    result['offline_model_calls']=0
    save(OUT/'diagnosis.json',result)
    return result


SYNTHETIC=(
 ('Which material coats the fictional Luma beacon?', 'The fictional Luma beacon is coated with violet ceramic.',
  ['The Neri beacon uses a copper housing.','A violet ceramic vase sits in the museum.','The Luma beacon flashes twice each evening.','Weather sensors measure humidity at the harbor.']),
 ('Why did the invented Tavo library move its book return?', 'The invented Tavo library moved its book return to keep returned books dry during rain.',
  ['The Miko library expanded its reading room.','Tavo library lends maps every Tuesday.','Rain fell near the railway station.','A book return can be painted yellow.']),
 ('How do fictional Zevi gardeners prevent seedlings from freezing?', 'Fictional Zevi gardeners wrap seedlings in felt overnight to prevent freezing.',
  ['Zevi gardeners harvest pears in autumn.','Felt is stored in a locked cupboard.','Seedlings need careful watering in summer.','The Doro team protects pipes with foam.']),
 ('Where does the imaginary Kela ferry store emergency blankets?', 'The imaginary Kela ferry stores emergency blankets in a cabinet beneath the captain’s seat.',
  ['The Kela ferry docks beside a stone tower.','Blankets are woven in the town workshop.','A passenger seat has a red cushion.','The Vuna ferry keeps life jackets above its door.']),
 ('What triggers the invented Pavo observatory’s backup lamps?', 'The invented Pavo observatory switches on backup lamps when its main power circuit fails.',
  ['The Pavo observatory cleans lenses at dawn.','Backup maps are kept in the reception desk.','The main gate closes after sunset.','The Seli observatory turns fans on when rooms become warm.']),
)


def live_analysis(qs,rows,by,qvecs,vectors,live):
    target_ids=sorted(live['targets']);pool=[r for r in rows if r['chunk_id'] in target_ids]
    variants={};allranks=[]
    for variant in VARIANTS:
        ranks={};mixed={};poolranks={}
        for q in qs:
            v=live['queries'][q['id']][variant]['vector'];stream=cosine(rows,v,vectors['doc-input-v1'])
            ranks[q['id']]=best_rank(q,stream)
            alt=dict(vectors['doc-input-v1'])
            # Only approved tune targets reembedded; global background stays frozen.
            for cid in target_ids:
                r=by[cid];alt[(r['source_id'],cid)]=live['targets'][cid]['eos' if variant.endswith('_eos') else 'base']['vector']
            mixed[q['id']]=best_rank(q,cosine(rows,v,alt));poolranks[q['id']]=best_rank(q,cosine(pool,v,alt))
            allranks.append({'id':q['id'],'variant':variant,'fixed_document_corpus_rank':ranks[q['id']],
                             'target_replacement_corpus_rank':mixed[q['id']], 'uniform_tune_target_pool_rank':poolranks[q['id']]})
        variants[variant]={'fixed_documents':quality(qs,ranks),'target_only_replacement':quality(qs,mixed),'uniform_tune_target_pool':quality(qs,poolranks)}
    synthetic=[]
    for i,item in enumerate(live['synthetic']):
        for variant in VARIANTS:
            qv=item['queries'][variant]['vector'];docs=item['docs']['eos' if variant.endswith('_eos') else 'base']['vectors']
            scored=sorted(enumerate(docs),key=lambda iv:(-math.fsum(a*b for a,b in zip(qv,iv[1],strict=True)),iv[0]))
            synthetic.append({'set':i+1,'variant':variant,'answer_rank':next(j for j,(index,v) in enumerate(scored,1) if index==0)})
    def delta(a,b):return {'max_abs':max(abs(x-y) for x,y in zip(a,b,strict=True)), 'l2':math.sqrt(math.fsum((x-y)**2 for x,y in zip(a,b,strict=True)))}
    checks={'query_fresh_vs_cached':[{'id':q['id'],**delta(live['queries'][q['id']]['space']['vector'],qvecs[sha(query_input(q['question']))])} for q in qs],
            'target_fresh_vs_cached':[{'chunk_id':cid,**delta(item['base']['vector'],vectors['doc-input-v1'][(by[cid]['source_id'],cid)])} for cid,item in sorted(live['targets'].items())],
            'target_eos_vs_base':[{'chunk_id':cid,**delta(item['base']['vector'],item['eos']['vector']),
                                   'prompt_eval_count_delta':item['eos']['prompt_eval_count']-item['base']['prompt_eval_count']} for cid,item in sorted(live['targets'].items())],
            'query_eos_token_deltas':[{'id':q['id'],'space':live['queries'][q['id']]['space_eos']['prompt_eval_count']-live['queries'][q['id']]['space']['prompt_eval_count'],
                                     'no_space':live['queries'][q['id']]['no_space_eos']['prompt_eval_count']-live['queries'][q['id']]['no_space']['prompt_eval_count']} for q in qs]}
    return {'variants':variants,'ranks':allranks,'synthetic':synthetic,'checks':checks,
            'scope_note':'Fixed documents tests query formats globally over975 chunks. EOS documents tested on all21 unique reachable tune target chunks only; mixed-corpus ranks are not an all-document EOS retrieval run. Unreachable question has no target.'}


def is_server_process(args):
    parts=args.split()
    return bool(parts) and ((Path(parts[0]).name=='ollama' and 'serve' in parts[1:]) or
                            (Path(parts[0]).name=='llama-server' and '/ollama/' in parts[0]))


def process_snapshot():
    ps=subprocess.run(['ollama','ps'],capture_output=True,text=True,check=True).stdout
    records=[]
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():continue
        try:
            args=(directory/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
            if not is_server_process(args):continue
            status=(directory/'status').read_text();rss=next(int(l.split()[1]) for l in status.splitlines() if l.startswith('VmRSS:'))
            records.append({'pid':int(directory.name),'cmdline':args,'rss_kib':rss})
        except (OSError,StopIteration):continue
    return {'ollama_ps':ps,'processes':records,'rss_sum_kib':sum(r['rss_kib'] for r in records)}


def live_run():
    if (OUT/'embedding-calls.json').exists() or (OUT/'live-vectors.json').exists():raise ValueError('LIVE_OUTPUT_EXISTS_NO_OVERWRITE')
    qs,repo,rows,by,qvecs,vectors=inputs();transport=BudgetTransport(OUT);embedder=Embedder(transport);embedder.check_digest()
    save(OUT/'model-show.json',transport.request('/api/show',{'model':MODEL}))
    live={'digest':DIGEST,'synthetic':[],'queries':{},'targets':{}}
    def embed(texts,phase,num_ctx=32768):
        transport.phase=phase
        vs=embedder.embed(texts,num_ctx=num_ctx)
        return {'vectors':vs,'prompt_eval_count':transport.calls[-1]['prompt_eval_count']}
    for i,(question,answer,distractors) in enumerate(SYNTHETIC):
        docs=[answer,*distractors];item={'question':question,'documents':docs,'docs':{},'queries':{}}
        for name,suffix in (('base',''),('eos',EOS)):item['docs'][name]=embed([t+suffix for t in docs],f'A2/A3 synthetic{i+1} documents {name}')
        for variant in VARIANTS:
            value=embed([query_variant(question,variant)],f'A2/A3 synthetic{i+1} query {variant}')
            item['queries'][variant]={'vector':value['vectors'][0],'prompt_eval_count':value['prompt_eval_count']}
        live['synthetic'].append(item);save(OUT/'live-vectors.partial.json',live)
    for q in qs:
        live['queries'][q['id']]={}
        for variant in VARIANTS:
            value=embed([query_variant(q['question'],variant)],f'A3 tune {q["id"]} {variant}')
            live['queries'][q['id']][variant]={'vector':value['vectors'][0],'prompt_eval_count':value['prompt_eval_count']}
        save(OUT/'live-vectors.partial.json',live)
    target_ids=sorted({cid for q in qs for cid in q['relevant_chunk_ids']})
    for cid in target_ids:
        r=by[cid];text=r['context_prefix']+'\n\n'+r['text'];live['targets'][cid]={}
        for name,suffix in (('base',''),('eos',EOS)):
            value=embed([text+suffix],f'A3 target {cid} {name}')
            live['targets'][cid][name]={'vector':value['vectors'][0],'prompt_eval_count':value['prompt_eval_count']}
        save(OUT/'live-vectors.partial.json',live)
    save(OUT/'live-vectors.json',live);result=offline()
    # A must be reviewed before F. No automatic proceeding past the correctness gate.
    print('A COMPLETE; review diagnosis.json before separate --memory',flush=True)


def memory_run():
    if (OUT/'memory.json').exists():raise ValueError('MEMORY_OUTPUT_EXISTS_NO_OVERWRITE')
    qs,repo,rows,by,qvecs,vectors=inputs()
    transport=BudgetTransport(OUT);transport.calls=load(OUT/'embedding-calls.json');embedder=Embedder(transport)
    chosen=sorted(rows,key=lambda r:r['chunk_id'])[:8]
    texts=[r['context_prefix']+'\n\n'+r['text'] for r in chosen]
    result=[]
    # Finish on the production context; no persisted model/config changes.
    for ctx in (4096,32768):
        transport.phase=f'F memory context{ctx}';samples=[];done=threading.Event();errors=[]
        def sample():
            while not done.is_set():
                try:samples.append(process_snapshot())
                except Exception as exc:errors.append(str(exc))
                done.wait(.5)
        thread=threading.Thread(target=sample);thread.start()
        try:embedder.embed(texts,num_ctx=ctx)
        finally:done.set();thread.join()
        after=process_snapshot();samples.append(after)
        result.append({'requested_num_ctx':ctx,'input_sha256':[sha(t) for t in texts],'chunk_ids':[r['chunk_id'] for r in chosen],
                       'samples':samples,'sampling_errors':errors,'after':after,
                       'observed_peak_server_rss_kib':max(s['rss_sum_kib'] for s in samples),
                       'note':'Peak sampled at0.5s; startup overlap may include both contexts. Use stable after snapshot for context comparison.'})
        save(OUT/'memory.partial.json',result)
    save(OUT/'memory.json',result)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--memory',action='store_true');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.live:live_run()
    elif args.memory:memory_run()
    else:offline();print('OFFLINE replay complete; model calls0',flush=True)


if __name__=='__main__':main()
