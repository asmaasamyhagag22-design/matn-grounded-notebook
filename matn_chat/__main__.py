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
    ask=sub.add_parser('ask');ask.add_argument('--notebook',required=True);ask.add_argument('--sources',required=True)
    ask.add_argument('--notebook-id');ask.add_argument('--structures-manifest');ask.add_argument('--query-cache');ask.add_argument('question')
    args=parser.parse_args();repo=None
    try:
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
        documents=[]
        for row in rows:
            if row['id'] not in selected:continue
            path=Path(manifest['documents'][row['doc_id']])
            if not path.is_absolute():path=manifest_path.parent/path
            d=DocumentStructure.model_validate_json(path.read_bytes())
            if d.doc_id!=row['doc_id']:raise ValueError('SNAPSHOT_DOC_ID')
            documents.append(d)
        search=Search(repo,Embedder())
        query_cache=Path(args.query_cache or str(args.notebook)+'.queries.json')
        if query_cache.exists():
            cached=json.loads(query_cache.read_text())
            if cached['digest']!=DIGEST or cached['input_version']!=QUERY_INPUT_VERSION:raise ValueError('QUERY_CACHE_VERSION')
            search.query_vectors={tuple(r['key']):r['vector'] for r in cached['entries']}
        result=ChatEngine(search,documents).ask(notebook,selected,args.question)
    except Exception as exc:
        result={'schema_version':1,'state':'error','message':'Chat failed closed.','sentences':[],
                'receipts':[],'dropped_sentences':0,'discarded_candidates':0,'error':type(exc).__name__,'timings':{}}
    finally:
        if repo is not None:repo.db.close()
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,allow_nan=False))
    return 1 if result['state']=='error' else 0


if __name__=='__main__':raise SystemExit(main())
