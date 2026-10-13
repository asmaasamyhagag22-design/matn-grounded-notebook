"""Resumed Part 2c diagnostics; rules committed first, v1 retained intact."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

from eval.rag import r_lite_3_part1 as prior
from eval.rag.r_lite_3_part2c_project import project
from eval.rag.r_lite_3_part2c_m3_v2 import decisions
from eval.rag.r_lite_3_part2c_urls import url_lines

OUT=Path('out/r-lite-3/part2c')


def read(p):return json.loads(Path(p).read_text())


def emit(name,data):
    (OUT/name).write_text(json.dumps(data,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def native_crops(sources,requests,stem):
    """Cached native renders first; requested dev crops otherwise render after registry SHA check."""
    from PIL import Image
    cached={(r['source'],r['pdf_page_index']):r for r in read('out/r-lite-3/part1/crops-manifest.json')}
    registry={r['doc_id']:r for r in read('eval/registry.json')['documents'] if r['doc_id'] in (*prior.DEV,prior.WEF)}
    rows=[];opened={};blocks={k:{e.block.block_id:e.block for e in s['document'].elements} for k,s in sources.items()}
    try:
        for key,bid in sorted(set(requests)):
            block=blocks[key][bid];parent=cached.get((key,block.page_index));scale=1.5
            if parent:
                assert hashlib.sha256(Path(parent['path']).read_bytes()).hexdigest()==parent['sha256']
                im=Image.open(parent['path']).convert('RGB');origin={'parent_render_path':parent['path'],'parent_render_sha256':parent['sha256']}
            else:
                assert key in registry,'UNAPPROVED_REAL6_PDF_ACCESS'
                entry=registry[key];path=Path('eval')/entry['file'];assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256'],'PDF_SHA_MISMATCH'
                import pypdfium2 as pdfium
                if key not in opened:opened[key]=pdfium.PdfDocument(str(path))
                page=opened[key][block.page_index];bitmap=page.render(scale=scale);im=bitmap.to_pil().convert('RGB');bitmap.close();page.close();origin={'pdf_path':str(path),'pdf_sha256':entry['sha256']}
            x0,y0,x1,y1=block.bbox;pixel=(max(0,int(x0*scale)),max(0,int(y0*scale)),min(im.width,int(x1*scale+1)),min(im.height,int(y1*scale+1)))
            path=OUT/'crops'/stem/key/(bid.rsplit(':',1)[-1]+'.png');path.parent.mkdir(parents=True,exist_ok=True);im.crop(pixel).save(path);im.close()
            rows.append({'source':key,'block_id':bid,'pdf_page_index':block.page_index,'bbox':list(block.bbox),'scale_px_per_pt':scale,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),**origin})
    finally:
        for doc in opened.values():doc.close()
    emit(stem+'-crops-manifest.json',rows);return rows


def urls(sources,rule,result):
    mono=re.compile(rule['font_regex']);pattern=re.compile(rule['url_regex']);inventory=[]
    for key,src in sources.items():
        associated=defaultdict(set);raw=prior.raw_records(src)
        for page in src['snapshot']['pages']:
            lines=[]
            for record in page['blocks']:
                for li,line in enumerate(record['lines']):
                    ws=line['words']
                    if not ws or not all(w.get('font_face') and w.get('size',0)>0 for w in ws):continue
                    box=[min(w['bbox'][0] for w in ws),min(w['bbox'][1] for w in ws),max(w['bbox'][2] for w in ws),max(w['bbox'][3] for w in ws)]
                    lines.append({'bid':record['block']['block_id'],'index':li,'words':ws,'bbox':box,'size':max(w['size'] for w in ws),'y':(box[1]+box[3])/2})
            _,matches=url_lines(lines,rule)
            for match in matches:
                for i in match['line_indices']:associated[lines[i]['bid']].update(match['url_tokens'])
        for bid,record in raw.items():
            ws=[w for l in record['lines'] for w in l['words']]
            if not any(mono.search(w.get('font_face','')) for w in ws):continue
            tokens=set(pattern.findall(record['block']['text']))|associated[bid]
            if not tokens:continue
            outcome='UNKNOWN' if bid in result[key]['unknown_ids'] else 'GUTTER_EXCLUDED' if bid in result[key]['excluded_gutter_block_ids'] else 'TEXT_CODE' if bid in result[key]['code_block_ids'] else 'UNCHANGED'
            inventory.append({'source':key,'block_id':bid,'pdf_page_index':record['block']['page_index'],'text':record['block']['text'],'URL_tokens':sorted(tokens),'v2_decision':outcome})
    emit('m3-v2-url-blocks.json',inventory);native_crops(sources,[(r['source'],r['block_id']) for r in inventory],'m3-v2-urls');return inventory


def m3():
    sources=prior.load_sources();rule=read('eval/rag/r_lite_3_part2c_m3_v2_rule.json')
    result={k:decisions(s,rule) for k,s in sources.items()};emit('m3-v2-decisions.json',result)
    projection,after=project(sources,result,read('eval/rag/frozen/questions.json')['items'],rule['name']);emit('m3-v2-projection.json',projection)
    old=read('out/r-lite-3/part2c/v1/m3-gates.json')['six_early_footnotes'];by={e.block.block_id:e for e in sources[prior.DEV[0]]['document'].elements};newby={e.block.block_id:e for e in after[prior.DEV[0]].elements}
    early=[dict(r,unchanged=all(by[b].model_dump(mode='json')==newby[b].model_dump(mode='json') and b not in result[prior.DEV[0]]['code_block_ids'] for b in r['block_ids'])) for r in old]
    markers=[]
    for key,src in sources.items():
        newby={e.block.block_id:e for e in after[key].elements}
        for e in src['document'].elements:
            if '+' not in e.block.text and '-' not in e.block.text:continue
            n=newby[e.block.block_id]
            markers.append({'source':key,'block_id':e.block.block_id,'text_exact':e.block.text==n.block.text,'citable_retained':not e.citable or n.citable,'plus_count':e.block.text.count('+'),'minus_count':e.block.text.count('-')})
    changed=[(k,b) for k,r in projection['sources'].items() if k!=prior.DEV[0] for b in r['changed_block_ids']];native_crops(sources,changed,'m3-v2-changes')
    inventory=urls(sources,rule,result)
    passed=len(early)==6 and all(r['unchanged'] for r in early) and all(r['text_exact'] and r['citable_retained'] for r in markers) and not any(r['prediction_failure'] for r in projection['sources'].values()) and not projection['frozen']['counts']['T2'] and not projection['frozen']['counts']['T3']
    gates={'status':'PASS' if passed else 'STOP_M3_V2_NO_V3','six_early_footnotes':early,'controls_are_known_not_accuracy_evidence':True,'all_plus_minus_retained':all(r['text_exact'] and r['citable_retained'] for r in markers),'marker_blocks':markers,'changes_outside_arxiv':len(changed),'url_blocks':len(inventory),'frozen':projection['frozen']['counts'],'arxiv_footnotes_after':projection['sources'][prior.DEV[0]]['chunk_distribution']['footnote'],'rule_retuned':False}
    emit('m3-v2-gates.json',gates);print(json.dumps({k:v for k,v in gates.items() if k not in ['six_early_footnotes','marker_blocks']},sort_keys=True))
    if not passed:raise SystemExit(32)


if __name__=='__main__':m3()


def docling_compare():
    from collections import Counter
    from eval.rag.r_lite_3_part2b_mapping import convert_box,union_share
    sources=prior.load_sources();src=sources[prior.DEV[0]];request=read(OUT/'docling-code-request.json');labels=read(OUT/'docling-code-labels.json');result=read(OUT/'m3-v2-decisions.json')[prior.DEV[0]]
    assert labels['status']=='COMPLETE' and len(labels['pages'])==len(request['pages'])
    assert {p['pdf_page_index'] for p in labels['pages']}==set(request['pages'])
    page_sizes={p['page_index']:[p['width'],p['height']] for p in src['snapshot']['pages']};by_page={p['pdf_page_index']:p for p in labels['pages']};rows=[];requests=[]
    for e in src['document'].elements:
        bid=e.block.block_id
        if not e.citable or e.block.page_index not in by_page:continue
        p=by_page[e.block.page_index];code_boxes=[convert_box(r['bbox'],p['docling_page_size'],page_sizes[e.block.page_index]) for r in p['regions'] if r['label']=='code']
        share=union_share(list(e.block.bbox),code_boxes);m3=bid in result['code_block_ids'];docling=share>=0.5
        row={'block_id':bid,'pdf_page_index':e.block.page_index,'M3_v2_code':m3,'M3_v2_gutter':bid in result['excluded_gutter_block_ids'],'M3_known':bid not in result['unknown_ids'],'Docling_code_union_share':share,'Docling_code':docling,'agreement':m3==docling,'original_footnote_cohort':bid in request['cohort_block_ids']};rows.append(row)
        if not row['agreement']:requests.append((prior.DEV[0],bid))
    known=[r for r in rows if r['M3_known']];cohort=[r for r in known if r['original_footnote_cohort']]
    data={'status':'DIAGNOSTIC_ONLY_NO_DECISION_POWER','configuration_commit':'0eb5651','mapping':'CODE region union covers >=0.5 of block bbox; same union machinery as Part 2b; diagnostic, not a rule change','pages':len(labels['pages']),'region_labels':dict(Counter(r['label'] for p in labels['pages'] for r in p['regions'])),'all_citable_selected_page_rows':rows,'known_blocks':len(known),'unknown_blocks':len(rows)-len(known),'agreements':sum(r['agreement'] for r in known),'footnote_cohort_known':len(cohort),'footnote_cohort_agreements':sum(r['agreement'] for r in cohort),'disagreement_ids':[r['block_id'] for r in known if not r['agreement']],'M3_rule_changed':False}
    emit('docling-code-agreement.json',data);native_crops(sources,requests,'docling-code-disagreements')
    print(json.dumps({k:v for k,v in data.items() if k not in ['all_citable_selected_page_rows','disagreement_ids']},sort_keys=True))


def m4():
    from eval.rag.r_lite_3_part2c_m4 import decisions as join
    import re
    sources=prior.load_sources();rule=read('eval/rag/r_lite_3_part2c_m4_rule.json');objects=read('out/r-lite-3/part1/objects.json')
    changes={k:join(src,objects,k,rule) for k,src in sources.items()};emit('m4-decisions.json',changes)
    projection,_=project(sources,changes,read('eval/rag/frozen/questions.json')['items'],rule['name']);emit('m4-projection.json',projection)
    tables=[];glyphs=[]
    for k,src in sources.items():
        for e in src['document'].elements:
            old=e.block.text;new=changes[k]['texts'].get(e.block.block_id,old)
            if re.search(r'T\s*A\s*B\s*L\s*E\s+A\s*3',old):
                # Only the existing word boundary matters; do not demand unmeasured joining in unknown blocks.
                compact_letters=re.sub(r'(?<=[A-Z])\s+(?=[A-Z])','',new)
                boundary=bool(re.search(r'T\s*A\s*B\s*L\s*E\s+A\s*3',new))
                tables.append({'source':k,'block_id':e.block.block_id,'old_text':old,'new_text':new,'TABLE_A3_boundary_preserved':boundary,'changed':old!=new})
            if old!=new:glyphs.append({'source':k,'block_id':e.block.block_id,'all_nonspace_glyphs_retained':''.join(old.split())==''.join(new.split()),'only_synthetic_spaces_removed':all(old[i]==' ' for i in changes[k]['offset_remaps'][e.block.block_id]['deleted_synthetic_space_offsets'])})
    changed=[(k,b) for k,r in changes.items() if k!=prior.WEF for b in r['texts']];native_crops(sources,changed,'m4-outside-wef')
    named=all(len(r['offset_remaps'])==len(r['texts']) and all(d['normalization']==rule['name'] for d in r['details']) for r in changes.values())
    passed=bool(tables) and all(r['TABLE_A3_boundary_preserved'] for r in tables) and all(r['all_nonspace_glyphs_retained'] and r['only_synthetic_spaces_removed'] for r in glyphs) and named and not any(r['prediction_failure'] for r in projection['sources'].values()) and not projection['frozen']['counts']['T2'] and not projection['frozen']['counts']['T3']
    gates={'status':'PASS' if passed else 'STOP_M4_GATE_FAILURE','TABLE_A3_controls':tables,'all_source_glyphs_retained':all(r['all_nonspace_glyphs_retained'] and r['only_synthetic_spaces_removed'] for r in glyphs),'changed_block_glyph_checks':glyphs,'every_affected_block_named_remap':named,'outside_WEF_changes':len(changed),'frozen':projection['frozen']['counts'],'source_change_counts':{k:len(v['texts']) for k,v in changes.items()},'rule_retuned':False}
    emit('m4-gates.json',gates);print(json.dumps({k:v for k,v in gates.items() if k not in ['TABLE_A3_controls','changed_block_glyph_checks']},sort_keys=True))
    if not passed:raise SystemExit(33)
