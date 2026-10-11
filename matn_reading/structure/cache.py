"""Immutable full reader snapshots and bounded one-time dev acquisition.

No reader rule changes. Frozen input inventory excludes new structure/orchestration.
Replay loaders never construct an OCR worker or model client.
"""
import hashlib
import json
import time
from pathlib import Path
from dataclasses import asdict
from matn_contracts.structure_ids import canonical

REPO=Path(__file__).resolve().parents[1]
# Explicit core modules, excluding CLI/overlays and the additive structure package.
CORE_FILES=('read.py','pdf_page.py','layout.py','classify.py','triage.py',
 'ocr/route.py','ocr/regions.py','ocr/numbers.py','ocr/consensus.py','ocr/consistency.py',
 'ocr/preprocess.py','ocr/reader1.py','ocr/worker.py','ocr/glm.py',
 'ocr/ocr_rules.json','ocr/closeout_rules.json','ocr/rapidocr_settings.json')
OCR_ROUTES={'scanned','scanned_with_ocr_layer','digital_broken','mixed'}


def core_fingerprint():
    from matn_reading.pdf_page import EXTRACTOR_VERSION
    inputs={p:hashlib.sha256((REPO/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in CORE_FILES}
    inputs['thresholds']=hashlib.sha256((REPO.parent/'eval/reading/thresholds.json').read_bytes()).hexdigest()
    inputs['libraries']=EXTRACTOR_VERSION
    return hashlib.sha256(canonical(inputs).encode()).hexdigest()


def cache_key(doc_id,fingerprint):
    return hashlib.sha256(canonical([doc_id,fingerprint,{'ocr':'frozen-default-all','dpi':300}]).encode()).hexdigest()


def save_snapshot(path,snapshot):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    content=canonical(snapshot)+'\n'
    if path.exists() and path.read_text()!=content: raise ValueError('CACHE_IMMUTABLE')
    tmp=path.with_suffix('.pending');tmp.write_text(content);tmp.replace(path)
    path.with_suffix('.sha256').write_text(hashlib.sha256(content.encode()).hexdigest()+'\n')


def load_snapshot(path):
    path=Path(path);data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=path.with_suffix('.sha256').read_text().strip(): raise ValueError('CACHE_HASH')
    value=json.loads(data)
    if value.get('schema_version')!=1 or not value.get('pages'): raise ValueError('CACHE_SCHEMA')
    return value


def preflight_ocr(snapshots, *, approval_file=None):
    pages=[{'doc_id':s.get('doc_id'),'page_index':p['page_index'],'route':p['route'],'reasons':p['reasons']}
           for s in snapshots for p in s['pages'] if p['route'] in OCR_ROUTES]
    if approval_file is not None:
        approval=json.loads(Path(approval_file).read_text(encoding='utf-8'))
        identity='sha256-'+approval['sha256']
        if len(snapshots)!=1 or snapshots[0].get('doc_id')!=identity:
            raise ValueError('OCR_APPROVAL_SHA')
        approved=approval['pdf_page_indices']
        routed=[p['page_index'] for p in pages]
        if len(approved)!=len(set(approved)) or len(routed)!=len(set(routed)) or set(routed)!=set(approved):
            raise ValueError('OCR_APPROVAL_SET')
    elif len(pages)>10: raise ValueError('OCR_CAP:'+canonical(pages))
    return pages


def page_record(page):
    blocks=[]
    for b in page.blocks:
        blocks.append({'block':b.contract.model_dump(mode='json'),'flagged':b.flagged,
          'lines':[{'words':[{'text':w.text,'bbox':[w.x0,w.top,w.x1,w.bottom],'size':w.size,'bold':w.bold,
                 'vertical':w.vertical,'visibility':w.visibility,'visibility_reasons':list(w.visibility_reasons),
                 'font_face':w.font_face,'text_object_id':w.text_object_id} for w in line.words]} for line in b.layout.lines]})
    return {'page_index':page.page_index,'page_label':page.page_label,'width':page.width,'height':page.height,
       'cropbox':list(page.cropbox),'route':page.route.value,'reasons':page.reasons,'blocks':blocks,
       'flags':page.flags,'tables':page.tables,'figure_regions':page.figure_regions,'ocr':page.ocr}


def acquire_dev(folder, *, reuse_ocr_from=None):
    """Read each dev PDF once; checkpoint digital results before global OCR preflight."""
    from checks.egress_guard import block_egress
    from matn_reading.read import read_document
    root=REPO.parent;folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    registry=json.loads((root/'eval/registry.json').read_text())
    docs=[d for d in registry['documents'] if d.get('split')=='dev']
    if sorted(d['doc_id'] for d in docs)!=['2601-14525v1','gao-21-519sp','wb-eem-2021-12']: raise ValueError('DEV_SET_CHANGED')
    snapshots=[];paths=[]
    with block_egress():
        for doc in docs:
            pdf=root/'eval'/doc['file'];raw=pdf.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=doc['sha256']: raise ValueError('SOURCE_HASH')
            identity='sha256-'+doc['sha256'];fingerprint=core_fingerprint();key=cache_key(identity,fingerprint)
            target=folder/doc['doc_id']/'00_reading.json';paths.append(target)
            if target.exists():
                s=load_snapshot(target)
                if s['cache_key']!=key: raise ValueError('CACHE_CORE_CHANGED')
            else:
                checkpoint=target.with_name('digital_read.json')
                if checkpoint.exists():
                    s=load_snapshot(checkpoint)
                    if s['cache_key']!=key: raise ValueError('CACHE_CORE_CHANGED')
                else:
                    started=time.perf_counter();reading=read_document(pdf)
                    s={'schema_version':1,'doc_id':identity,'dev_key':doc['doc_id'],'title':doc['doc_id'],
                       'core_fingerprint':fingerprint,'core_files':list(CORE_FILES),'cache_key':key,
                       'pages':[page_record(p) for p in reading.pages],'outline':[]}
                    save_snapshot(checkpoint,s)
                    checkpoint.with_name('acquisition.json').write_text(canonical({'digital_wall_seconds':time.perf_counter()-started,'pages':len(s['pages']),'cache_key':key})+'\n')
            snapshots.append(s)
            print('DIGITAL_CACHED',doc['doc_id'],len(s['pages']),flush=True)
        route_log=[{'doc_id':s['doc_id'],'dev_key':s['dev_key'],'pages':[{'page_index':p['page_index'],'route':p['route'],'reasons':p['reasons']} for p in s['pages']]} for s in snapshots]
        (folder/'routes-before-ocr.json').write_text(canonical(route_log)+'\n')
        pending=preflight_ocr(snapshots)
        print('OCR_PREFLIGHT',canonical(pending),flush=True)
        if reuse_ocr_from is not None:
            for s in snapshots:
                old=load_snapshot(Path(reuse_ocr_from)/s['dev_key']/'00_reading.json')
                if old['doc_id']!=s['doc_id']: raise ValueError('OCR_REPLAY_SOURCE')
                previous={p['page_index']:p for p in old['pages']}
                replay=[]
                for i,p in enumerate(s['pages']):
                    before=previous[p['page_index']]
                    if before.get('ocr'):
                        if p['cropbox']!=before['cropbox']:raise ValueError('OCR_REPLAY_FRAME')
                        s['pages'][i]=before;replay.append(p['page_index'])
                    elif p['route'] in OCR_ROUTES:raise ValueError('OCR_CACHE_MISS:'+s['dev_key']+':'+str(i))
                s['ocr_replay']={'source_cache_key':old['cache_key'],'page_indices':replay}
        from matn_reading.ocr.route import read_scan_page,OcrConfig
        from matn_reading.ocr.preprocess import render_page_image
        from matn_reading.ocr.reader1 import RapidOcrWorker
        from matn_reading.ocr.glm import GlmReader
        config=OcrConfig()
        # Complete existing target means no inference. Per-page checkpoints prevent repeats.
        need=reuse_ocr_from is None and any(not target.exists() and any(p['route'] in OCR_ROUTES for p in s['pages']) for s,target in zip(snapshots,paths))
        if need:
            with RapidOcrWorker() as worker:
                glm=GlmReader()
                for doc,s,target in zip(docs,snapshots,paths):
                    if target.exists(): continue
                    pdf=root/'eval'/doc['file'];started=time.perf_counter()
                    for i,p in enumerate(s['pages']):
                        if p['route'] not in OCR_ROUTES: continue
                        cp=target.with_name(f'ocr_p{i:04d}.json')
                        if cp.exists(): s['pages'][i]=load_snapshot(cp)['pages'][0];continue
                        from matn_reading.triage import Route
                        image=render_page_image(pdf,p['page_index'],config.dpi)
                        layer=[(w['text'],w['bbox']) for b in p['blocks'] for l in b['lines'] for w in l['words']]
                        page=read_scan_page(image,page_index=p['page_index'],page_label=p['page_label'],cropbox=p['cropbox'],
                            route=Route(p['route']),reasons=p['reasons'],doc_id=s['doc_id'],worker=worker,glm=glm,config=config,
                            crop_dir=target.parent,text_layer=layer if p['route']=='scanned_with_ocr_layer' else [])
                        rec=page_record(page);save_snapshot(cp,{**s,'pages':[rec]});s['pages'][i]=rec
                        print('OCR_CACHED',s['dev_key'],i,flush=True)
                    target.with_name('ocr-acquisition.json').write_text(canonical({'wall_seconds':time.perf_counter()-started})+'\n')
        for s,target in zip(snapshots,paths):
            if not target.exists(): save_snapshot(target,s)
    return paths

if __name__=='__main__':
    import sys
    acquire_dev(Path(sys.argv[1]))
