"""Resumable local realistic-v2 collection; frozen60 first, then confirmation, 12h maximum, c1b identity."""
from __future__ import annotations
import argparse
import fcntl
import json
from pathlib import Path
import shutil
import time
from eval.verification.coverage import load_documents,DEV_PATHS
from eval.verification.v2 import save,sha
from matn_rag.contracts import canonical
from matn_rag.embedding import DIGEST,QUERY_INPUT_VERSION
from matn_rag.search import Search
from matn_chat.__main__ import ReadOnlyNotebook
from matn_chat.engine import ChatEngine
from matn_chat.generation import LocalGenerator,GENERATOR_DIGEST,PROMPT_VERSION,payload
from .realistic import render_packet
from .c1b_summary import summarize_run


from .collect import CachedGeneration, integrity as original_integrity, questions, query_cache, baseline
from .token_budget import TokenCounter
from matn_chat.memory import MemoryGuard,sample_memory
import subprocess
import threading


def integrity(root):
    original_integrity(root)
    state=json.loads((root/'start.json').read_text())
    for path,digest in state['c1_artifacts'].items():
        if sha(Path(path).read_bytes())!=digest:raise RuntimeError('HARD_STOP_C1_DRIFT:'+path)
    if subprocess.check_output(['git','diff','--cached','--name-only','--','reports/r-lite-diagnostics.md'],text=True):
        raise RuntimeError('HARD_STOP_OWNER_STAGED')


class CachedOnly:
    def check_digest(self):pass
    def embed(self,texts):raise RuntimeError('EMBEDDING_CACHE_MISS_REFUSED')


def assert_no_embedding(client):
    loaded=client.request('/api/ps').get('models',[])
    if any(m.get('name')!='qwen3.5:9b' for m in loaded):
        raise RuntimeError('UNEXPECTED_RESIDENT_MODEL:'+','.join(m.get('name','') for m in loaded))
    return loaded


def oom_evidence(root,since=None):
    if since is None:since=json.loads((root/'start.json').read_text())['started_wall']
    evidence=subprocess.run(['journalctl','-k','--since','@'+str(int(since)),'--no-pager'],capture_output=True,text=True)
    lines=[l for l in evidence.stdout.splitlines() if any(x in l.lower() for x in ('oom','killed process','out of memory'))]
    record={'since':since,'lines':lines,'returncode':evidence.returncode,'stderr':evidence.stderr}
    with (root/'oom-evidence.log').open('a') as f:f.write(json.dumps(record)+'\n')
    return record


class RunGenerator(CachedGeneration):
    def __init__(self,*args,engine,root_run,**kwargs):
        super().__init__(*args,**kwargs);self.engine=engine;self.root_run=root_run
    def generate(self,body):
        assert_no_embedding(self.generator)
        if (self.root_run/'corrective-unload.json').exists():self.engine.entailment.close()
        # Also protect the redraft, after L4 may have been loaded by verification.
        guard=MemoryGuard()
        if not guard.check(self.engine.entailment.close):
            self.engine.memory_guard.samples.extend(guard.samples)
            from matn_chat.engine import ChatFailure
            raise ChatFailure('deferred_memory')
        self.engine.memory_guard.samples.extend(guard.samples)
        try:return super().generate(body)
        except Exception:
            oom_evidence(self.root_run)
            raise


class MemoryMonitor:
    def __init__(self,path):self.path=path;self.stop=threading.Event();self.thread=threading.Thread(target=self.run,daemon=True)
    def run(self):
        with self.path.open('a') as f:
            while not self.stop.is_set():
                f.write(json.dumps(sample_memory())+'\n');f.flush();self.stop.wait(1)
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.stop.set();self.thread.join()




def collect(root=Path('out/c1b'),cap_seconds=43200,limit=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    lock=(root/'collection.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    integrity(root)
    if not 0<cap_seconds<=43200:raise ValueError('INVALID_CAP')
    qs=questions();smoke=[]
    for source_name in dict.fromkeys(q['source'] for q in qs if q['cohort']=='frozen60'):
        smoke.append(next(q for q in qs if q['cohort']=='frozen60' and q['split']=='tune' and q['source']==source_name))
    assert len(smoke)==3
    qs=smoke+[q for q in qs if q not in smoke]
    documents_by_name=load_documents();docs=tuple(documents_by_name.values());source=Path('out/vnr-d2/confirmation.sqlite');dbpath=root/'retrieval.sqlite'
    if not dbpath.exists():shutil.copy2(source,dbpath)
    repo=ReadOnlyNotebook(dbpath);notebook='dev5';selected=repo.source_ids(notebook)
    cached=query_cache();search=Search(repo,CachedOnly());search.query_vectors=dict(cached)
    identity={'version':'c1b','prompt_version':PROMPT_VERSION,'generator_digest':GENERATOR_DIGEST,
        'generator_settings':{k:v for k,v in payload('q',{}).items() if k!='prompt'},'question_projection_sha256':sha(canonical(qs)),
        'source_database_sha256':sha(source.read_bytes()),'private_index_sha256':sha(dbpath.read_bytes()),'source_files_sha256':{p:sha(Path(p).read_bytes()) for p in DEV_PATHS.values()},
        'code_sha256':{str(p):sha(p.read_bytes()) for directory in ['matn_chat','matn_verification','matn_rag','eval/chat'] for p in sorted(Path(directory).glob('*.py'))},
        'label_state':'UNLABELED / NOT FROZEN','retrieval':'unchanged C1, dev5, focused top10, no reranker',
        'cap_seconds':cap_seconds,'smoke_ids':[q['id'] for q in smoke],'order':'three frozen60 tune smoke questions (one per source); remaining frozen60; then39 confirmation',
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
        start_state=json.loads((root/'start.json').read_text());control={'started_wall':start_state['started_wall'],'deadline_wall':start_state['deadline_wall'],'identity_sha256':identity_sha};save(control_path,control)
    client=LocalGenerator();assert_no_embedding(client)
    smoke_failed=False
    counter=TokenCounter();engine=ChatEngine(search,docs,generator=client,memory_guard=MemoryGuard(),token_counter=counter);rows=[];deferred=[]
    # Exhaustive dry retrieval already demonstrated all99 cache hits; refuse every embedding fallback.
    preflight=json.loads((root/'preflight.json').read_text())
    assert len(preflight['questions'])==99 and not preflight['overflows'] and preflight['embedding_calls']==0
    monitor=MemoryMonitor(root/'memory.jsonl');monitor.__enter__()
    try:
        for q in qs[:limit]:
            integrity(root)
            for p,digest in {**identity['source_files_sha256'],**identity['code_sha256'],**identity['query_cache_sha256']}.items():
                if sha(Path(p).read_bytes())!=digest:raise RuntimeError('COLLECTION_BINDING_DRIFT:'+p)
            path=root/'questions'/(q['id']+'.json')
            if time.time()>=control['deadline_wall']-2 and not path.exists():
                deferred=[{'id':r['id'],'cohort':r['cohort'],'reason':'12-hour collection cap'} for r in qs if not (root/'questions'/(r['id']+'.json')).exists()]
                break
            if sha(dbpath.read_bytes())!=identity['private_index_sha256']:raise RuntimeError('HARD_STOP_PRIVATE_INDEX_DRIFT')
            before=len(search.query_vectors)
            binding=sha(canonical({'identity_sha256':identity_sha,'question':q}))
            if path.exists():
                row=json.loads(path.read_text())
                if row['binding']!=binding:raise ValueError('QUESTION_CHECKPOINT_DRIFT')
            else:
                generator=RunGenerator(root/'generation'/q['id'],client,deadline=control['deadline_wall'],binding=binding,engine=engine,root_run=root)
                engine.generator=generator
                started=time.perf_counter();response=engine.ask(notebook,selected,q['question'])
                save(root/'inputs'/(q['id']+'.json'),{'binding':binding,'question':q,'retrieval':engine.retrieval,'handles':engine.handles})
                row={**q,'binding':binding,'response':response,'trace':engine.trace,'handles':engine.handles,
                    'embedding_cache_misses':len(search.query_vectors)-before,'generation_calls':generator.calls,
                    'partial_generation_cache_hits':generator.cache_hits,'question_active_seconds':time.perf_counter()-started,
                    'original_generation_seconds':sum(r['original_seconds'] for r in generator.calls),
                    'memory_after':sample_memory(),
                    'timing_scope':'active engine wall per answer; setup/snapshot load excluded; partial-resume cache hits preserve original call costs separately'}
                save(path,row)
            rows.append(row)

            if len(rows)==3:
                errors=[r for r in rows if r['response']['state']=='error']
                oom=oom_evidence(root)
                save(root/'smoke.json',{'ids':[r['id'] for r in rows],'errors':len(errors),'oom_evidence':oom})
                if errors or oom['lines']:
                    if not errors:errors=list(rows)
                    corrective_started=time.time()
                    # One documented corrective setting: unload L4 before every generation.
                    save(root/'corrective-unload.json',{'reason':'smoke error','setting':'close L4 before every generation','original_errors':[r['id'] for r in errors]})
                    engine.entailment.close()
                    repaired=[]
                    for original in errors:
                        repair_binding=sha(canonical({'binding':original['binding'],'corrective_unload':True}))
                        engine.generator=RunGenerator(root/'smoke-correction'/original['id'],client,deadline=control['deadline_wall'],binding=repair_binding,engine=engine,root_run=root)
                        result=engine.ask(notebook,selected,original['question'])
                        repair={**original,'response':result,'trace':engine.trace,'handles':engine.handles}
                        save(root/'smoke-correction-questions'/(original['id']+'.json'),repair);repaired.append(repair)
                    corrective_oom=oom_evidence(root,corrective_started)
                    if any(r['response']['state']=='error' for r in repaired) or corrective_oom['lines']:
                        smoke_failed=True
                        deferred=[{'id':r['id'],'cohort':r['cohort'],'reason':'smoke still errors after one corrective setting'} for r in qs if not (root/'questions'/(r['id']+'.json')).exists()]
                        break
            summary=summarize_run(rows,[json.loads(l) for l in (root/'memory.jsonl').read_text().splitlines() if l]);summary.update({'required_frozen60':60,'optional_confirmation':39,'completed_question_checkpoints':len(rows),
                'deadline_wall':control['deadline_wall'],'state':'running','deferred_questions':deferred,'baseline_realistic_v1':baseline(),
                'embedding_cache_misses':sum(r['embedding_cache_misses'] for r in rows)})
            save(root/'generation-summary.json',summary)
            (root/'realistic-v2-labeling-packet.md').write_text(render_packet(rows))
            print(q['cohort'],q['id'],row['response']['state'],
                  'sentences',len(row['response']['sentences']),'calls',len(row['generation_calls']),'seconds',round(row['question_active_seconds'],2),flush=True)
    finally:
        monitor.__exit__();engine.entailment.close();counter.close();repo.db.close();fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
    summary=summarize_run(rows,[json.loads(l) for l in (root/'memory.jsonl').read_text().splitlines() if l]);summary.update({'required_frozen60':60,'optional_confirmation':39,'completed_question_checkpoints':len(rows),
        'deadline_wall':control['deadline_wall'],'started_wall':control['started_wall'],'ended_wall':time.time(),
        'state':'smoke_failed' if smoke_failed else 'complete' if len(rows)==len(qs) else 'cap_reached' if deferred else 'limited_run',
        'deferred_questions':deferred,'baseline_realistic_v1':baseline(),'embedding_cache_misses':sum(r['embedding_cache_misses'] for r in rows)})
    save(root/'generation-summary.json',summary)
    packet=render_packet(rows)
    corrections=[json.loads(p.read_text()) for p in sorted((root/'smoke-correction-questions').glob('*.json'))]
    if corrections:packet+='\n# Smoke corrective attempts (additional audit only)\n'+render_packet(corrections)
    for q in deferred:packet+=f"\n## {q['id']} — {q['cohort']}\n\nDEFERRED: {q['reason']}; no generation.\n"
    (root/'realistic-v2-labeling-packet.md').write_text(packet)
    save(str(dbpath)+'.queries.json',{'digest':DIGEST,'input_version':QUERY_INPUT_VERSION,'entries':[{'key':list(k),'vector':v} for k,v in sorted(search.query_vectors.items())]})
    integrity(root)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=Path('out/c1b'))
    parser.add_argument('--cap-seconds',type=int,default=43200);parser.add_argument('--limit',type=int)
    args=parser.parse_args();print(json.dumps(collect(args.root,args.cap_seconds,args.limit),indent=2))


if __name__=='__main__':main()
