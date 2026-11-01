"""Build a new reviewable notebook from validated local snapshots and exact caches."""
import json
from pathlib import Path
from matn_contracts.structure import DocumentStructure
from matn_rag.sqlite import SQLiteRepository
from matn_rag.ingest import prepare
from matn_rag.embedding import DIGEST
from .readiness import write, sha


def bundle(documents, output, caches=(), embedder=None, readies=()):
    from .readiness import load_ready
    documents=list(documents);caches=list(caches);coverage={};revisions={}
    for pointer in readies:
        receipt=load_ready(pointer);path=Path(receipt['notebook']).parent/'document.json'
        d=DocumentStructure.model_validate_json(path.read_bytes())
        documents.append(path);caches.append(receipt['notebook'])
        coverage[d.doc_id]=receipt['coverage'];revisions[d.doc_id]=receipt['revision']
    if not documents:raise ValueError('DOCUMENTS_OR_READY_REQUIRED')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    repo=SQLiteRepository(output/'notebook.db');opened=[];sources=[];new_embeddings=0
    try:
        from .__main__ import ReadOnlyNotebook
        opened=[ReadOnlyNotebook(p) for p in caches]
        seen=set();manifest={};mode='hybrid-no-prefix'
        for path in documents:
            path=Path(path).resolve();raw=path.read_bytes()
            d=DocumentStructure.model_validate_json(raw)
            if d.doc_id in seen:raise ValueError('DUPLICATE_DOCUMENT')
            seen.add(d.doc_id)
            metadata,chunks=prepare(d);repo.create_notebook('reliable')
            sid=repo.add_source('reliable',d.doc_id,metadata,chunks)
            target=output/(d.doc_id+'.json');target.write_bytes(raw);manifest[d.doc_id]=str(target)
            reused=0
            for chunk in chunks:
                text=chunk['text'];v=None
                for cache in opened:
                    v=cache.get_embedding(DIGEST,'doc-input-no-prefix-v1',text)
                    if v is not None:break
                if v is None and embedder is not None:
                    embedder.check_digest();v=embedder.embed([text])[0];new_embeddings+=1
                if v is None:mode='bm25';continue
                repo.put_embedding(DIGEST,'doc-input-no-prefix-v1',text,v)
                repo.link_embedding(sid,chunk['chunk_id'],'doc-input-no-prefix-v1',DIGEST,'doc-input-no-prefix-v1',text);reused+=1
            sources.append(dict(doc_id=d.doc_id,path=str(path),sha256=sha(raw),chunks=len(chunks),reused_vectors=reused))
        integrity=repo.integrity()
        if integrity['foreign_key_errors'] or integrity['orphan_embeddings']:raise ValueError('BUNDLE_INTEGRITY')
        write(output/'notebook.db.structures.json',dict(version=1,documents=manifest,index_mode=mode,source_coverage=coverage,source_revisions=revisions))
        write(output/'bundle.json',dict(version=1,sources=sources,index_mode=mode,integrity=integrity,
                                      new_extraction_calls=0,new_ocr_calls=0,new_embedding_calls=new_embeddings))
    finally:
        repo.db.close()
        for cache in opened:cache.db.close()
    return output/'notebook.db'


def restore_layout(pdf, prepared, reference_input, reference_manifest, sidecar, output, cell_observations=None):
    """Reuse existing layout only after complete source, reader and page matching.

    No detector-only numeric promotion. Existing cell observations remain as-is;
    unavailable tables retain their original reasons.
    """
    from .readiness import load_page
    from matn_reading.structure.document import write_structure
    from matn_reading.structure.cache import core_fingerprint
    pdf=Path(pdf);prepared=Path(prepared);output=Path(output)
    state=json.loads((prepared/'progress.json').read_bytes());binding=state['binding']
    if binding['doc_id']!='sha256-'+sha(pdf.read_bytes()):raise ValueError('LAYOUT_SOURCE_IDENTITY')
    if binding['reader']!=core_fingerprint():raise ValueError('LAYOUT_READER_IDENTITY')
    raw=Path(reference_input).read_bytes();manifest=json.loads(Path(reference_manifest).read_bytes())
    if sha(raw)!=manifest['structure_hashes']['00_structure_input.json']:raise ValueError('LAYOUT_REFERENCE_HASH')
    reference=json.loads(raw)
    if reference['doc_id']!=binding['doc_id']:raise ValueError('LAYOUT_REFERENCE_SOURCE')
    pages={p['page_index']:p for p in load_page(prepared/'digital.json.gz')['pages']}
    for path in sorted((prepared/'ocr').glob('*.json.gz')):
        p=load_page(path);pages[p['page_index']]=p
    if set(pages)!=set(range(state['total_pages'])):raise ValueError('LAYOUT_PAGE_COVERAGE')
    # The grouping/cache version may differ. Reuse only when every contract,
    # word coordinate, visibility verdict and numeric observation is identical.
    keys=('page_index','page_label','width','height','cropbox','blocks','tables')
    def ocr_observations(page):
        ocr=page.get('ocr')
        if not ocr:return ocr
        # Execution times are not layout/number observations. Enumerate only
        # known timing fields; unknown/new fields remain identity constraints.
        ignored={'layout_seconds','preprocess_seconds','reader1_seconds','reader1_wall_seconds'}
        value={k:v for k,v in ocr.items() if k not in ignored}
        if 'second_reads' in value:
            value['second_reads']={k:v for k,v in value['second_reads'].items() if k!='seconds'}
        return value
    mismatches=[]
    for before in reference['pages']:
        current=pages[before['page_index']]
        if any(current.get(k)!=before.get(k) for k in keys) or ocr_observations(current)!=ocr_observations(before):mismatches.append(before['page_index'])
    if mismatches:raise ValueError('LAYOUT_PAGE_CONTENT_MISMATCH:'+str(mismatches))
    output.mkdir(parents=True,exist_ok=False)
    value=json.loads(Path(sidecar).read_bytes())
    # consume validates source SHA, model/configuration identity and frames.
    observations=json.loads(Path(cell_observations).read_bytes()) if cell_observations else None
    document=write_structure(reference,output,layout_sidecar=value,require_positive_tables=True,cell_observations=observations)
    write(output/'layout-reuse.json',dict(version=1,source_sha256=sha(pdf.read_bytes()),
        reference_sha256=sha(raw),sidecar_sha256=sha(Path(sidecar).read_bytes()),
        cell_observations_sha256=sha(Path(cell_observations).read_bytes()) if cell_observations else None,
        producer_reader=reference['core_fingerprint'],current_reader=binding['reader'],
        matched_pages=sorted(pages),matched_fields=[*keys,'ocr_observations_excluding_execution_times'],policy='exact_observation_reuse',
        citable_table_blocks=[e.block.block_id for e in document.elements if e.citable and e.role=='table'],
        available_tables=sum(t.structure=='available' for t in document.tables),new_ocr_calls=0))
    return output/'document.json'


def attach_source_context(result, documents, coverage=None, revisions=None, snapshots=None):
    """Selected snapshots are known; total PDF coverage needs a pinned receipt."""
    from copy import deepcopy
    from matn_verification.rules import fingerprint
    coverage=coverage or {};revisions=revisions or {};snapshots=snapshots or {}
    result['source_snapshots']={d.doc_id:snapshots.get(d.doc_id) or fingerprint(d) for d in documents}
    result['source_revisions']={d.doc_id:revisions.get(d.doc_id) for d in documents}
    selected={d.doc_id:coverage.get(d.doc_id,dict(complete=None,total_pages=None,
        ready_pages=sorted(p.pdf_page_index+1 for p in d.pages),pending_pages=None,
        excluded_words_by_reason=d.coverage_summary.excluded_words_by_reason,
        status='snapshot_only_total_pdf_coverage_unknown')) for d in documents}
    result['selected_source_coverage']=deepcopy(selected)
    if any(c.get('complete') is False for c in selected.values()) and not result.get('error') and result['state'] not in ('error','deferred_memory'):
        result['message']='Processing is still in progress for selected sources; missing evidence in published pages is not evidence of absence in the PDFs.'
        if not result['sentences']:result['state']='processing'
    return result
