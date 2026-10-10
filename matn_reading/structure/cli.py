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
from .cache import load_snapshot,preflight_ocr,page_record
from .document import from_reading,prepare_snapshot,write_structure,structure_only


def run(pdf,out,worker_factory=None,glm=None):
    pdf=Path(pdf);out=Path(out)
    if hashlib.sha256(pdf.read_bytes()).hexdigest() in legacy.test_split_hashes(): raise legacy.RefusedTestSplit('sealed source')
    started=time.perf_counter();out.mkdir(parents=True,exist_ok=True)
    with block_egress():
        reading=read_document(pdf);pages=list(reading.pages)
        scanned=preflight_ocr([{'doc_id':reading.doc_id,'pages':[page_record(p) for p in pages]}])
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
                    image=render_page_image(pdf,i,config.dpi)
                    layer=[(w.text,(w.x0,w.top,w.x1,w.bottom)) for w in opened.page(i).words] if p.route.value=='scanned_with_ocr_layer' else []
                    pages[i]=read_scan_page(image,page_index=i,page_label=p.page_label,cropbox=p.cropbox,route=p.route,reasons=p.reasons,doc_id=reading.doc_id,worker=worker,glm=reader2,config=config,crop_dir=out,text_layer=layer)
                    processed[i]=preprocess(image,config.preprocess)[0]
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
    args=parser.parse_args(argv)
    try:
        if args.structure_only: structure_only(args.out)
        else: run(args.pdf,args.out)
    except (legacy.RefusedTestSplit,ValueError,FileNotFoundError) as error:
        print(f'REFUSED: {error}',file=sys.stderr);return 3 if isinstance(error,legacy.RefusedTestSplit) else 2
    print(f'Done. Outputs in {args.out.resolve()}');return 0
