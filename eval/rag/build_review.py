"""Build a self-contained offline Firefox owner review; read dev PDFs only for crops."""
import base64
import hashlib
import json
from pathlib import Path
import fitz
from .prepare_drafts import splits_and_sample

ROOT=Path(__file__).resolve().parents[2]


def build_review(rows,out):
    sample=splits_and_sample(rows)
    if len(sample)!=20:raise ValueError('OWNER_SAMPLE_COUNT')
    registry=json.loads((ROOT/'eval/registry.json').read_text())['documents']
    docs={d['doc_id']:d for d in registry if d['split']=='dev'}
    items=[]
    for row in sample:
        doc=docs[row['source']];pdf=ROOT/'eval'/doc['file']
        if hashlib.sha256(pdf.read_bytes()).hexdigest()!=doc['sha256']:raise ValueError('SOURCE_HASH')
        crops=[]
        with fitz.open(pdf) as opened:
            spans=row['target_spans']
            if not spans:
                spans=[{'pdf_page_index':row['gold_page_index'],'bbox':list(opened[row['gold_page_index']].rect)}]
            seen=set()
            for span in spans:
                key=(span['pdf_page_index'],tuple(span['bbox']))
                if key in seen:continue
                seen.add(key);page=opened[span['pdf_page_index']]
                clip=fitz.Rect(span['bbox']);clip=fitz.Rect(clip.x0-8,clip.y0-8,clip.x1+8,clip.y1+8)&page.rect
                data=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),clip=clip,alpha=False).tobytes('png')
                crops.append({'pdf_page_index':span['pdf_page_index'],
                    'image':'data:image/png;base64,'+base64.b64encode(data).decode()})
        items.append({**row,'crops':crops})
    manifest=hashlib.sha256(json.dumps(sample,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    template=Path(__file__).with_name('review_template.html').read_text()
    payload=json.dumps({'schema':'matn-rag-owner-review/1','manifest':manifest,'items':items},ensure_ascii=False).replace('</','<\\/')
    out.write_text(template.replace('REVIEW_DATA_PLACEHOLDER',payload))
    out.with_suffix('.sample.json').write_text(json.dumps({'schema':'matn-rag-owner-sample/1','manifest':manifest,
        'seed':20261012,'provenance':'drafted by model family A','items':sample},indent=2,ensure_ascii=False)+'\n')
    return sample

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('drafts',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
    build_review(json.loads(a.drafts.read_text())['items'],a.out)
