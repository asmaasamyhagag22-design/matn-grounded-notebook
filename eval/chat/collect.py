"""Resumable local realistic-v2 collection; frozen60 first, then confirmation, 10h max."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from eval.verification.coverage import load_documents,DEV_PATHS
from eval.verification.v2 import save,sha
from matn_rag.contracts import canonical
from matn_rag.embedding import Embedder,DIGEST,QUERY_INPUT_VERSION
from matn_rag.search import Search
from matn_chat.__main__ import ReadOnlyNotebook
from matn_chat.engine import ChatEngine,first_failure
from matn_chat.handles import build_handles
from matn_chat.generation import LocalGenerator,GENERATOR_DIGEST,PROMPT_VERSION,payload
from .realistic import render_packet,summarize


class CachedGeneration:
    def __init__(self,root,generator,*,deadline,binding):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.generator=generator;self.deadline=deadline;self.binding=binding;self.cache_hits=0;self.calls=[]
    def generate(self,body):
        key=sha(canonical(body));path=self.root/(key+'.json')
        if path.exists():
            record=json.loads(path.read_text())
            if record['binding']!=self.binding or record['payload_sha256']!=key or sha(canonical(record['raw']))!=record['raw_sha256']:
                raise ValueError('GENERATION_CHECKPOINT_DRIFT')
            self.cache_hits+=1;self.calls.append({'cache_hit':True,'original_seconds':record['seconds'],'payload_sha256':key})
            return record['raw']
        remaining=self.deadline-time.time()
        if remaining<=1:raise TimeoutError('COLLECTION_CAP_REACHED')
        if isinstance(self.generator,LocalGenerator):
            self.generator.timeout=min(7200,remaining);self.generator.deadline=self.deadline
        save(self.root/(key+'.input.json'),{'binding':self.binding,'payload':body,'payload_sha256':key})
        start=time.perf_counter()
        raw=self.generator.generate(body);seconds=time.perf_counter()-start
        record={'binding':self.binding,'payload_sha256':key,'raw':raw,'raw_sha256':sha(canonical(raw)),'seconds':seconds}
        save(path,record);self.calls.append({'cache_hit':False,'original_seconds':seconds,'payload_sha256':key})
        return raw


def integrity(root):
    state=json.loads((root/'start.json').read_text())
    if sha(Path('reports/r-lite-diagnostics.md').read_bytes())!=state['owner_sha256']:raise RuntimeError('HARD_STOP_OWNER_DRIFT')
    for p,digest in {**state['protected_sha256'],**state['local_freezes'],**state['v1_originals']}.items():
        if sha(Path(p).read_bytes())!=digest:raise RuntimeError('HARD_STOP_PROTECTED_DRIFT:'+p)


def questions():
    raw=json.loads(Path('eval/rag/frozen/questions.json').read_text())['items']
    extra=json.loads(Path('out/rr1/questions.json').read_text())['confirmation']
    assert len(raw)==60 and len(extra)==39
    vnr=json.loads(Path('eval/rag/vnr-confirmation-freeze.json').read_text())
    assert {r['id'] for r in extra if r['source']=='egypt-2021-vnr'}==set(vnr['ids'])
    for p in ['eval/rag/wef-confirmation-freeze.json','eval/rag/vnr-confirmation-freeze.json']:
        freeze=json.loads(Path(p).read_text());assert sha(Path(freeze['path']).read_bytes())==freeze['sha256']
    result=[{'id':r['id'],'split':r['split'],'question':r['question'],'source':r.get('source'),
        'cohort':cohort} for cohort,items in [('frozen60',raw),('confirmation',extra)] for r in items]
    assert len({r['id'] for r in result})==99
    return result


def query_cache():
    entries={}
    for name in ['out/rag-core/part2/query-cache.json','out/vnr-d2/query-cache.json']:
        data=json.loads(Path(name).read_text())
        assert data['digest']==DIGEST and data['input_version']==QUERY_INPUT_VERSION
        for row in data['entries']:
            key=tuple(row['key'])
            if key in entries and entries[key]!=row['vector']:raise ValueError('QUERY_CACHE_CONFLICT')
            entries[key]=row['vector']
    return entries


def baseline():
    rows=[]
    for split in ['tune','check']:
        for r in json.loads(Path(f'out/v3/{split}-MiniCheck-RoBERTa-Large-receipts.json').read_text()):
            if r['set']=='realistic-v1':rows.append(r)
    from collections import Counter
    return {'sentences':len(rows),'first_failure':dict(Counter((first_failure(r['receipt']) or {}).get('layer','verified') for r in rows)),
        'scope':'original realistic-v1 sentences, n=60, not the claim-weighted n=80 V3 table; same fixed verifier, seen outputs, descriptive only'}


def collect(root=Path('out/c1'),cap_seconds=36000,limit=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    lock=(root/'collection.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    integrity(root)
    if not 0<cap_seconds<=36000:raise ValueError('INVALID_CAP')
    qs=questions();documents_by_name=load_documents();docs=tuple(documents_by_name.values());source=Path('out/vnr-d2/confirmation.sqlite');dbpath=root/'retrieval.sqlite'
    if not dbpath.exists():shutil.copy2(source,dbpath)
    repo=ReadOnlyNotebook(dbpath);notebook='dev5';selected=repo.source_ids(notebook)
    cached=query_cache();search=Search(repo,Embedder());search.query_vectors=dict(cached)
    identity={'version':'chat-realistic-v2-collection-v1','prompt_version':PROMPT_VERSION,'generator_digest':GENERATOR_DIGEST,
        'generator_settings':{k:v for k,v in payload('q',{}).items() if k!='prompt'},'question_projection_sha256':sha(canonical(qs)),
        'source_database_sha256':sha(source.read_bytes()),'private_index_sha256':sha(dbpath.read_bytes()),'source_files_sha256':{p:sha(Path(p).read_bytes()) for p in DEV_PATHS.values()},
        'code_sha256':{str(p):sha(p.read_bytes()) for directory in ['matn_chat','matn_verification','matn_rag','eval/chat'] for p in sorted(Path(directory).glob('*.py'))},
        'label_state':'UNLABELED / NOT FROZEN','retrieval':'unchanged C1, dev5, focused top10, no reranker',
        'cap_seconds':cap_seconds,'order':'all frozen60 existing splits first; then all39 confirmation, descriptive only',
        'query_cache_sha256':{p:sha(Path(p).read_bytes()) for p in ['out/rag-core/part2/query-cache.json','out/vnr-d2/query-cache.json']}}
    identity_sha=sha(canonical(identity));settings=root/'generation-settings.json'
    if settings.exists():
        if sha(canonical(json.loads(settings.read_text())))!=identity_sha:raise ValueError('COLLECTION_IDENTITY_DRIFT')
    else:save(settings,identity)
    # Sidecars are private Chat artifacts; the source index and retrieval code stay untouched.
    save(str(dbpath)+'.structures.json',{'version':1,'documents':{d.doc_id:str(Path(DEV_PATHS[name]).resolve()) for name,d in documents_by_name.items()}})
    save(str(dbpath)+'.queries.json',{'digest':DIGEST,'input_version':QUERY_INPUT_VERSION,'entries':[{'key':list(k),'vector':v} for k,v in sorted(cached.items())]})
    control_path=root/'run-control.json'
    if control_path.exists():
        control=json.loads(control_path.read_text());assert control['identity_sha256']==identity_sha
    else:
        now=time.time();control={'started_wall':now,'deadline_wall':now+cap_seconds,'identity_sha256':identity_sha};save(control_path,control)
    client=LocalGenerator();engine=ChatEngine(search,docs,generator=client);rows=[];deferred=[]
    try:
        for q in qs[:limit]:
            integrity(root)
            for p,digest in {**identity['source_files_sha256'],**identity['code_sha256'],**identity['query_cache_sha256']}.items():
                if sha(Path(p).read_bytes())!=digest:raise RuntimeError('COLLECTION_BINDING_DRIFT:'+p)
            path=root/'questions'/(q['id']+'.json')
            if time.time()>=control['deadline_wall']-2 and not path.exists():
                deferred=[{'id':r['id'],'cohort':r['cohort'],'reason':'10-hour collection cap'} for r in qs if not (root/'questions'/(r['id']+'.json')).exists()]
                break
            if sha(dbpath.read_bytes())!=identity['private_index_sha256']:raise RuntimeError('HARD_STOP_PRIVATE_INDEX_DRIFT')
            before=len(search.query_vectors)
            binding=sha(canonical({'identity_sha256':identity_sha,'question':q}))
            if path.exists():
                row=json.loads(path.read_text())
                if row['binding']!=binding:raise ValueError('QUESTION_CHECKPOINT_DRIFT')
            else:
                generator=CachedGeneration(root/'generation'/q['id'],client,deadline=control['deadline_wall'],binding=binding)
                engine.generator=generator
                started=time.perf_counter();response=engine.ask(notebook,selected,q['question'])
                save(root/'inputs'/(q['id']+'.json'),{'binding':binding,'question':q,'retrieval':engine.retrieval,'handles':engine.handles})
                row={**q,'binding':binding,'response':response,'trace':engine.trace,'handles':engine.handles,
                    'embedding_cache_misses':len(search.query_vectors)-before,'generation_calls':generator.calls,
                    'partial_generation_cache_hits':generator.cache_hits,'question_active_seconds':time.perf_counter()-started,
                    'original_generation_seconds':sum(r['original_seconds'] for r in generator.calls),
                    'timing_scope':'active engine wall per answer; setup/snapshot load excluded; partial-resume cache hits preserve original call costs separately'}
                save(path,row)
            rows.append(row)
            summary=summarize(rows);summary.update({'required_frozen60':60,'optional_confirmation':39,'completed_question_checkpoints':len(rows),
                'deadline_wall':control['deadline_wall'],'state':'running','deferred_questions':deferred,'baseline_realistic_v1':baseline(),
                'embedding_cache_misses':sum(r['embedding_cache_misses'] for r in rows)})
            save(root/'generation-summary.json',summary)
            (root/'realistic-v2-labeling-packet.md').write_text(render_packet(rows))
            print(q['cohort'],q['id'],row['response']['state'],
                  'sentences',len(row['response']['sentences']),'calls',len(row['generation_calls']),'seconds',round(row['question_active_seconds'],2),flush=True)
    finally:repo.db.close();fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
    summary=summarize(rows);summary.update({'required_frozen60':60,'optional_confirmation':39,'completed_question_checkpoints':len(rows),
        'deadline_wall':control['deadline_wall'],'started_wall':control['started_wall'],'ended_wall':time.time(),
        'state':'complete' if len(rows)==len(qs) else 'cap_reached' if deferred else 'limited_run',
        'deferred_questions':deferred,'baseline_realistic_v1':baseline(),'embedding_cache_misses':sum(r['embedding_cache_misses'] for r in rows)})
    save(root/'generation-summary.json',summary)
    packet=render_packet(rows)
    for q in deferred:packet+=f"\n## {q['id']} — {q['cohort']}\n\nDEFERRED: 10-hour cap; no generation.\n"
    (root/'realistic-v2-labeling-packet.md').write_text(packet)
    save(str(dbpath)+'.queries.json',{'digest':DIGEST,'input_version':QUERY_INPUT_VERSION,'entries':[{'key':list(k),'vector':v} for k,v in sorted(search.query_vectors.items())]})
    integrity(root)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path('out/c1'))
    parser.add_argument('--cap-seconds',type=int,default=36000);parser.add_argument('--limit',type=int)
    args=parser.parse_args();print(json.dumps(collect(args.root,args.cap_seconds,args.limit),indent=2))


if __name__=='__main__':main()
