"""Read-only notebook CLI. Authoritative snapshots are bound by a local sidecar."""
import argparse
import json
from pathlib import Path
import sqlite3
from matn_contracts.structure import DocumentStructure
from matn_rag.sqlite import SQLiteRepository
from matn_rag.search import Search
from matn_rag.embedding import Embedder,DIGEST,QUERY_INPUT_VERSION
from .engine import ChatEngine


class ReadOnlyNotebook(SQLiteRepository):
    def __init__(self,path):
        path=Path(path).resolve()
        if not path.is_file():raise ValueError('NOTEBOOK_MISSING')
        self.db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        self.db.row_factory=sqlite3.Row;self.revision=0
        self.db.execute('PRAGMA query_only=ON')


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    ask=sub.add_parser('ask');ask.add_argument('--notebook');ask.add_argument('--sources',default='all')
    ask.add_argument('--preserved-meaning',action='store_true',help='Opt-in Phase04 bounded scope checks, one redraft and labelled excerpt fallback');ask.add_argument('--notebook-id');ask.add_argument('--structures-manifest');ask.add_argument('--query-cache');ask.add_argument('question')
    ask.add_argument('--table-lookup',action='store_true',help='Exact available table row projection by header and source cell value')
    ask.add_argument('--neural-rerank',action='store_true',help='Experimental slower pinned neural candidate ranking')
    ask.add_argument('--rerank-cache')
    ask.add_argument('--reliable',action='store_true',help='Bounded candidate reranking and verified multi-source units')
    ask.add_argument('--lexical-only',action='store_true',help='Explicit BM25 candidate mode without query embedding')
    ask.add_argument('--ready',help='Pinned prepared PDF pointer (ready.json)')
    ask.add_argument('--session');ask.add_argument('--session-dir');ask.add_argument('--trace-output')
    prepare=sub.add_parser('prepare');prepare.add_argument('pdf');prepare.add_argument('--out',required=True)
    prepare.add_argument('--stop-after',type=int);prepare.add_argument('--publish-every',type=int,default=32)
    status=sub.add_parser('status');status.add_argument('--out',required=True)
    reset=sub.add_parser('reset-session');reset.add_argument('--session',required=True);reset.add_argument('--session-dir',required=True)
    migration=sub.add_parser('migrate-preparation')
    for key in ('pdf','source','out'):migration.add_argument('--'+key,required=True)
    combine=sub.add_parser('bundle');combine.add_argument('--document',action='append',default=[]);combine.add_argument('--ready',action='append',default=[])
    combine.add_argument('--embed-missing',action='store_true')
    combine.add_argument('--cache',action='append',default=[]);combine.add_argument('--out',required=True)
    restore=sub.add_parser('restore-layout');restore.add_argument('--cell-observations')
    for key in ('pdf','prepared','reference-input','reference-manifest','sidecar','out'):
        restore.add_argument('--'+key,required=True)
    args=parser.parse_args();repo=None
    if args.command=='migrate-preparation':
        from .migration import migrate
        print(migrate(args.pdf,args.source,args.out));return 0
    if args.command=='bundle':
        from .notebooks import bundle
        print(bundle(args.document,args.out,args.cache,Embedder() if args.embed_missing else None,args.ready));return 0
    if args.command=='restore-layout':
        from .notebooks import restore_layout
        print(restore_layout(args.pdf,args.prepared,args.reference_input,args.reference_manifest,args.sidecar,args.out,args.cell_observations));return 0
    if args.command=='prepare':
        from .readiness import prepare_pdf
        state=prepare_pdf(args.pdf,args.out,stop_after=args.stop_after,publish_every=args.publish_every)
        return 0 if state['status']=='complete' else 2
    if args.command=='status':
        root=Path(args.out);progress=json.loads((root/'progress.json').read_bytes())
        import fcntl
        with (root/'prepare.lock').open('a') as handle:
            try:
                fcntl.flock(handle,fcntl.LOCK_EX | fcntl.LOCK_NB)
                progress['active']=False
                fcntl.flock(handle,fcntl.LOCK_UN)
            except BlockingIOError:
                progress['active']=True
                progress['status']='processing'
        progress['extraction']=dict(completed=len(progress['extracted_pages']),remaining=progress['total_pages']-len(progress['extracted_pages']))
        required=set(progress.get('ocr_required_pages',[]))
        progress['ocr']=dict(completed=len(progress['ocr_pages']),remaining=sorted(required-set(progress['ocr_pages'])),triage_complete='ocr_required_pages' in progress)
        if (root/'ready.json').exists():
            from .readiness import load_ready
            progress['published']=load_ready(root/'ready.json')
        events=root/'events.jsonl'
        if events.exists():
            # The last line may be interrupted mid-write; ignore only that tail.
            for line in reversed(events.read_text().splitlines()):
                try:progress['last_event']=json.loads(line);break
                except json.JSONDecodeError:continue
        print(json.dumps(progress,ensure_ascii=False,sort_keys=True));return 0
    if args.command=='reset-session':
        import hashlib
        from .readiness import write,lock
        path=Path(args.session_dir)/(hashlib.sha256(args.session.encode()).hexdigest()+'.json')
        if path.exists():
            with lock(path.with_suffix('.lock')):
                value=json.loads(path.read_bytes());value['turns']=[];write(path,value)
        print(json.dumps(dict(state='context_cleared',session=args.session)));return 0
    receipt=None
    try:
        if args.ready:
            from .readiness import load_ready
            receipt=load_ready(args.ready);args.notebook=receipt['notebook']
        if not args.notebook:raise ValueError('NOTEBOOK_OR_READY_REQUIRED')
        repo=ReadOnlyNotebook(args.notebook)
        notebooks=[r[0] for r in repo.db.execute('SELECT id FROM notebooks ORDER BY id')]
        notebook=args.notebook_id or (notebooks[0] if len(notebooks)==1 else None)
        if notebook not in notebooks:raise ValueError('NOTEBOOK_ID_REQUIRED')
        rows=repo.source_rows(notebook);aliases={key:r['id'] for r in rows for key in (r['id'],r['doc_id'])}
        selected=repo.source_ids(notebook) if args.sources=='all' else [aliases[v] for v in args.sources.split(',')]
        repo.validate_selection(notebook,selected)
        manifest_path=Path(args.structures_manifest or str(args.notebook)+'.structures.json')
        manifest=json.loads(manifest_path.read_text())
        if manifest['version']!=1:raise ValueError('STRUCTURE_MANIFEST_VERSION')
        if manifest.get('index_mode')=='bm25':search_lexical=True
        else:search_lexical=False
        documents=[]
        for row in rows:
            if row['id'] not in selected:continue
            path=Path(manifest['documents'][row['doc_id']])
            if not path.is_absolute():path=manifest_path.parent/path
            d=DocumentStructure.model_validate_json(path.read_bytes())
            if d.doc_id!=row['doc_id']:raise ValueError('SNAPSHOT_DOC_ID')
            documents.append(d)
        search=Search(repo,Embedder(),lexical_only=bool(args.lexical_only or search_lexical or receipt and receipt['coverage']['index_mode']=='bm25'))
        query_cache=Path(args.query_cache or str(args.notebook)+'.queries.json')
        if query_cache.exists():
            cached=json.loads(query_cache.read_text())
            if cached['digest']!=DIGEST or cached['input_version']!=QUERY_INPUT_VERSION:raise ValueError('QUERY_CACHE_VERSION')
            search.query_vectors={tuple(r['key']):r['vector'] for r in cached['entries']}
        manifest_coverage={d.doc_id:receipt['coverage'] for d in documents} if receipt else manifest.get('source_coverage',{})
        manifest_revisions={d.doc_id:receipt['revision'] for d in documents} if receipt else manifest.get('source_revisions',{})
        from .preserved import PreservedChatEngine
        from .reliable import ReliableChatEngine
        cls=ReliableChatEngine if args.reliable else PreservedChatEngine if args.preserved_meaning else ChatEngine
        def run(question, query_plan=None):
            if args.table_lookup:
                from .table_lookup import lookup
                value=lookup(documents,question)
                from .notebooks import attach_source_context
                attach_source_context(value,documents,manifest_coverage,manifest_revisions)
                value['query_plan']=query_plan
                if receipt:
                    from .readiness import attach_coverage
                    attach_coverage(value,receipt)
                if args.trace_output:
                    from .readiness import write
                    write(args.trace_output,dict(question=question,response=value,trace=[]))
                return value
            if args.reliable:
                from .reliable import LocalReranker
                engine=cls(search,documents,reranker=LocalReranker(cache=args.rerank_cache) if args.neural_rerank else None,source_coverage=manifest_coverage,source_revisions=manifest_revisions)
            else:engine=cls(search,documents)
            value=engine.ask(notebook,selected,query_plan['current_question'],query_plan=query_plan) if args.reliable and query_plan else engine.ask(notebook,selected,question)
            value['query_plan']=query_plan
            if receipt:
                from .readiness import attach_coverage
                attach_coverage(value,receipt)
            if args.trace_output:
                from .readiness import write
                write(args.trace_output,dict(question=question,response=value,trace=engine.trace))
            return value
        if args.session:
            from .conversation import Conversation
            scope=dict(notebook=str(Path(args.ready or args.notebook).resolve()),documents=sorted(d.doc_id for d in documents))
            folder=args.session_dir or str(Path(args.ready or args.notebook).resolve().parent/'sessions')
            with Conversation(folder,args.session,scope) as conversation:
                plan=conversation.plan(args.question)
                effective=plan['retrieval_query']
                result=run(effective,plan);conversation.remember(args.question,effective,result)
        else:
            result=run(args.question)
    except Exception as exc:
        result={'schema_version':1,'state':'error','message':'Chat failed closed.','sentences':[],
                'receipts':[],'dropped_sentences':0,'discarded_candidates':0,'error':type(exc).__name__,'error_detail':str(exc),'timings':{}}
    finally:
        if repo is not None:repo.db.close()
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False))
    return 1 if result['state']=='error' else 0


if __name__=='__main__':raise SystemExit(main())
