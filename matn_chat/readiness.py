"""Restartable local PDF preparation, immutable published indexes and explicit coverage.

Extraction checkpoints retain source words, never infer text from previous chat.
Only the atomic ready.json pointer is mutable; readers pin a complete revision.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import asdict
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import time

from matn_reading.structure.cache import core_fingerprint, cache_key, page_record
from matn_rag.contracts import canonical

VERSION = 'pdf-chat-readiness-v2'
GLM_DIGEST = '12c54d1b823a9a151957273c8b7a5e57fcaa23a640981f25822cda4b3a1d5edb'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix+'.pending')
    tmp.write_bytes(canonical(value)+b'\n')
    tmp.replace(path)


@contextmanager
def lock(path):
    # A process crash releases flock; no stale lock deletion or second writer.
    import fcntl
    with Path(path).open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('PREPARATION_ALREADY_RUNNING') from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def binding(pdf):
    from matn_rag.embedding import DIGEST
    root = Path(__file__).resolve().parents[1]
    files = [*sorted((root/'matn_reading/structure').glob('*.py')),
             root/'matn_rag/ingest.py', root/'matn_rag/tokenizer.py']
    return dict(version=VERSION, doc_id='sha256-'+sha(Path(pdf).read_bytes()),
                reader=core_fingerprint(), pipeline=sha(canonical({str(p.relative_to(root)):sha(p.read_bytes()) for p in files})),
                embedding=DIGEST, ocr_glm_digest=GLM_DIGEST,
                variant='doc-input-no-prefix-v1', table_policy='exclude_unclassified_tables',
                checkpoint_schema='page-record-v1', orchestration='per-page-ocr-batch-v1')


def save_page(path, value):
    raw=canonical(value)
    envelope=canonical(dict(sha256=sha(raw), value=value))
    tmp=path.with_suffix('.pending')
    tmp.write_bytes(gzip.compress(envelope, mtime=0));tmp.replace(path)


def load_page(path):
    envelope=json.loads(gzip.decompress(path.read_bytes()))
    if sha(canonical(envelope['value'])) != envelope['sha256']:
        raise ValueError('PAGE_CHECKPOINT_HASH')
    return envelope['value']


def data_record(data):
    # Grouping needs these fields only; discard glyph/render buffers immediately.
    return {k:([asdict(w) for w in data.words] if k=='words' else asdict(data.signals) if k=='signals' else getattr(data,k))
            for k in ('page_index','width','height','cropbox','page_label','words','images','drawings','tables','signals','edge_cases','filled_boxes')}


def page_data(value):
    from matn_reading.pdf_page import PageData
    from matn_reading.layout import Word
    from matn_reading.triage import PageSignals
    return PageData(**{**value,'words':[Word(**w) for w in value['words']],
                      'signals':PageSignals(**value['signals'])}, chars=[], text_objects=[], paint_objects=[], plumber_text='', pdfium_text='')


def replay_page(value):
    from matn_reading.read import PageReading, ReadBlock
    from matn_reading.layout import LayoutBlock, Line, Word
    from matn_contracts.domain import Block
    from matn_reading.triage import Route
    blocks=[]
    for r in value['blocks']:
        b=Block.model_validate(r['block'])
        lines=[Line([Word(w['text'],*w['bbox'],**{k:v for k,v in w.items() if k not in ('text','bbox')}) for w in l['words']]) for l in r['lines']]
        blocks.append(ReadBlock(LayoutBlock(lines).finish(),b.block_type.value,r['flagged'],b.bbox,b))
    return PageReading(value['page_index'],value['page_label'],value['width'],value['height'],tuple(value['cropbox']),
                       Route(value['route']),value['reasons'],blocks,value['flags'],value.get('figure_regions',[]),value['tables'],{}, {},ocr=value['ocr'])


def publish(root, state, records, *, embedder=None):
    """Reassemble global context; publish only when document AND index are consistent."""
    from matn_reading.structure.document import assemble
    from matn_rag.sqlite import SQLiteRepository
    from matn_rag.ingest import prepare
    from matn_rag.embedding import DIGEST
    from matn_contracts.structure_ids import canonical as structure_canonical
    if not records:
        return
    ready_path=root/'ready.json'
    if ready_path.exists():
        previous=load_ready(ready_path)
        available={p['page_index']+1 for p in records}
        if not set(previous['coverage']['ready_pages']) <= available:
            return  # Resuming must never roll back an already published page.
    snap=dict(schema_version=1,doc_id=state['binding']['doc_id'],title=state['title'],
              core_fingerprint=state['binding']['reader'],cache_key=cache_key(state['binding']['doc_id'],state['binding']['reader']),
              pages=records,outline=[],unclassified_table_policy=True)
    # No chart-as-table promotion without a source-bound layout observation.
    document=assemble(snap)
    docbytes=(structure_canonical(document.model_dump(mode='json'))+'\n').encode()
    coverage=dict(total_pages=state['total_pages'], ready_pages=sorted(p['page_index']+1 for p in records),
                  pending_pages=sorted(set(range(1,state['total_pages']+1))-{p['page_index']+1 for p in records}),
                  errors=state['errors'], complete=len(records)==state['total_pages'] and not state['errors'],
                  table_policy='Unclassified table blocks excluded; no chart numbers inferred.',
                  excluded_words_by_reason=document.coverage_summary.excluded_words_by_reason,
                  ocr_second_read_failures={str(p['page_index']+1):sum(f.get('reason')=='second_read_failed' for f in p['flags'])
                                            for p in records if any(f.get('reason')=='second_read_failed' for f in p['flags'])},
                  index_mode='hybrid-no-prefix' if embedder else 'bm25')
    revision=sha(docbytes+canonical(coverage))
    folder=root/'revisions'/revision;folder.mkdir(parents=True,exist_ok=True)
    dbpath=folder/'notebook.db'
    if (folder/'receipt.json').exists():
        receipt=load_ready(folder/'receipt.json')
        write(ready_path,receipt);state['published_revision']=revision
        return
    # A crash may leave an unpublished DB. Idempotent add_source + embedding cache resume it.
    repo=SQLiteRepository(dbpath)
    try:
        metadata, chunks=prepare(document)
        repo.create_notebook('readiness');sid=repo.add_source('readiness',document.doc_id,metadata,chunks)
        if embedder:
            embedder.check_digest()
            cache=SQLiteRepository(root/'embedding-cache.db')
            try:
                pairs=sorted((c['chunk_id'],c['text']) for c in chunks)
                missing=[(cid,text) for cid,text in pairs if cache.get_embedding(DIGEST,'doc-input-no-prefix-v1',text) is None]
                state['embedding']=dict(total=len(pairs),reused=len(pairs)-len(missing),remaining=len(missing))
                write(root/'progress.json',state)
                for offset in range(0,len(missing),8):
                    batch=missing[offset:offset+8];tick=time.monotonic()
                    vectors=embedder.embed([text for _,text in batch])
                    for (_,text),v in zip(batch,vectors,strict=True):
                        cache.put_embedding(DIGEST,'doc-input-no-prefix-v1',text,v)
                    state['embedding']['remaining']=len(missing)-offset-len(batch)
                    write(root/'progress.json',state)
                    event(root, 'embedding_batch', seconds=time.monotonic()-tick, completed=offset+len(batch), remaining=len(missing)-offset-len(batch))
                for cid,text in pairs:
                    vector=cache.get_embedding(DIGEST,'doc-input-no-prefix-v1',text)
                    repo.put_embedding(DIGEST,'doc-input-no-prefix-v1',text,vector)
                    repo.link_embedding(sid,cid,'doc-input-no-prefix-v1',DIGEST,'doc-input-no-prefix-v1',text)
            finally:
                cache.db.close()
        integrity=repo.integrity()
        if integrity['foreign_key_errors'] or integrity['orphan_embeddings']:
            raise ValueError('PUBLISHED_INDEX_INTEGRITY')
    finally:
        repo.db.close()
    (folder/'document.json').write_bytes(docbytes)
    write(folder/'notebook.db.structures.json',dict(version=1,documents={document.doc_id:'document.json'}))
    receipt=dict(schema_version=1,revision=revision,binding=state['binding'],coverage=coverage,
                 notebook=str(dbpath.resolve()),document_sha256=sha(docbytes),index_sha256=sha(dbpath.read_bytes()),integrity=integrity)
    write(folder/'receipt.json',receipt)
    write(root/'ready.json',receipt)
    state['published_revision']=revision
    event(root,'published',revision=revision,coverage=coverage,integrity=integrity)


def event(root, stage, **fields):
    row=dict(time=time.time(),stage=stage,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**fields)
    with (root/'events.jsonl').open('a') as f:
        f.write(json.dumps(row,sort_keys=True)+'\n');f.flush()
    print(json.dumps(row,ensure_ascii=False),flush=True)


def prepare_pdf(pdf, out, *, stop_after=None, publish_every=32, embedder=None, lexical_only=False):
    from checks.egress_guard import block_egress
    if publish_every < 1 or stop_after is not None and stop_after < 1:
        raise ValueError('POSITIVE_PAGE_COUNTS_REQUIRED')
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    with lock(root/'prepare.lock'), block_egress():
        return _prepare(Path(pdf),root,stop_after,publish_every,embedder,lexical_only)


def _prepare(pdf,root,stop_after,publish_every,embedder,lexical_only=False):
    from matn_reading.cli import test_split_hashes
    from matn_reading.pdf_page import OpenPdf
    from matn_reading.read import reading_from_pages
    from matn_reading.structure.cache import OCR_ROUTES
    from matn_rag.embedding import Embedder
    started=time.monotonic();identity=binding(pdf)
    if lexical_only:
        if embedder is not None:
            raise ValueError('LEXICAL_PREPARATION_CANNOT_EMBED')
        identity={**identity, 'embedding':None, 'variant':'app-bm25-v1'}
    if identity['doc_id'].removeprefix('sha256-') in test_split_hashes():
        raise ValueError('SEALED_TEST_SPLIT_REFUSED')
    statepath=root/'progress.json'
    if statepath.exists():
        state=json.loads(statepath.read_bytes())
        if state['binding']!=identity:
            raise ValueError('PROCESSING_BINDING_MISMATCH_USE_NEW_OUTPUT')
    else:
        with OpenPdf(pdf) as opened: total=len(opened)
        state=dict(schema_version=1,binding=identity,title=pdf.stem,total_pages=total,extracted_pages=[],ocr_pages=[],errors={},status='processing',started_at=time.time())
    write(statepath,state)
    (root/'pages').mkdir(exist_ok=True);(root/'ocr').mkdir(exist_ok=True)
    event(root,'start',binding=identity,previous_status=state['status'])
    if state['status']=='complete':
        # Warm path validates bytes, never merely trusts a completion bit.
        receipt=load_ready(root/'ready.json')
        event(root,'warm_reuse',seconds=time.monotonic()-started,revision=receipt['revision'])
        return state
    extracted={};ocr={};new=0
    try:
        with OpenPdf(pdf) as opened:
            for i in range(state['total_pages']):
                target=root/'pages'/f'{i:04d}.json.gz'
                if target.exists():
                    value=load_page(target)
                else:
                    tick=time.monotonic()
                    try:
                        data=opened.page(i);value=data_record(data);timings=data.timings
                        del data
                        save_page(target,value)
                        event(root,'page_extracted',page=i+1,seconds=time.monotonic()-tick,**timings)
                        new+=1
                    except Exception as exc:
                        state['errors'][str(i+1)]='extraction: '+repr(exc);write(statepath,state)
                        event(root,'page_error',page=i+1,error=repr(exc));continue
                if value['page_index']!=i:
                    raise ValueError('CHECKPOINT_PAGE_ID')
                extracted[i]=value
                state['errors'].pop(str(i+1),None)
                state['extracted_pages']=sorted(j+1 for j in extracted)
                write(statepath,state)
                if new and (i+1 in (8,) or (i+1)%publish_every==0 or stop_after and new>=stop_after):
                    reading=reading_from_pages(pdf,identity['doc_id'],[page_data(v) for v in extracted.values()])
                    records=[page_record(p) for p in reading.pages if p.route.value not in OCR_ROUTES]
                    publish(root,state,records)
                    del reading
                    if stop_after and new>=stop_after:
                        state['status']='paused';write(statepath,state)
                        event(root,'intentional_stop',seconds=time.monotonic()-started,new_pages=new)
                        return state
        event(root,'digital_complete',seconds=time.monotonic()-started,pages=len(extracted))
        reading=reading_from_pages(pdf,identity['doc_id'],[page_data(v) for v in extracted.values()])
        save_page(root/'digital.json.gz',{'pages':[page_record(p) for p in reading.pages]})
        state['ocr_required_pages']=[p.page_index+1 for p in reading.pages if p.route.value in OCR_ROUTES]
        write(statepath,state)
        from matn_reading.ocr.route import OcrConfig, read_scan_page
        from matn_reading.ocr.preprocess import render_page_image
        from matn_reading.ocr.reader1 import RapidOcrWorker
        from matn_reading.ocr.glm import GlmReader, GlmConfig
        with ExitStack() as stack:
            worker=None
            for offset,p in enumerate(reading.pages):
                if p.route.value not in OCR_ROUTES: continue
                target=root/'ocr'/f'{p.page_index:04d}.json.gz';tick=time.monotonic()
                try:
                    cached=target.exists()
                    if cached:
                        record=load_page(target);replacement=replay_page(record)
                    else:
                        if worker is None:
                            from matn_rag.transport import LoopbackTransport
                            models=LoopbackTransport().request('/api/tags')['models']
                            if not any(m['name']=='glm-ocr:bf16' and m['digest']==GLM_DIGEST for m in models):
                                raise ValueError('OCR_GLM_DIGEST_MISMATCH')
                        words=extracted[p.page_index]['words']
                        from contextlib import nullcontext
                        from matn_app.model_gate import lease
                        gated=bool(os.environ.get('MATN_MODEL_GATE'))
                        with lease() if gated else nullcontext():
                            # Release the OCR sidecar before handing RAM to an
                            # answer; a crash also releases the process lease.
                            glm=GlmReader(GlmConfig(cache_dir=root/'glm-cache'))
                            try:
                                with RapidOcrWorker() if gated else nullcontext(worker or stack.enter_context(RapidOcrWorker())) as page_worker:
                                    if not gated:
                                        worker=page_worker
                                    replacement=read_scan_page(render_page_image(pdf,p.page_index,300),page_index=p.page_index,
                                        page_label=p.page_label,cropbox=p.cropbox,route=p.route,reasons=p.reasons,doc_id=identity['doc_id'],
                                        worker=page_worker,glm=glm,config=OcrConfig(),crop_dir=root,
                                        text_layer=[(w['text'],(w['x0'],w['top'],w['x1'],w['bottom'])) for w in words] if p.route.value=='scanned_with_ocr_layer' else [])
                            finally:
                                if gated:glm.close()
                        if any(f['kind'] in ('ocr_no_text','ocr_unavailable','second_read_failed') for f in replacement.flags):
                            raise ValueError('OCR_INCOMPLETE_SEE_FLAGS')
                        save_page(target,page_record(replacement))
                    reading.pages[offset]=replacement;ocr[p.page_index]=True
                    state['ocr_pages']=sorted(j+1 for j in ocr);state['errors'].pop(str(p.page_index+1),None)
                    event(root,'ocr_page',page=p.page_index+1,seconds=time.monotonic()-tick,cached=cached)
                except Exception as exc:
                    state['errors'][str(p.page_index+1)]='ocr: '+repr(exc)
                    event(root,'page_error',page=p.page_index+1,error=repr(exc))
                write(statepath,state)
        from matn_reading.ocr.regions import repeat_furniture
        repeat_furniture(reading.pages)
        records=[page_record(p) for p in reading.pages if p.route.value not in OCR_ROUTES or p.page_index in ocr]
        event(root,'reading_complete',pages=len(records),errors=state['errors'],seconds=time.monotonic()-started)
        publish(root,state,records)
        if not lexical_only:
            publish(root,state,records,embedder=embedder or Embedder())
        state['status']='complete' if len(records)==state['total_pages'] and not state['errors'] else 'incomplete'
        write(statepath,state)
        event(root,'finished',status=state['status'],seconds=time.monotonic()-started)
        return state
    except BaseException as exc:
        state['status']='interrupted';state['last_error']=repr(exc);write(statepath,state)
        event(root,'interrupted',error=repr(exc),seconds=time.monotonic()-started)
        raise


def load_ready(path):
    receipt=json.loads(Path(path).read_bytes());db=Path(receipt['notebook'])
    if sha(db.read_bytes())!=receipt['index_sha256'] or sha((db.parent/'document.json').read_bytes())!=receipt['document_sha256']:
        raise ValueError('PUBLISHED_REVISION_HASH')
    return receipt


def attach_coverage(result,receipt):
    result['source_revision']=receipt['revision'];result['source_coverage']=receipt['coverage']
    if not receipt['coverage']['complete'] and result.get('state') not in ('error','deferred_memory') and not result.get('error'):
        result['message']='Processing is still in progress. Answers cover only the ready pages; missing evidence is not evidence of absence in the PDF.'
        if not result.get('sentences'):
            result['state']='processing'
    return result
