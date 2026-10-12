"""P2C-A2: add neutral 72pt context without a redraw or owner CSV write."""
import csv
import hashlib
import json
from pathlib import Path

ROOT=Path('out/r-lite-3/part2c')


def main():
    csv_path=Path('eval/rag/owner-audit-20261013.csv');csv_before=csv_path.read_bytes()
    rows=list(csv.DictReader(csv_path.open()));assert len(rows)==50 and all(not r['label'] and not r['note'] for r in rows),'OWNER_LABELS_EXIST_STOP'
    mapping_raw=(ROOT/'audit-private-mapping.json').read_bytes();entries=json.loads(mapping_raw)
    assert len(entries)==50 and [e['item'] for e in entries]==list(range(1,51))
    cfg=json.loads(Path('eval/rag/r_lite_3_part2c_sampling.json').read_text())
    assert hashlib.sha256(Path(cfg['pdf']).read_bytes()).hexdigest()==cfg['sha256'],'PDF_SHA_MISMATCH'
    exact=json.loads((ROOT/'audit-crops-manifest.json').read_text());by={r['item']:r for r in exact}
    import pypdfium2 as pdfium
    from PIL import ImageDraw
    records=[];html='<!doctype html><html lang="en"><meta charset="utf-8"><title>Owner audit</title>'
    html+='<style>body{max-width:1100px;margin:24px auto;font:16px sans-serif}article{margin:32px 0;break-inside:avoid}img{max-width:100%;border:1px solid #aaa;display:block;margin:10px 0}</style>'
    with pdfium.PdfDocument(cfg['pdf']) as pdf:
        for entry in entries:
            r=by[entry['item']];assert hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256'],'EXACT_CROP_CHANGED'
            page=pdf[r['pdf_page_index']];bitmap=page.render(scale=1.5);im=bitmap.to_pil().convert('RGB');x0,y0,x1,y1=r['bbox'];width,height=page.get_size()
            context=[max(0,x0-72),max(0,y0-72),min(width,x1+72),min(height,y1+72)]
            pixel=(int(context[0]*1.5),int(context[1]*1.5),min(im.width,int(context[2]*1.5+1)),min(im.height,int(context[3]*1.5+1)))
            crop=im.crop(pixel);draw=ImageDraw.Draw(crop)
            outline=[round(x0*1.5)-pixel[0],round(y0*1.5)-pixel[1],round(x1*1.5)-pixel[0],round(y1*1.5)-pixel[1]]
            draw.rectangle(outline,outline='#666666',width=2)
            path=ROOT/'audit'/f"item-{entry['item']:02d}-context.png";crop.save(path)
            crop.close();im.close();bitmap.close();page.close()
            records.append({'item':entry['item'],'pdf_page_index':r['pdf_page_index'],'block_bbox':r['bbox'],'context_bbox':context,'padding_pt':72,'scale_px_per_pt':1.5,'outline_color':'#666666','outline_width_pixels':2,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_sha256':cfg['sha256']})
            html+=f'<article><p>Item {entry["item"]} · PDF page index {r["pdf_page_index"]}</p><img alt="Item {entry["item"]} exact crop" src="item-{entry["item"]:02d}.png"><img alt="Item {entry["item"]} context crop" src="item-{entry["item"]:02d}-context.png"></article>'
    html+='</html>\n';(ROOT/'audit/index.html').write_text(html)
    (ROOT/'audit-context-crops-manifest.json').write_text(json.dumps(records,sort_keys=True,indent=2)+'\n')
    assert csv_path.read_bytes()==csv_before and (ROOT/'audit-private-mapping.json').read_bytes()==mapping_raw
    assert all(e['block_id'] not in html for e in entries)
    print('P2C-A2 PASS: 50 unchanged items, 100 images, 72pt native context; CSV and mapping byte-unchanged')


if __name__=='__main__':main()
