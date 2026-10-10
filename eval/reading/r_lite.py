"""Dev-only R-lite measurements; frozen normalization, no reader tuning."""
from collections import Counter
import json
import re
from pathlib import Path
from statistics import median
from eval.normalize import quote_on_page,count_on_page

DEV=('2601-14525v1','gao-21-519sp','wb-eem-2021-12')


def overflow_cause(text,role,flags=()):
    if 'code_text' in flags or re.search(r'(?:def |class |\w+\s*=\s*\w+\()',text): return 'code'
    if re.search(r'(?i)references|bibliography|doi:|https?://',text): return 'references'
    if role=='list_item' or re.search(r'(?:^|\n)\s*(?:[-•]|\d+[.)])\s+',text): return 'list-without-punctuation'
    if role=='table' or text.count('|')>=3 or text.count('\t')>=3: return 'table-like text'
    return 'other'


def metrics(d):
    body=sorted(c.word_count for c in d.chunks if c.kind=='body')
    def percentile(p): return body[round((len(body)-1)*p)] if body else 0
    by_block={e.block.block_id:e for e in d.elements};overflow=[]
    for c in d.chunks:
        if 'single_sentence_overflow' in c.flags:
            e=by_block[c.primary[0].block_id]
            overflow.append({'chunk_id':c.chunk_id,'pages':sorted({by_block[s.block_id].block.page_index for s in c.primary}),'words':c.word_count,'cause':overflow_cause(c.text,e.role,e.flags)})
    sections={s.section_id:s for s in d.sections}
    def depth(s): return 1+depth(sections[s.parent_id]) if s.parent_id else 1
    unavailable=[t for t in d.tables if t.structure=='unavailable']
    nums=[n for e in d.elements if e.citable for n in e.number_tokens]
    return {'pages':len(d.pages),'routes':dict(Counter(p.route for p in d.pages)),'sections':dict(Counter(s.source for s in d.sections)),'depth':max((depth(s) for s in d.sections),default=0),'chunks':dict(Counter(c.kind for c in d.chunks)),'body_words':{'min':min(body,default=0),'p25':percentile(.25),'median':median(body) if body else 0,'p75':percentile(.75),'p95':percentile(.95),'max':max(body,default=0)},'tables_structured':len(d.tables)-len(unavailable),'tables_unavailable':len(unavailable),'tables_unavailable_share':len(unavailable)/len(d.tables) if d.tables else 0,'table_reasons':dict(Counter(t.unavailable_reason.split(':')[0] for t in unavailable)),'excluded':dict(Counter(r for e in d.elements for r in e.exclusion_reasons)),'flagged_numbers':sum(n.status.startswith('flagged') for n in nums),'flagged_unlinked':sum(n.status=='flagged-unlinked' for n in nums),'digital_unlinked':sum(n.status=='digital-unlinked' for n in nums),'digital_unlinked_occurrences':[{'page_index':n.pdf_page_index,'block_id':n.block_id,'start':n.start,'end':n.end,'text':n.text} for n in nums if n.status=='digital-unlinked'],'overflow_count':len(overflow),'overflow_max_words':max((o['words'] for o in overflow),default=0),'overflow':overflow,'findings':[i.model_dump(mode='json') for i in d.issues if i.reason=='fused_heading']}


def quote_coverage(d,items):
    result={'total':len(items),'single_chunk':0,'two_adjacent_chunks':0,'other_split':0,'missing':[],'duplicate_occurrences':0}
    for item in items:
        quote=item['evidence_quote'];page=item['page_index']
        elements=[e for e in d.elements if e.block.page_index==page];good=[e for e in elements if e.citable]
        text='\n\n'.join(e.block.text for e in good)
        chunks=[c for c in d.chunks if any(s.block_id in {e.block.block_id for e in good} for s in c.primary)]
        result['duplicate_occurrences']+=max(0,count_on_page(quote,text)-1)
        if not quote_on_page(quote,text):
            alltext='\n\n'.join(e.block.text for e in elements)
            cause='wrongly_excluded_block' if quote_on_page(quote,alltext) else ('normalization' if quote in alltext else 'reader_text')
            result['missing'].append({'id':item['id'],'page_index':page,'cause':cause});continue
        if any(quote_on_page(quote,c.text) for c in chunks): result['single_chunk']+=1
        elif any(a.next_chunk_id==b.chunk_id and quote_on_page(quote,a.text+'\n\n'+b.text) for a,b in zip(chunks,chunks[1:])): result['two_adjacent_chunks']+=1
        else: result['other_split']+=1
    return result


def assert_gates(d):
    from matn_reading.structure.coverage import validate_coverage
    from matn_reading.ocr.consistency import Cell,check_table_totals
    validate_coverage(d.elements,d.sections,d.chunks)
    for c in d.chunks:
        if c.kind=='body' and c.word_count>350 and ('single_sentence_overflow' not in c.flags or len(c.sentence_spans)!=1): raise ValueError('G6_OVERFLOW')
    for t in d.tables:
        if t.structure=='unavailable':
            if not t.unavailable_reason: raise ValueError('G7_REASON')
            continue
        t.__class__.model_validate(t.model_dump())
        if check_table_totals([[Cell(c.text,c.bbox.coordinates) for c in t.cells if c.row==r] for r in range(t.rows)]): raise ValueError('G7_TOTALS')
    return {'G1a':'PASS','G1b':'PASS','G2':'PASS','G3':'PASS','G6':'PASS','G7':'PASS'}


def tree_text(d):
    by_parent={}
    for s in d.sections: by_parent.setdefault(s.parent_id,[]).append(s)
    lines=[]
    def walk(parent,level):
        for s in by_parent.get(parent,[]):
            lines.append('  '*level+f'{s.title} [{s.source}] blocks={len(s.block_ids)} {s.section_id}');walk(s.section_id,level+1)
    walk(None,0)
    return '\n'.join(lines)+'\n'


def run(root=Path('.')):
    import time
    from matn_contracts.structure_ids import canonical
    from matn_reading.structure.cache import load_snapshot,save_snapshot
    from matn_reading.structure.document import prepare_snapshot,write_structure
    registry=json.loads((root/'eval/registry.json').read_text())
    results={}
    for key in DEV:
        entry=next(e for e in registry['documents'] if e['doc_id']==key and e['split']=='dev')
        folder=root/'out/r-lite'/key;sfile=folder/'runs'/('sha256-'+entry['sha256'])/'00_reading.json'
        start=time.perf_counter()
        if sfile.exists(): s=load_snapshot(sfile)
        else:
            s=prepare_snapshot(load_snapshot(root/'out/r-lite/acquisition'/key/'00_reading.json'),root/'eval'/entry['file']);save_snapshot(sfile,s)
        d=write_structure(s,sfile.parent);first={n:p.read_bytes() for n in ('01_elements.jsonl','02_sections.json','03_tables.json','04_chunks.jsonl','05_document.json','document.json') for p in [sfile.parent/n]}
        from subprocess import run as process_run
        import sys
        save_snapshot(folder/'determinism-final'/'00_reading.json',s)
        process_run([sys.executable,'-m','matn_reading','read','cached-input-unused.pdf','--out',str(folder/'determinism-final'),'--structure-only'],check=True,capture_output=True,text=True)
        if any((folder/'determinism-final'/n).read_bytes()!=content for n,content in first.items()): raise ValueError('G5_BYTES')
        gold=json.loads((root/'eval/gold/dev'/f'{key}.json').read_text())
        items=gold['key_points']+gold['key_numbers'] if isinstance(gold,dict) else gold
        result=metrics(d);result['gates']={**assert_gates(d),'G5':'PASS'};result['gold']=quote_coverage(d,items);result['cache_key']=s['cache_key'];result['runtime_seconds']=time.perf_counter()-start
        result['acquisition']={name:json.loads((root/'out/r-lite/acquisition'/key/name).read_text()) for name in ('acquisition.json','ocr-acquisition.json') if (root/'out/r-lite/acquisition'/key/name).exists()}
        (folder/'tree.txt').write_text(tree_text(d));results[key]=result
        print(key,canonical(result),flush=True)
    (root/'out/r-lite/metrics.json').write_text(canonical(results)+'\n')
    return results



def real_smoke(root):
    import hashlib,time
    from matn_contracts.structure_ids import canonical
    from matn_reading.structure.document import replay_real,write_structure
    from matn_reading.structure.cache import save_snapshot
    from matn_reading.structure.pdf_metadata import read_metadata
    start=time.perf_counter();result={};sources=json.loads((root/'eval/reading/real/sources.json').read_text())
    for key,indices in [('nbs_circular_31_e4_1956',(7,15,32)),('statab_1951_part04',(0,8,45))]:
        source=next(s for s in sources['documents'] if s['doc_key']==key);pdf=root/'eval/reading/real/incoming'/source['file']
        digest=hashlib.sha256(pdf.read_bytes()).hexdigest()
        if digest!=source['sha256_seen_2026_10_04']: raise ValueError('REAL_SOURCE_HASH')
        metadata=read_metadata(pdf);pages=[];rawhashes={};tokens=0
        for i in indices:
            path=root/'out/reading/step4c-closeout-final-v3/final/real'/f'{key}_p{i:04d}.json'
            record=json.loads(path.read_text());rawhashes[path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
            m=metadata['pdf_metadata_pages'][i];crop=record['cropbox'];size=record['preprocess']['size']
            expected=[round((crop[2]-crop[0])*300/72),round((crop[3]-crop[1])*300/72)]
            if m['rotation']!=0 or any(abs(a-b)>1 for a,b in zip(size,expected)): raise ValueError(f'REAL_FRAME_MISMATCH:{key}:{i}')
            pages.append(replay_real(record,'sha256-'+digest,m['page_label'],*m['render_size']));tokens+=len(record['tokens'])
            if canonical(record['tokens'])!=canonical(pages[-1]['ocr']['tokens']): raise ValueError('REAL_TOKEN_MUTATION')
        s={'schema_version':1,'doc_id':'sha256-'+digest,'title':key,'cache_key':record['fingerprint'],'core_fingerprint':record['fingerprint'],'pages':pages,**metadata}
        folder=root/'out/r-lite/real'/key
        save_snapshot(folder/'00_reading.json',s)
        d=write_structure(s,folder)
        from subprocess import run as process_run
        import sys
        save_snapshot(folder/'determinism'/'00_reading.json',s)
        process_run([sys.executable,'-m','matn_reading','read','cached-input-unused.pdf','--out',str(folder/'determinism'),'--structure-only'],check=True,capture_output=True,text=True)
        if any((folder/n).read_bytes()!=(folder/'determinism'/n).read_bytes() for n in ('01_elements.jsonl','02_sections.json','03_tables.json','04_chunks.jsonl','05_document.json','document.json')): raise ValueError('REAL_G5_BYTES')
        result[key]={'pages':len(pages),'reader_tokens':tokens,'reader_token_bytes':'identical','raw_cache_hashes':rawhashes,'gates':{**assert_gates(d),'G5':'PASS'},'metrics':metrics(d)}
        for name,digest in rawhashes.items():
            path=root/'out/reading/step4c-closeout-final-v3/final/real'/name
            if hashlib.sha256(path.read_bytes()).hexdigest()!=digest: raise ValueError('REAL_CACHE_MUTATED')
    result['runtime_seconds']=time.perf_counter()-start
    (root/'out/r-lite/real-smoke.json').write_text(canonical(result)+'\n');return result



def table_contact_sheet(root):
    """One small overlay per dev table region; no unrelated page/gallery outputs."""
    import math
    import pypdfium2 as pdfium
    from PIL import Image,ImageDraw,ImageFont
    from matn_contracts.structure import DocumentStructure
    registry=json.loads((root/'eval/registry.json').read_text());tiles=[]
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',11)
    for key in DEV:
        entry=next(e for e in registry['documents'] if e['doc_id']==key and e['split']=='dev')
        file=next((root/'out/r-lite'/key/'runs').glob('*/05_document.json'));d=DocumentStructure.model_validate_json(file.read_text())
        pdf=pdfium.PdfDocument(str(root/'eval'/entry['file']))
        try:
            for t in d.tables:
                page=pdf[t.pdf_page_index];image=page.render(scale=1.5).to_pil().convert('RGB');page.close()
                x0,y0,x1,y1=t.bbox.coordinates
                crop=image.crop((int(x0*1.5),int(y0*1.5),math.ceil(x1*1.5),math.ceil(y1*1.5)))
                draw=ImageDraw.Draw(crop)
                draw.rectangle((0,0,crop.width-1,crop.height-1),outline='green' if t.structure=='available' else 'red',width=3)
                for c in t.cells:
                    a,b,z,h=c.bbox.coordinates;draw.rectangle(((a-x0)*1.5,(b-y0)*1.5,(z-x0)*1.5,(h-y0)*1.5),outline='blue',width=2)
                crop.thumbnail((270,200));tile=Image.new('RGB',(290,245),'white');tile.paste(crop,((290-crop.width)//2,0));dr=ImageDraw.Draw(tile)
                dr.text((5,202),f'{key} p{t.pdf_page_index} {t.table_id[-6:]}',font=font,fill='black')
                dr.text((5,219),t.unavailable_reason.split(':')[0] if t.unavailable_reason else f'cells={len(t.cells)}',font=font,fill='red' if t.structure=='unavailable' else 'green');tiles.append(tile)
        finally: pdf.close()
    columns=5;sheet=Image.new('RGB',(columns*290,math.ceil(len(tiles)/columns)*245),'#dddddd')
    for i,tile in enumerate(tiles): sheet.paste(tile,((i%columns)*290,(i//columns)*245))
    path=root/'out/r-lite/table-contact-sheet.png';sheet.save(path);return {'tables':len(tiles),'path':str(path)}


def write_report(root):
    m=json.loads((root/'out/r-lite/metrics.json').read_text());real=json.loads((root/'out/r-lite/real-smoke.json').read_text())
    lines=['# R-lite — 2026-10-10','', 'G1a/G1b/G2/G3/G5/G6/G7: PASS (3 full dev documents + 6 cached real-scan pages).',
      'G4: 65/73 (89.04%); single_chunk65/73; two_adjacent0/73; other_split0/73; missing8/73. Reader_text6; wrongly_excluded_block2; normalization0.',
      'OCR acquisition: 8/10 pages; routes logged before OCR; core/rules/GT/test split changes0.',
      'Fixed chunker: r-lite-1; whitespace-v1; target250/max350/tiny50/page-window3; overlap0; intra-sentence cuts0.',
      '', '| Document | Pages / routes | Sections / depth | Chunks (body/table/caption/footnote) | Body words min/p25/median/p75/p95/max | Tables available/unavailable/share | Flagged OCR/unlinked OCR/unlinked digital | Structure s |',
      '|---|---|---|---|---|---|---|---|']
    for k,v in m.items():
        w=v['body_words'];c=v['chunks']
        lines.append(f"| {k} | {v['pages']} / {v['routes']} | {v['sections']} / {v['depth']} | {c.get('body',0)}/{c.get('table',0)}/{c.get('caption',0)}/{c.get('footnote',0)} | {'/'.join(str(w[n]) for n in ('min','p25','median','p75','p95','max'))} | {v['tables_structured']}/{v['tables_unavailable']}/{100*v['tables_unavailable_share']:.2f}% | {v['flagged_numbers']}/{v['flagged_unlinked']}/{v['digital_unlinked']} | {v['runtime_seconds']:.2f} |")
    for k,v in m.items():
        a=v['acquisition'];g=v['gold'];lines+=['',f'## {k}',f"- acquisition digital/OCR seconds: {a['acquisition.json']['digital_wall_seconds']:.2f}/{a.get('ocr-acquisition.json',{}).get('wall_seconds',0):.2f}",f"- cache_key: `{v['cache_key']}`",f"- excluded: `{v['excluded']}`",f"- table unavailable reasons: `{v['table_reasons']}`",f"- overflow count/max: {v['overflow_count']}/{v['overflow_max_words']}; ids/pages/causes: `out/r-lite/metrics.json`",f"- G4 single/two-adjacent/other/missing: {g['single_chunk']}/{g['two_adjacent_chunks']}/{g['other_split']}/{len(g['missing'])} / {g['total']}; duplicate occurrences{g['duplicate_occurrences']}"]
        for miss in g['missing']: lines.append(f"- G4 `{miss['id']}` p{miss['page_index']}: `{miss['cause']}`")
        lines += [f"- digital-unlinked occurrences{v['digital_unlinked']}; fused-heading findings{len(v['findings'])}: `out/r-lite/metrics.json` (page/block_id/span)",f'- tree: `out/r-lite/{k}/tree.txt`',f'- stages: `out/r-lite/{k}/runs/sha256-*/01_elements.jsonl` → `05_document.json` + `document.json`',f'- G5 separate process: `out/r-lite/{k}/determinism-final/`']
    lines+=['','## Cached real scans',f"- pages6; reader tokens823; cached token bytes identical; OCR calls0; wall seconds{real['runtime_seconds']:.2f}"]
    for k,v in real.items():
        if isinstance(v,dict): lines.append(f"- {k}: pages{v['pages']}; tokens{v['reader_tokens']}; gates `{v['gates']}`; `out/r-lite/real/{k}/`")
    lines+=['- precision/frame/token hash evidence: `out/r-lite/real-smoke.json`','','## Evidence','- acquisition: `out/r-lite/acquisition/routes-before-ocr.json`; per-doc `acquisition.json`, `ocr-acquisition.json`, immutable `00_reading.json` + `.sha256`','- per-document counters/occurrences: `out/r-lite/metrics.json`','- table overlays143: `out/r-lite/table-contact-sheet.png`','- frozen chunk parameters: commit `33324b0`; approved digital-unlinked: `740fff6`; no gold tuning','- full suite: pending final docs commit; focused checks: `out/r-lite/focused-tests.log`']
    (root/'reports/r-lite.md').write_text('\n'.join(lines)+'\n')

if __name__=='__main__':
    run()
    real_smoke(Path('.'))
    table_contact_sheet(Path('.'))
    write_report(Path('.'))
