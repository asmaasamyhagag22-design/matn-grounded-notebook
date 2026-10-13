"""Report-only WEF structure inventory and seeded native crop evidence."""
from collections import Counter
import json
from pathlib import Path
import random
import re
import fitz
from PIL import Image,ImageDraw
from matn_contracts.structure import DocumentStructure
from eval.reading.r_lite import metrics

ROOT=Path('out/rag-core/wef-quality');PROFILE=tuple(range(64,76))+tuple(range(83,89))


def run():
    d=DocumentStructure.model_validate_json(Path('out/rag-core/section-rebuild/wef-future-of-jobs-2025/05_document.json').read_bytes())
    by={e.block.block_id:e for e in d.elements};ROOT.mkdir(parents=True,exist_ok=True)
    page_rows=[]
    for p in d.pages:
        secs=[s for s in d.sections if s.page_range[0]<=p.pdf_page_index<=s.page_range[1]]
        headings=[s for s in d.sections if s.heading_block_id and by[s.heading_block_id].block.page_index==p.pdf_page_index]
        page_rows.append({'pdf_page_index':p.pdf_page_index,'ocr_sourced':p.route in ('mixed','scanned'),'section_extents':len(secs),'sections_with_owned_blocks':sum(any(by[b].block.page_index==p.pdf_page_index for b in s.block_ids) for s in secs),'headings': [{'section_id':s.section_id,'source':s.source,'heading_block_id':s.heading_block_id,'text':s.title} for s in headings]})
    selected=random.Random(20261012).sample(sorted((c for c in d.chunks if c.kind=='table'),key=lambda c:c.chunk_id),20)
    samples=[]
    with fitz.open('eval/incoming/wef_future_of_jobs_2025.pdf') as pdf:
        for i,c in enumerate(selected):
            pages=sorted({by[s.block_id].block.page_index for s in c.primary});crops=[]
            for p in pages:
                bs=[fitz.Rect(by[s.block_id].block.bbox) for s in c.primary if by[s.block_id].block.page_index==p];box=bs[0]
                for b in bs[1:]:box|=b
                box=fitz.Rect(box.x0-8,box.y0-8,box.x1+8,box.y1+8)&pdf[p].rect
                path=ROOT/f'table-{i:02}-p{p:04}.png';pdf[p].get_pixmap(matrix=fitz.Matrix(1.5,1.5),clip=box).save(path);crops.append(str(path))
            samples.append({'sample_index':i,'chunk_id':c.chunk_id,'pages':pages,'text':c.text,'crops':crops,'classification':'pending model family A visual judgment'})
        for p in PROFILE:
            pdf[p].get_pixmap(matrix=fitz.Matrix(1.5,1.5)).save(ROOT/f'profile-p{p:04}.png')
    for batch in range(4):
        sheet=Image.new('RGB',(1100,1200),'white');draw=ImageDraw.Draw(sheet)
        for j,s in enumerate(samples[batch*5:batch*5+5]):
            im=Image.open(s['crops'][0]).convert('RGB');im.thumbnail((1050,210));sheet.paste(im,(5,j*240+25));draw.text((5,j*240+3),f"sample{s['sample_index']:02} pages{s['pages']} {s['chunk_id'][-16:]}",fill='black')
        sheet.save(ROOT/f'table-sheet-{batch}.png')
    continuation=[]
    for p in PROFILE:
        es=[e for e in d.elements if e.citable and e.block.page_index==p]
        cs=[c for c in d.chunks if any(by[s.block_id].block.page_index==p for s in c.primary)]
        continuation.append({'pdf_page_index':p,'ocr_sourced':d.pages[p].route in ('mixed','scanned'),'crop':str(ROOT/f'profile-p{p:04}.png'),'blocks':[{'block_id':e.block.block_id,'role':e.role,'bbox':list(e.block.bbox),'text':e.block.text} for e in es],'chunks':[{'chunk_id':c.chunk_id,'kind':c.kind,'pages':sorted({by[s.block_id].block.page_index for s in c.primary}),'text':c.text} for c in cs]})
    summary={'metrics':metrics(d),'dev_body_distributions':{k:json.load(open('out/rag-core/section-rebuild/gates.json'))[k]['metrics']['body_words'] for k in ('2601-14525v1','gao-21-519sp','wb-eem-2021-12')},'citable_primary_words_by_chunk_kind':dict(Counter({kind:sum(len(by[s.block_id].block.text[s.start:s.end].split()) for c in d.chunks if c.kind==kind for s in c.primary) for kind in {c.kind for c in d.chunks}})),'letter_spaced_token_occurrences':[{'block_id':e.block.block_id,'pdf_page_index':e.block.page_index,'text':m.group()} for e in d.elements for m in re.finditer(r'(?<!\w)(?:[A-Z] ){2,}[A-Z](?!\w)',e.block.text)],'pages':page_rows,'table_sample':samples,'profile_continuation':continuation,'provenance':'structure counts from code; classifications pending model family A visual judgment; no reading fixes'}
    annotations=Path('eval/rag/wef-table-visual-annotations.json')
    if annotations.exists():
        labels={r['chunk_id']:r for r in json.loads(annotations.read_text())['items']}
        for sample in samples:
            label=labels[sample['chunk_id']]
            sample.update({k:label[k] for k in ('classification','provenance','reason')})
    (ROOT/'diagnosis.json').write_text(json.dumps(summary,indent=2)+'\n')
    for r in continuation:
        if r['pdf_page_index'] in (70,84,85):
            print('PAGE',r['pdf_page_index'],'ocr',r['ocr_sourced'])
            for b in r['blocks']:print(b['role'],b['block_id'][-16:],b['text'][:500])
    return summary

if __name__=='__main__':run()
