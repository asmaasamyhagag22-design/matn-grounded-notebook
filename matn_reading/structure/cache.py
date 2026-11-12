"""Immutable reader snapshots and bounded OCR preflight.

Replay loaders never construct an OCR worker or model client.
"""
import hashlib
import json
from pathlib import Path
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
