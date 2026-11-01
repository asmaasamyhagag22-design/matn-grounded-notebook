"""Discovered sources into a notebook (NotebookLM "Discover" pattern), behind an explicit command.

Every complete, independent source a research run read is registered through the existing
notebook ingestion path (`matn_chat.notebooks.bundle`: validated DocumentStructure ->
`matn_rag.ingest.prepare` chunks -> embeddings -> SQLite index). The grounded Chat then
answers over them with its unchanged retrieval, verification and citation contracts.

  .venv/bin/python -B -m matn_research.notebook_import --run RUN_FOLDER --out NOTEBOOK_FOLDER [--embed-missing]
  .venv/bin/python -m matn_chat ask --notebook NOTEBOOK_FOLDER/notebook.db --reliable "question"
"""
import argparse
import json
from pathlib import Path

from matn_contracts.structure import DocumentStructure


def sources(run):
    """document.json paths of complete, independent reads, first occurrence per doc_id, in reading order."""
    run = Path(run); seen = set(); paths = []
    for r in json.loads((run / 'reading-status.json').read_bytes()):
        if r.get('status') != 'complete' or not r.get('independent'):
            continue
        path = run / 'sources' / Path(r['folder']).name / 'document.json'
        if not path.exists():
            path = Path(r['folder']) / 'document.json'
        d = DocumentStructure.model_validate_json(path.read_bytes())
        if d.doc_id not in seen:
            seen.add(d.doc_id); paths.append((path, r.get('final_url') or r['url']))
    return paths


def import_run(run, out, *, embedder=None, caches=()):
    from matn_chat.notebooks import bundle
    rows = sources(run)
    if not rows:
        raise ValueError('NO_COMPLETE_INDEPENDENT_SOURCES')
    db = bundle([p for p, _ in rows], out, caches=caches, embedder=embedder)
    manifest = dict(run=str(Path(run).resolve()), notebook=str(db), sources=[dict(document=str(p), url=u) for p, u in rows],
                    path='matn_chat.notebooks.bundle (existing ingestion); Chat and verification contracts unchanged')
    (Path(out) / 'research-import.json').write_text(json.dumps(manifest, indent=1))
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--run', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--embed-missing', action='store_true'); ap.add_argument('--cache', action='append', default=[])
    a = ap.parse_args(argv)
    embedder = None
    if a.embed_missing:
        from matn_rag.embedding import Embedder
        embedder = Embedder()
    print(json.dumps(import_run(a.run, a.out, embedder=embedder, caches=a.cache), indent=1))


if __name__ == '__main__':
    main()
