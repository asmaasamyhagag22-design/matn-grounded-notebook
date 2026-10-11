"""Additive entry point; frozen reader CLI bytes and tests remain unchanged."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from checks.egress_guard import block_egress
from matn_reading import cli as legacy
from matn_reading.read import read_document
from .cache import load_snapshot,preflight_ocr,page_record,core_fingerprint,cache_key,save_snapshot
from matn_contracts.structure_ids import canonical
from .document import from_reading,prepare_snapshot,write_structure,structure_only


def run(pdf,out,worker_factory=None,glm=None, *, approval_file=None,compare_digital=None):
    pdf=Path(pdf);out=Path(out)
    if hashlib.sha256(pdf.read_bytes()).hexdigest() in legacy.test_split_hashes(): raise legacy.RefusedTestSplit('sealed source')
    started=time.perf_counter();out.mkdir(parents=True,exist_ok=True)
    with block_egress():
        digital_started=time.perf_counter()
        reading=read_document(pdf);pages=list(reading.pages)
        records=[page_record(p) for p in pages]
        fingerprint=core_fingerprint();key=cache_key(reading.doc_id,fingerprint)
        manifest={'doc_id':reading.doc_id,'reader_fingerprint':fingerprint,'cache_key':key,
                  'digital_wall_seconds':time.perf_counter()-digital_started,'ocr_pages':[]}
        snapshot={'schema_version':1,'doc_id':reading.doc_id,'title':pdf.stem,
                  'core_fingerprint':fingerprint,'cache_key':key,'pages':records,'outline':[]}
        save_snapshot(out/'digital_read.json',snapshot)
        scanned=preflight_ocr([snapshot],approval_file=approval_file)
        if compare_digital is not None:
            baseline=load_snapshot(compare_digital)
            old={p['page_index']:p for p in baseline['pages']}
            new={p['page_index']:p for p in records}
            differing=[i for i in sorted(set(old)|set(new)) if canonical(old.get(i))!=canonical(new.get(i))]
            manifest['digital_comparison']={'method':'canonical per-page page_record JSON; all fields; envelope metadata excluded',
                'baseline':str(compare_digital),'differing_pages':differing,
                'identity_matches':baseline['doc_id']==reading.doc_id,
                'baseline_pages_sha256':hashlib.sha256(canonical(baseline['pages']).encode()).hexdigest(),
                'fresh_pages_sha256':hashlib.sha256(canonical(records).encode()).hexdigest()}
            (out/'acquisition-manifest.json').write_text(canonical(manifest)+'\n')
            if differing or baseline['doc_id']!=reading.doc_id:
                raise ValueError('DIGITAL_MISMATCH:'+canonical(differing))
        (out/'routes-before-ocr.json').write_text(json.dumps(scanned,ensure_ascii=False,indent=2)+'\n')
        processed={}
        if scanned:
            from matn_reading.ocr.route import read_scan_page,OcrConfig
            from matn_reading.ocr.preprocess import render_page_image,preprocess
            from matn_reading.ocr.reader1 import RapidOcrWorker
            from matn_reading.ocr.glm import GlmReader
            from matn_reading.pdf_page import OpenPdf
            config=OcrConfig()
            with (worker_factory or RapidOcrWorker)() as worker,OpenPdf(pdf) as opened:
                reader2=glm or GlmReader()
                for spec in scanned:
                    i=spec['page_index'];p=pages[i]
                    page_started=time.perf_counter();calls={'ocr':0,'second_read':0,'second_read_cached':0,'second_read_cache_keys':[]}
                    worker_read=worker.read;glm_read=reader2.read_line
                    def counted_read(*args,**kwargs):
                        calls['ocr']+=1
                        return worker_read(*args,**kwargs)
                    def counted_second(*args,**kwargs):
                        result=glm_read(*args,**kwargs)
                        calls['second_read']+=int(not result.cached)
                        calls['second_read_cached']+=int(result.cached)
                        calls['second_read_cache_keys'].append(result.key)
                        return result
                    worker.read=counted_read;reader2.read_line=counted_second
                    image=render_page_image(pdf,i,config.dpi)
                    layer=[(w.text,(w.x0,w.top,w.x1,w.bottom)) for w in opened.page(i).words] if p.route.value=='scanned_with_ocr_layer' else []
                    pages[i]=read_scan_page(image,page_index=i,page_label=p.page_label,cropbox=p.cropbox,route=p.route,reasons=p.reasons,doc_id=reading.doc_id,worker=worker,glm=reader2,config=config,crop_dir=out,text_layer=layer)
                    worker.read=worker_read;reader2.read_line=glm_read
                    processed[i]=preprocess(image,config.preprocess)[0]
                    manifest['ocr_pages'].append({'pdf_page_index':i,'wall_seconds':time.perf_counter()-page_started,
                        'cache_key':key,**calls,'second_reads':pages[i].ocr['second_reads']})
                    (out/'acquisition-manifest.json').write_text(canonical(manifest)+'\n')
                    print('OCR_PAGE_DONE',i,canonical(manifest['ocr_pages'][-1]),flush=True)
        from matn_reading.ocr.regions import repeat_furniture
        repeat_furniture(pages)
        document=from_reading(pdf,out,reading,pages)
        (out/'blocks.jsonl').write_text(''.join(b.contract.model_dump_json()+'\n' for p in pages for b in p.blocks))
        legacy.write_reading(pages,pdf.name,out/'reading.md')
        legacy.write_report(pages,pdf.name,time.perf_counter()-started,0.,out/'report.md')
        from matn_reading.overlay import draw_overlay,draw_scan_overlay
        from matn_reading.pdf_page import render_page
        import pypdfium2 as pdfium
        opened=pdfium.PdfDocument(str(pdf));overlays=out/'overlays';overlays.mkdir(exist_ok=True)
        try:
            for p in pages:
                i=p.page_index
                if i in processed: draw_scan_overlay(p,processed[i],300).save(overlays/f'p{i:04d}.png')
                else: draw_overlay(p,render_page(opened[i],1.5),1.5,(p.cropbox[0],p.cropbox[1])).save(overlays/f'p{i:04d}.png')
        finally: opened.close()
    return document


def main(argv=None):
    parser=argparse.ArgumentParser(prog='python -m matn_reading')
    sub=parser.add_subparsers(dest='command',required=True)
    read=sub.add_parser('read');read.add_argument('pdf',type=Path);read.add_argument('--out',type=Path,required=True)
    read.add_argument('--structure-only',action='store_true')
    read.add_argument('--ocr-approval',type=Path)
    read.add_argument('--compare-digital',type=Path)
    args=parser.parse_args(argv)
    try:
        if args.structure_only: structure_only(args.out)
        else: run(args.pdf,args.out,approval_file=args.ocr_approval,compare_digital=args.compare_digital)
    except (legacy.RefusedTestSplit,ValueError,FileNotFoundError) as error:
        print(f'REFUSED: {error}',file=sys.stderr);return 3 if isinstance(error,legacy.RefusedTestSplit) else 2
    print(f'Done. Outputs in {args.out.resolve()}');return 0
