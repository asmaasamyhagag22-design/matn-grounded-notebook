"""P2C-E answer-only cached image provenance inventory; never opens PDFs."""
import hashlib
import json
from pathlib import Path
from PIL import Image

OUT=Path('out/r-lite-3/part2c')


def main():
    sample=json.loads(Path('eval/reading/real/sample-frozen-20261006.json').read_text())
    registry=json.loads(Path('eval/registry.json').read_text());registered={r['doc_id'] for r in registry['documents']};rows=[]
    report_texts={str(p):p.read_text() for p in Path('reports').glob('*.json') if p.name!='r-lite-3-part2c-evidence.json'}
    for key,pages in [('nbs_circular_31_e4_1956',[7,15,32]),('statab_1951_part04',[0,8,45])]:
        snap=json.loads(Path('out/r-lite-2/real',key,'00_reading.json').read_text())
        for index in pages:
            name=f'{key}_p{index:04d}';path=Path('eval/reading/real/review_assets',name+'.png');record=Path('out/reading/step4c-closeout-final-v3/final/real',name+'.json')
            metadata=json.loads(record.read_text());page=next(p for p in snap['pages'] if p['page_index']==index)
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            with Image.open(path) as im:dimensions=list(im.size)
            historical=[p for p,text in report_texts.items() if digest in text]
            overlay=Path('out/reading/step4c-closeout-final-v3/final/real',name+'.png')
            rows.append({'source':key,'pdf_page_index':index,'clean_page_image_path':str(path),'image_exists':True,'image_sha256_observed_now':digest,'historical_full_page_SHA_record_found_in_reports':historical,'render_origin_code':'eval/reading/real/review.py generate / matn_reading.ocr.preprocess.render_page_image;300dpi source cropbox raster','dimensions_px':dimensions,'source_pdf_sha256_previously_recorded':sample['sources'][key],'source_pdf_SHA_record':'eval/reading/real/sample-frozen-20261006.json $.sources','cropbox_pt':metadata['cropbox'],'page_dimensions_pt':[page['width'],page['height']],'OCR_preprocess_metadata':metadata['preprocess'],'metadata_path':str(record),'metadata_sha256':hashlib.sha256(record.read_bytes()).hexdigest(),'overlay_path':str(overlay),'overlay_exists':overlay.exists(),'overlay_is_not_clean_labeler_input':True,'dev_registry_registered':key in registered})
    result={'status':'ANSWER_ONLY_NO_LABELER_OR_PDF_ACCESS','pages':rows,'cached_clean_pages':len(rows),'prior_full_page_image_SHA_record_confirmed':sum(bool(r['historical_full_page_SHA_record_found_in_reports']) for r in rows),'interpretation':'Six clean full-page PNGs exist; their byte hashes are first recorded by this inventory. Prior records pin source PDF SHA and token/context crop SHA, not these complete page-image bytes in the searched report manifests. A present file and a new hash do not retroactively prove source provenance.','required_before_labeler':['owner named approval to register the six cached images as dev-only input with exact image/source hashes and page indices','establish original render cropbox/DPI/dimensions and frame, independently validate cached-image provenance to source SHA without assuming newly observed hashes are historical','pin the clean unannotated image bytes; do not use OCR boxes/overlays as labeler input','approve an image-input adapter: the committed Docling configuration uses a PDF converter, so cached PNG input cannot be silently substituted','carry exact image-to-page mapping and any deskew/denoise transform for label projection; preserve source reading statuses'],'inference_calls':0,'real6_PDF_opened':False}
    (OUT/'real6-image-provenance.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n');print('P2C-E: six clean PNGs exist; prior fullpage SHA records confirmed',result['prior_full_page_image_SHA_record_confirmed'],'new hashes recorded; no PDFs or labeler opened')


if __name__=='__main__':main()
