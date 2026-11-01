"""Reuse real reader checkpoints only when every preparation-code hash matches.

This copies no overview, verifier receipt, catalog, answer or model selection.
The destination app reranks and verifies evidence with its current implementation.
"""
import hashlib
import json
from pathlib import Path
import shutil
from matn_app.freeze import identity
from matn_app.runtime import ROOT
from matn_app.evidence import _source_cache
from matn_chat.readiness import binding,load_ready

PREFIXES=('matn_reading/','matn_rag/','matn_contracts/')
EXTRA={'matn_chat/readiness.py','eval/reading/thresholds.json'}
ARTIFACTS=('pages','ocr','glm-cache','revisions','progress.json','ready.json','digital.json.gz','events.jsonl')


def seed(source_app,source_identity,pdfs,destination_cache):
    recorded=json.loads(Path(source_identity).read_bytes())
    recorded=recorded.get('code',recorded)
    current=identity(ROOT)
    relevant=lambda files:{p:s for p,s in files.items() if p.startswith(PREFIXES) or p in EXTRA}
    if relevant(recorded['files'])!=relevant(current['files']):
        raise ValueError('PREPARATION_CODE_CHANGED_REEXTRACT_REQUIRED')
    rows=[]
    for pdf in map(Path,pdfs):
        expected={**binding(pdf),'embedding':None,'variant':'app-bm25-v1'}
        candidates=[]
        for path in (Path(source_app)/'source-cache').glob('*/progress.json'):
            state=json.loads(path.read_bytes())
            if state.get('binding')==expected:candidates.append(path.parent)
        if not candidates:continue
        source=candidates[-1]
        receipt=load_ready(source/'ready.json') if (source/'ready.json').exists() else None
        destination=_source_cache(pdf,destination_cache)
        if any(destination.iterdir()):raise ValueError('DESTINATION_CACHE_NOT_EMPTY')
        files={}
        for name in ARTIFACTS:
            old=source/name;new=destination/name
            if old.is_dir():shutil.copytree(old,new)
            elif old.is_file():shutil.copy2(old,new)
        for file in destination.rglob('*'):
            if file.is_file():files[str(file.relative_to(destination))]=hashlib.sha256(file.read_bytes()).hexdigest()
        rows.append(dict(source=str(source),destination=str(destination),doc_id=expected['doc_id'],
            ready_revision=receipt['revision'] if receipt else None,files=files,
            reused='reader/OCR/index only; all salience selections and verification receipts recomputed'))
    return dict(preparation_code_matches=True,source_identity=recorded['identity'],sources=rows,
                timing_label='warm reader checkpoints, fresh overview and question calls; not a cold upload measurement')
