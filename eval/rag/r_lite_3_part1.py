"""Read-only R-lite.3 mechanism inventory and bounded in-memory interventions.

Reproduce: source scripts/dev_environment.sh && .venv/bin/python -m eval.rag.r_lite_3_part1
No acquisition, OCR, models, indexing, retrieval, cache writes or production imports of this module.
Candidate cohorts and limits are explicit; finite interventions are not trained classifiers.
"""
from collections import Counter, defaultdict
import copy
import hashlib
import inspect
import json
from pathlib import Path
import random
import re
from statistics import median

from checks.egress_guard import block_egress
from matn_contracts.domain import Block
from matn_contracts.structure_ids import structure_id
from matn_contracts.structure import DocumentStructure
from matn_reading.structure.elements import build_elements, word_ledger
from eval.rag.question_tools import locate
from types import SimpleNamespace
from matn_reading.structure.sections import build_sections
from matn_reading.structure.chunks import build_chunks, _make
from matn_reading.structure.coverage import validate_coverage
from eval.rag.r_lite_3_identity import recompute_block, main as identity_main, DEFINITIONS

OUT=Path('out/r-lite-3/part1')
DEV=('2601-14525v1','gao-21-519sp','wb-eem-2021-12')
WEF='wef-future-of-jobs-2025'
REAL=('nbs_circular_31_e4_1956','statab_1951_part04')
PROFILE=tuple(range(64,76))+tuple(range(83,89))
SPACED=re.compile(r'(?<!\w)(?:[A-Z] ){2,}[A-Z](?!\w)')
MONO=re.compile(r'(?i)courier|mono|consolas|inconsolata|typewriter|nimbusmon')
INPUTS={}


def read(path):
    path=Path(path);raw=path.read_bytes();INPUTS[str(path)]=hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def emit(name,data):
    path=OUT/name;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')


def scope_counts(rows,exclude_cover=False):
    counts=Counter();moves=Counter();numbers=[]
    for p in rows:
        if exclude_cover and p['pdf_page_index']==0:continue
        counts.update(p['word_counts']);moves.update(p['disposition_moves'])
        numbers.extend(x for x in p['every_numeric_token'] if x['status']=='matched')
    bad=[x for x in numbers if x['ocr']['disposition']=='accepted' and x['digital']['value']!=x['ocr']['value']]
    return {'alignment':dict(counts),'disposition_moves':dict(moves),'matched_numbers':len(numbers),'accepted_value_disagreements':bad}


def target_class(identity_same,citable_same,chunks_same):
    return 'T3' if not identity_same else 'T2' if not citable_same else 'T1' if not chunks_same else 'T0'


def short_distribution(values):
    return {'n':len(values),'min':min(values) if values else None,'median':median(values) if values else None,'max':max(values) if values else None,'below':{str(t):sum(x<t for x in values) for t in (1,2,5,10)},'histogram':dict(Counter(values))}


def load_sources():
    result={}
    for key in (*DEV,*REAL,WEF):
        if key in DEV: snap=next(Path('out/r-lite-2',key,'runs').glob('*/00_reading.json'))
        elif key in REAL:snap=Path('out/r-lite-2/real',key,'00_reading.json')
        else:snap=Path('out/rag-core/wef-first-run/approved-acquisition/runs/sha256-f25987c0dee6eba2d832f80924b0e926a4705605cbd6a5c5f10323897da31271/00_reading.json')
        doc=Path('out/rag-core/section-rebuild',key,'05_document.json')
        result[key]={'snapshot':read(snap),'document':DocumentStructure.model_validate(read(doc)),'snapshot_path':str(snap),'document_path':str(doc)}
    return result


def table_ids(doc):return {s.block_id for c in doc.chunks if c.kind=='table' for s in c.primary}


def raw_records(source):return {r['block']['block_id']:r for p in source['snapshot']['pages'] for r in p['blocks']}


def mono_blocks(source):
    raw=raw_records(source)
    return {e.block.block_id for e in source['document'].elements if e.citable and e.role=='footnote' and (source['document'].doc_id!='sha256-ad9f9d0d152930510045d485eebb695ab15b8f775e9bfd63313355c591a675d7' or e.block.page_index>=23) and any(MONO.search(w.get('font_face','')) for line in raw[e.block.block_id]['lines'] for w in line['words'])}


def transforms(sources):
    """Complete finite candidate definitions, including intentionally broad guard counterfactuals."""
    cohorts={};labels=read('eval/rag/wef-table-visual-annotations.json')['items']
    d=sources[WEF]['document'];chunks={c.chunk_id:c for c in d.chunks}
    sampled={s.block_id for r in labels for s in chunks[r['chunk_id']].primary}
    for key,source in sources.items():
        doc=source['document'];by={e.block.block_id:e for e in doc.elements}
        mono=mono_blocks(source)
        bare={b for b in mono if re.fullmatch(r'(?:\d+\s*[+-]?\s*)+',by[b].block.text)}
        spaced={e.block.block_id for e in doc.elements if SPACED.search(e.block.text)}
        mixed={p['page_index'] for p in source['snapshot']['pages'] if p['route']=='mixed'}
        cohorts[key]={'chart_sample':sampled if key==WEF else set(),'all_tables':table_ids(doc),
            'profile_headings':{e.block.block_id for e in doc.elements if e.citable and e.role=='heading' and e.block.page_index in PROFILE and e.block.style.font_size_pt==9 and len(e.block.text.split())>=8} if key==WEF else set(),
            'mono_footnotes':mono,'bare_gutter':bare,'regular_gutter':{e.block.block_id for e in doc.elements if key==DEV[0] and e.citable and e.role=='footnote' and e.block.page_index>=23 and e.block.text.isdigit() and 60<=e.block.bbox[0]<=75 and e.block.bbox[2]<=85},'spaced':spaced,'mixed_pages':mixed}
    return cohorts


def predict(sources,cohorts,questions,name,mode,overrides=None):
    results={};all_after={}
    for key,src in sources.items():
        old=src['document'];snap=src['snapshot'];by={e.block.block_id:e for e in old.elements};selected=set();roles={};excluded=set();texts={};changed_pages=set()
        if mode=='sample_chart': selected=cohorts[key]['chart_sample'];roles={b:'figure' for b in selected};excluded=selected
        elif mode=='quarantine_wef_tables' and key==WEF: selected=cohorts[key]['all_tables'];excluded=selected
        elif mode=='quarantine_all_tables': selected=cohorts[key]['all_tables'];excluded=selected
        elif mode=='heading_demote': selected=cohorts[key]['profile_headings'];roles={b:'text' for b in selected}
        elif mode=='mono_retype': selected=cohorts[key]['mono_footnotes'];roles={b:'text' for b in selected}
        elif mode=='bare_exclude': selected=cohorts[key]['bare_gutter'];excluded=selected
        elif mode=='regular_gutter': selected=cohorts[key]['regular_gutter'];excluded=selected
        elif mode=='split_gutter' and key==WEF: selected={b for b,e in by.items() if e.citable and e.role=='text' and e.block.page_index in PROFILE and e.block.page_index in cohorts[key]['mixed_pages'] and e.block.bbox[0]<345 and e.block.bbox[2]>358}
        elif mode=='spacing_join': selected=cohorts[key]['spaced'];texts={b:SPACED.sub(lambda m:m.group().replace(' ',''),by[b].block.text) for b in selected}
        elif mode=='geometry_spacing':texts=(overrides or {}).get(key,{});selected=set(texts)
        elif mode=='healthy_digital': changed_pages=cohorts[key]['mixed_pages'];selected={b for b,e in by.items() if e.block.page_index in changed_pages}
        oldids={e.block.block_id for e in old.elements};mapping={};elements=[];replacements={}
        if mode=='healthy_digital' and changed_pages:
            # Exact saved digital records, no new acquisition; omit regional OCR addition (unknown).
            if key==WEF: digital=read('out/rag-core/wef-first-run/approved-acquisition/digital_read.json')
            elif key in DEV:digital=read(Path('out/r-lite-2/acquisition')/key/'digital_read.json')
            else:digital=None
            if digital is None:
                results[key]={'scope':'real cached OCR only','selected_pages':sorted(changed_pages),'prediction':'NO_SAVED_DIGITAL_LAYER; option keep flagged; no regional OCR predicted'};all_after[key]=old;continue
            newsnap=copy.deepcopy(snap);saved={p['page_index']:p for p in digital['pages']}
            for i,p in enumerate(newsnap['pages']):
                if p['page_index'] in changed_pages:newsnap['pages'][i]=saved[p['page_index']]
            snap=newsnap;raw,_=build_elements(snap);elements=list(raw)
        else:
            for e in old.elements:
                b=e.block;newtext=texts.get(b.block_id,b.text)
                if mode=='split_gutter' and b.block_id in selected:
                    original=raw_records(src)[b.block_id]; records=[]
                    for side in (0,1):
                        lines=[{'words':[w for w in line['words'] if ((w['bbox'][0]+w['bbox'][2])/2<351)==(side==0)]} for line in original['lines']]
                        lines=[line for line in lines if line['words']]
                        if not lines:continue
                        text,_,words=word_ledger({'lines':lines},digital=False)
                        box=[min(w['bbox'][0] for w in words),min(w['bbox'][1] for w in words),max(w['bbox'][2] for w in words),max(w['bbox'][3] for w in words)]
                        data=b.model_dump(mode='json');data.update(text=text,bbox=box);data['block_id']=recompute_block(data);block=Block.model_validate(data)
                        elements.append(e.model_copy(update={'block':block,'bbox':e.bbox.model_copy(update={'coordinates':tuple(box)}),'source_spans':(),'number_tokens':()}))
                        records.append({**original,'block':block.model_dump(mode='json'),'lines':lines})
                    replacements[b.block_id]=records
                    continue
                if newtext!=b.text:
                    data=b.model_dump(mode='json');data['text']=newtext;data['block_id']=recompute_block(data);newb=Block.model_validate(data);mapping[b.block_id]=newb.block_id
                    # Candidate changes invalidate provenance; this counterfactual only predicts text and IDs.
                    e=e.model_copy(update={'block':newb,'source_spans':(),'number_tokens':()})
                updates={}
                if b.block_id in roles:updates['role']=roles[b.block_id]
                if b.block_id in excluded:updates.update(citable=False,exclusion_reasons=('candidate_exclusion',))
                elements.append(e.model_copy(update=updates))
        chunks=old.chunks;sections=old.sections;failure=None
        if mode=='producer_version_migration':
            tmap={}
            for table in old.tables:
                replacement=table.model_copy(update={'producer_version':'r-lite-3'})
                tmap[table.table_id]=structure_id(old.doc_id,'t','r-lite-3',replacement.identity_inputs())
            new=[];cmap={}
            for c in old.chunks:
                tid=tmap.get(c.table_id,c.table_id)
                material=[c.section_id,c.kind,c.text,[m.model_dump(exclude={'primary_chunk_id'}) for m in c.offset_map],tid,c.row_range]
                cid=structure_id(old.doc_id,'c','r-lite-3',material);cmap[c.chunk_id]=cid
                new.append(c.model_copy(update={'chunk_id':cid,'producer_version':'r-lite-3','table_id':tid}))
            chunks=tuple(c.model_copy(update={'offset_map':tuple(m.model_copy(update={'primary_chunk_id':cmap.get(m.primary_chunk_id,m.primary_chunk_id)}) if m.primary_chunk_id else m for m in c.offset_map),'repeated_context':tuple(r.model_copy(update={'primary_chunk_id':cmap[r.primary_chunk_id]}) for r in c.repeated_context),'prev_chunk_id':cmap.get(c.prev_chunk_id),'next_chunk_id':cmap.get(c.next_chunk_id)}) for c in new)
        if selected or changed_pages or mode in ('block_chunks','merge_tiny'):
            try:
                # Use original reader roles on unchanged elements for the section eligibility pass.
                record_by=raw_records(src)
                if not changed_pages:
                    newsnap=copy.deepcopy(snap)
                    for page in newsnap['pages']:
                        page['blocks']=[replacement for r in page['blocks'] for replacement in replacements.get(r['block']['block_id'],[r])]
                        for r in page['blocks']:
                            bid=r['block']['block_id']
                            if bid in mapping:r['block']['block_id']=mapping[bid];r['block']['text']=texts[bid]
                    snap=newsnap
                    eligible=[e.model_copy(update={'role':record_by[next((b for b,n in mapping.items() if n==e.block.block_id),e.block.block_id)]['block']['block_type']}) if e.block.block_id not in roles and e.block.block_id not in mapping and e.block.block_id in record_by else e for e in elements]
                    eligible=[e.model_copy(update={'role':'text','block':e.block.model_copy(update={'style':e.block.style.model_copy(update={'font_size_pt':None})})}) if e.block.block_id in roles and mode=='heading_demote' else e for e in eligible]
                else:eligible=elements
                sections,issues=build_sections(snap,eligible) if mode not in ('block_chunks','merge_tiny') else (old.sections,())
                demoted={i.block_id for i in issues if i.reason=='heading_demoted'}
                elements=[e.model_copy(update={'role':'text'}) if e.block.block_id in demoted else e for e in elements]
                existing={e.block.block_id for e in elements if e.citable and e.role=='table'}
                tables=[t for t in old.tables if t.block_ids and set(t.block_ids)<=existing]
                chunks=build_chunks(snap,elements,sections,tables)
                if mode=='block_chunks' and key==WEF:
                    # Packing-only candidate on 18 pages: one body chunk per source block.
                    emap={e.block.block_id:e for e in elements};smap={s.section_id:s for s in sections};new=[]
                    for c in chunks:
                        if c.kind!='body' or not any(emap[s.block_id].block.page_index in PROFILE for s in c.primary):new.append(c);continue
                        for bid in dict.fromkeys(s.block_id for s in c.primary):
                            parts=[{'block_id':s.block_id,'start':s.start,'end':s.end} for s in c.primary if s.block_id==bid]
                            new.append(_make(snap,smap[c.section_id],'body',parts,emap))
                    chunks=tuple(new)
                elif mode=='merge_tiny':
                    emap={e.block.block_id:e for e in elements};smap={s.section_id:s for s in sections};new=[]
                    for c in chunks:
                        if new and c.kind==new[-1].kind and c.section_id==new[-1].section_id and not c.table_id and not new[-1].table_id and min(c.word_count,new[-1].word_count)<50 and c.word_count+new[-1].word_count<=350:
                            prev=new.pop();parts=[]
                            for j,chunk in enumerate([prev,c]):
                                if j:parts.append({'separator':'\n\n'})
                                for span in chunk.offset_map:
                                    if span.kind=='separator':parts.append({'separator':span.separator})
                                    else:parts.append({'block_id':span.block_id,'start':span.char_start,'end':span.char_end})
                            new.append(_make(snap,smap[c.section_id],c.kind,parts,emap))
                        else:new.append(c)
                    chunks=tuple(new)
                if mode in ('block_chunks','merge_tiny'):
                    grouped=defaultdict(list)
                    for c in chunks:grouped[c.section_id].append(c.chunk_id)
                    chunks=tuple(c.model_copy(update={'prev_chunk_id':grouped[c.section_id][grouped[c.section_id].index(c.chunk_id)-1] if grouped[c.section_id].index(c.chunk_id)>0 else None,'next_chunk_id':grouped[c.section_id][grouped[c.section_id].index(c.chunk_id)+1] if grouped[c.section_id].index(c.chunk_id)+1<len(grouped[c.section_id]) else None}) for c in chunks)
                # Predict primary coverage independent of stale numeric/provenance ledgers.
                lengths={e.block.block_id:len(e.block.text) for e in elements if e.citable and e.block.text};intervals=defaultdict(list)
                for c in chunks:
                    for span in c.primary:intervals[span.block_id].append((span.start,span.end))
                for bid,n in lengths.items():
                    cursor=0
                    for a,b in sorted(intervals[bid]):
                        if a!=cursor:raise ValueError('PREDICTION_COVERAGE:'+bid)
                        cursor=b
                    if cursor!=n:raise ValueError('PREDICTION_COVERAGE:'+bid)
            except ValueError as exc:
                failure=str(exc);sections=old.sections;chunks=old.chunks
        newids={e.block.block_id for e in elements};newby={e.block.block_id:e for e in elements};oldsec={s.section_id:s.model_dump(mode='json') for s in old.sections};newsec={s.section_id:s.model_dump(mode='json') for s in sections}
        oldchunk={c.chunk_id:c.model_dump(mode='json') for c in old.chunks};newchunk={c.chunk_id:c.model_dump(mode='json') for c in chunks}
        changedsec=sorted(k for k in oldsec.keys()|newsec.keys() if oldsec.get(k)!=newsec.get(k));changedchunk=sorted(k for k in oldchunk.keys()|newchunk.keys() if oldchunk.get(k)!=newchunk.get(k))
        offset_changed=sorted(b for b in oldids if b not in newids or (b in newby and newby[b].block.text!=by[b].block.text))
        role_changed=sorted(b for b in oldids&newids if by[b].role!=newby[b].role)
        block_changed=sorted((oldids^newids)|{b for b in oldids&newids if by[b].model_dump(mode='json')!=newby[b].model_dump(mode='json')})
        vector_excluded=sorted(c.chunk_id for c in old.chunks if c.word_count<10) if mode=='vector_short' else []
        input_hashes_before={hashlib.sha256((c.context_prefix+'\n\n'+c.text).encode()).hexdigest() for c in old.chunks}
        changed_embedding_inputs=sorted({hashlib.sha256((SPACED.sub(lambda m:m.group().replace(' ',''),c.context_prefix+'\n\n'+c.text) if mode=='search_spacing' else c.context_prefix+'\n\n'+c.text).encode()).hexdigest() for c in chunks}-input_hashes_before)
        results[key]={'embedding_new_input_hashes':changed_embedding_inputs,'embedding_estimated_new_inputs':len(changed_embedding_inputs),'embedding_estimated_batch8_calls':(len(changed_embedding_inputs)+7)//8,'selected_block_ids':sorted(selected),'selected_pages':sorted(changed_pages),'block_changes':block_changed,'block_ids_removed':sorted(oldids-newids),'block_ids_added':sorted(newids-oldids),'offsets_changed_blocks':offset_changed,'roles_changed_blocks':role_changed,'sections_changed_ids':changedsec,'chunks_changed_ids':changedchunk,'vector_excluded_chunk_ids':vector_excluded,'counts':{'changed_blocks':len(set(block_changed)&oldids),'changed_block_records_old_and_new':len(block_changed),'changed_offsets_blocks':len(offset_changed),'changed_roles':len(role_changed),'sections_changed':len(changedsec),'chunks_changed':len(changedchunk),'old_chunks':len(old.chunks),'new_chunks':len(chunks),'new_chunk_word_counts_by_kind':{kind:short_distribution([c.word_count for c in chunks if c.kind==kind]) for kind in sorted({c.kind for c in chunks})},'citable_words_before':sum(len(e.block.text.split()) for e in old.elements if e.citable),'citable_words_after':sum(len(e.block.text.split()) for e in elements if e.citable)},'section_collision_prediction':failure if failure and 'DUPLICATE_SECTION_ID' in failure else 'none','prediction_failure':failure,'limits':'In-memory structural projection. Text/route changes discard stale numeric/source ledgers; not an accepted DocumentStructure. No regional OCR content guessed.'}
        all_after[key]={'elements':elements,'chunks':chunks}
    frozen={t:[] for t in ('T0','T1','T2','T3')};details=[]
    for q in questions:
        old=sources[q['source']]['document'];after=all_after[q['source']];elements=after.elements if isinstance(after,DocumentStructure) else after['elements'];chunks=after.chunks if isinstance(after,DocumentStructure) else after['chunks'];newby={e.block.block_id:e for e in elements};spans=q['target_spans']
        identity=all(s['block_id'] in newby and s['end']<=len(newby[s['block_id']].block.text) and newby[s['block_id']].block.text[s['start']:s['end']]==next(e.block.text for e in old.elements if e.block.block_id==s['block_id'])[s['start']:s['end']] for s in spans)
        citable=all(s['block_id'] in newby and newby[s['block_id']].citable for s in spans)
        def relevant(cs):
            return sorted(c.chunk_id for c in cs if spans and all(any(p.block_id==s['block_id'] and p.start<=s['start'] and p.end>=s['end'] for p in c.primary) for s in spans))
        oldsets=relevant(old.chunks);assert oldsets==q['relevant_chunk_ids'], 'BASELINE_D1_LOCATOR_MISMATCH:'+q['id']
        if oldsets and results[q['source']].get('counts',{}).get('chunks_changed'):
            newsets,_=locate(SimpleNamespace(chunks=chunks),q['target_text'])
        else:newsets=relevant(chunks)
        t=target_class(identity,citable,oldsets==newsets)
        frozen[t].append(q['id']);details.append({'question_id':q['id'],'class':t,'old_D1_covering_chunks':oldsets,'new_D1_covering_chunks':newsets,'original_stored_relevant_chunks':q['relevant_chunk_ids']})
    return {'candidate':name,'mode':mode,'definition':DEFINITIONS['TARGET-BREAKING' if mode in ('healthy_digital','spacing_join','split_gutter','geometry_spacing') else 'TARGET-PRESERVING'],'classification':'BREAKING' if mode in ('healthy_digital','spacing_join','split_gutter','geometry_spacing') else 'PRESERVING','sources':results,'frozen':{'counts':{t:len(v) for t,v in frozen.items()},'ids':frozen,'per_question':details},'retire_if_T2':bool(frozen['T2']),'frozen_targets_in_vector_excluded_chunks':[q['id'] for q in questions if set(q['relevant_chunk_ids'])&set(results[q['source']].get('vector_excluded_chunk_ids',[]))]}


def inspect_objects(sources,cohorts):
    import pdfplumber
    import pypdfium2 as pdfium
    from PIL import Image,ImageDraw
    registry=read('eval/registry.json')['documents'];pdfs={r['doc_id']:(Path('eval')/r['file'],r['sha256']) for r in registry if r['doc_id'] in (*DEV,WEF)}
    requests=defaultdict(lambda:defaultdict(set));crops=[];objects={};page_log=[]
    def request(key,page,reason):requests[key][page].add(reason)
    for key,src in sources.items():
        if key not in pdfs:continue
        by={e.block.block_id:e for e in src['document'].elements}
        for bid in cohorts[key]['spaced']:request(key,by[bid].block.page_index,'Item4 spaced-run objects and tolerance comparison')
        for bid in cohorts[key]['mono_footnotes']:request(key,by[bid].block.page_index,'Item6 monospace/code/line-number objects')
        for bid in table_ids(src['document']) if key in DEV else cohorts[key]['chart_sample']:request(key,by[bid].block.page_index,'Item1 table/figure drawing precedence and candidate guard crop')
        for page in cohorts[key]['mixed_pages']:request(key,page,'Item2 explicit mixed-route image objects')
        short=[c for c in src['document'].chunks if c.word_count<10]
        for c in random.Random(20261012).sample(sorted(short,key=lambda c:c.chunk_id),min(4,len(short))):
            for span in c.primary:request(key,by[span.block_id].block.page_index,'Item7 seeded tiny chunk crop')
        if key==DEV[0]:
            for c in src['document'].chunks:
                if c.kind=='footnote' and any(by[s.block_id].block.page_index<10 for s in c.primary):
                    for span in c.primary:request(key,by[span.block_id].block.page_index,'Item6 six real early footnote chunks guard')
        if key==WEF:
            for page in PROFILE:request(key,page,'Items3/5 all18 narrative-profile continuation pages')
            for page in (100,101,102,103,104,105):request(key,page,'Item3 synthetic TA B L E A 3 opening mechanism')
    ratio_signature=str(inspect.signature(pdfplumber.utils.text.WordExtractor));experiment=[]
    for key in sorted(requests):
        path,expected=pdfs[key];actual=hashlib.sha256(path.read_bytes()).hexdigest();assert actual==expected;INPUTS[str(path)]=actual
        with pdfplumber.open(path) as pdf:
            renderer=pdfium.PdfDocument(str(path))
            for page in sorted(requests[key]):
                p=pdf.pages[page];chars=p.chars;fonts=Counter(c['fontname'] for c in chars);images=[{'bbox':[i['x0'],i['top'],i['x1'],i['bottom']],'width':i.get('srcsize',[None,None])[0],'height':i.get('srcsize',[None,None])[1]} for i in p.images]
                # Record native objects with stable local ordinal, geometry, font and exact glyphs.
                items=[{'object_id':i,'text':c['text'],'bbox':[c['x0'],c['top'],c['x1'],c['bottom']],'fontname':c['fontname'],'size':c['size'],'advance':c.get('adv'),'matrix':list(c.get('matrix',[]))} for i,c in enumerate(chars)]
                from pdfminer.pdfinterp import PDFContentParser
                from pdfminer.psparser import PSKeyword, keyword_name, PSEOF
                parser=PDFContentParser(p.page_obj.contents); operands=[]; text_operators=[]
                while True:
                    try: _,token=parser.nextobject()
                    except PSEOF: break
                    if isinstance(token,PSKeyword):
                        op=keyword_name(token)
                        if op in ('Tc','Tw','Tj','TJ'):
                            def plain(v):
                                return v.decode('latin1') if isinstance(v,bytes) else [plain(x) for x in v] if isinstance(v,list) else v if isinstance(v,(str,int,float,bool,type(None))) else str(v)
                            text_operators.append({'operator':op,'operands':[plain(x) for x in operands]})
                        operands=[]
                    else: operands.append(token)
                objects[f'{key}/{page}']={'text_operators':text_operators,'chars':items,'fontname_distribution':dict(fonts),'images':images,'rects':[{'bbox':[r['x0'],r['top'],r['x1'],r['bottom']],'fill':r.get('fill'),'stroke':r.get('stroke')} for r in p.rects],'lines':[{'bbox':[r['x0'],r['top'],r['x1'],r['bottom']]} for r in p.lines],'curve_count':len(p.curves),'curves':[{'object_id':i,'bbox':[c['x0'],c['top'],c['x1'],c['bottom']],'points':c.get('pts'),'path':c.get('path'),'fill':c.get('fill'),'stroke':c.get('stroke')} for i,c in enumerate(p.curves)],'dimensions':[p.width,p.height]}
                native=renderer[page];bitmap=native.render(scale=1.5);im=bitmap.to_pil().convert('RGB')
                file=OUT/'crops'/f'{key}-p{page:04d}.png';file.parent.mkdir(parents=True,exist_ok=True);im.save(file)
                crops.append({'source':key,'pdf_page_index':page,'bbox':[0,0,p.width,p.height],'scale_px_per_pt':1.5,'path':str(file),'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'reasons':sorted(requests[key][page])})
                print('INSPECT',key,page,flush=True)
                page_log.append({'source':key,'path':str(path),'pdf_page_index':page,'reasons':sorted(requests[key][page]),'objects':'pdfplumber chars/rects/lines/images; pypdfium2 native render','source_sha256':actual})
                # Compare exact spans only, in memory; our reader does not call extract_words.
                by={e.block.block_id:e for e in sources[key]['document'].elements}
                for bid in sorted(cohorts[key]['spaced']):
                    e=by[bid]
                    if e.block.page_index!=page:continue
                    x0,y0,x1,y1=e.block.bbox;inside_chars=[c for c in chars if x0-.5<=c['x0'] and c['x1']<=x1+.5 and y0-.5<=c['top'] and c['bottom']<=y1+.5]
                    output={}
                    for ratio in (None,.1,.2,.3,.5):
                        words=pdfplumber.utils.extract_words(inside_chars,x_tolerance=3,x_tolerance_ratio=ratio,extra_attrs=['fontname','size'])
                        output[str(ratio)]=[w['text'] for w in words]
                    experiment.append({'source':key,'block_id':bid,'pdf_page_index':page,'bbox':list(e.block.bbox),'runs':[m.group() for m in SPACED.finditer(e.block.text)],'literal_space_glyphs':sum(c['text'].isspace() for c in inside_chars),'char_ids':[i for i,c in enumerate(chars) if c in inside_chars],'word_tolerances':output,'limits':'Whole block crop; no word count can establish the intended lexical joining. Explicit space glyphs remain delimiters at all ratios.'})
                bitmap.close();native.close();p.close()
            renderer.close()
    # Native contact sheets for review, not a substitute for object inventory.
    for key in pdfs:
        selected=[r for r in crops if r['source']==key]
        for batch in range((len(selected)+7)//8):
            rows=selected[batch*8:batch*8+8];sheet=Image.new('RGB',(1200,1700),'white');draw=ImageDraw.Draw(sheet)
            for i,r in enumerate(rows):
                im=Image.open(r['path']);im.thumbnail((285,795));x=(i%4)*300;y=(i//4)*850;sheet.paste(im,(x,y+30));draw.text((x+4,y+5),f"{key} PDF {r['pdf_page_index']}",fill='black')
            sheet.save(OUT/'crops'/f'sheet-{key}-{batch}.png')
    emit('objects.json',objects);emit('crops-manifest.json',crops);emit('inspected-pages.json',page_log)
    return {'pdfplumber_version':pdfplumber.__version__,'installed_WordExtractor_signature':ratio_signature,'supports_x_tolerance_ratio':'x_tolerance_ratio' in ratio_signature,'reader_uses':'custom _words_from_chars; gap_em threshold, not extract_words; explicit spaces break except numeric_bridge','reader_reference':'matn_reading/pdf_page.py:275','experiments':experiment},objects,crops



def enrich_spacing(spacing,objects):
    import unicodedata
    for row in spacing['experiments']:
        native=objects[f"{row['source']}/{row['pdf_page_index']}"]['chars']
        ids=set(row['char_ids']);lines=defaultdict(list)
        for c in native:
            if c['object_id'] in ids:lines[round(c['bbox'][3],1)].append(c)
        evidence=[]
        for run in row['runs']:
            needle=run.replace(' ','');matches=[]
            for chars in lines.values():
                chars=sorted(chars,key=lambda c:(c['bbox'][0],c['object_id']));compact='';mapping=[]
                for i,c in enumerate(chars):
                    text=unicodedata.normalize('NFKC',c['text'])
                    for ch in text:
                        if not ch.isspace():compact+=ch;mapping.append(i)
                start=0
                while True:
                    at=compact.find(needle,start)
                    if at<0:break
                    a=mapping[at];z=mapping[at+len(needle)-1]+1;selected=chars[a:z];visible=[c for c in selected if not c['text'].isspace()]
                    gaps=[{'left_char_id':l['object_id'],'right_char_id':r['object_id'],'gap_pt':r['bbox'][0]-l['bbox'][2],'gap_em':(r['bbox'][0]-l['bbox'][2])/max(l['size'],r['size']),'literal_space_between':any(c['text'].isspace() for c in selected[selected.index(l)+1:selected.index(r)])} for l,r in zip(visible,visible[1:])]
                    matches.append({'char_ids':[c['object_id'] for c in selected],'native_text':''.join(c['text'] for c in selected),'literal_space_glyphs_in_run':sum(c['text'].isspace() for c in selected),'gaps':gaps,'split_gaps_over_current_0_1_em':sum(g['gap_em']>.1 and not g['literal_space_between'] for g in gaps)})
                    start=at+1
            evidence.append({'cached_run':run,'native_sequence_matches':matches,'attribution':'unresolved' if not matches else 'ambiguous_multiple_native_sequences' if len(matches)>1 else 'literal_word_spaces_plus_tracking_gaps' if matches[0]['literal_space_glyphs_in_run'] and matches[0]['split_gaps_over_current_0_1_em'] else 'literal_space_glyphs' if matches[0]['literal_space_glyphs_in_run'] else 'glyph_gaps_custom_segmentation' if matches[0]['split_gaps_over_current_0_1_em'] else 'OCR_or_other_layout_split_not_explained_by_gap_threshold'})
        row['exact_run_native_evidence']=evidence
    spacing['attribution_counts']=dict(Counter(e['attribution'] for row in spacing['experiments'] for e in row['exact_run_native_evidence']))
    spacing['limits']='Exact glyph-sequence matches and gaps; whole-block ordinary spaces are not attributed to letter spacing. Content operators record Tc/Tj/TJ; glyph gaps include positioning and tracking; OCR-generated runs may not match PDF text.'
    return spacing



def geometry_spacing_projection(sources,cohorts,objects):
    result={}
    for key,source in sources.items():
        texts={};by={e.block.block_id:e for e in source['document'].elements};records=raw_records(source);pages={p['page_index']:p for p in source['snapshot']['pages']}
        for bid in sorted(cohorts[key]['spaced']):
            e=by[bid];page=pages[e.block.page_index]
            if page.get('ocr'):continue
            native=objects[f'{key}/{e.block.page_index}']['chars'];record=copy.deepcopy(records[bid])
            for line in record['lines']:
                merged=[]
                for w in line['words']:
                    if merged:
                        left=merged[-1];gap=w['bbox'][0]-left['bbox'][2];em=max(w['size'],left['size'])
                        alnum=re.fullmatch(r'[A-Z0-9]+',left['text']) and re.fullmatch(r'[A-Z0-9]+',w['text'])
                        spaces=any(c['text'].isspace() and left['bbox'][2]-.01<=(c['bbox'][0]+c['bbox'][2])/2<=w['bbox'][0]+.01 and min(w['bbox'][1],left['bbox'][1])-.5<=(c['bbox'][1]+c['bbox'][3])/2<=max(w['bbox'][3],left['bbox'][3])+.5 for c in native)
                        if alnum and 0<=gap<=.2*em and not spaces:
                            left['text']+=w['text'];left['bbox']=[min(left['bbox'][0],w['bbox'][0]),min(left['bbox'][1],w['bbox'][1]),max(left['bbox'][2],w['bbox'][2]),max(left['bbox'][3],w['bbox'][3])];continue
                    merged.append(w)
                line['words']=merged
            text,_,_=word_ledger(record,digital=True)
            if text!=e.block.text:texts[bid]=text
        result[key]=texts
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with block_egress():
        identity_main()
        sources=load_sources();cohorts=transforms(sources);questions=read('eval/rag/frozen/questions.json')['items']
        m=read('out/rag-core/mixed-route/measurement.json');scope={'all14':scope_counts(m['pages']),'mixed13':scope_counts(m['pages'],True),'cover0':m['pages'][0]['word_counts'],'cover0_digital_words':m['pages'][0]['digital_words'],'page85_17_to_7':[x for p in m['pages'] if p['pdf_page_index']==85 for x in p['every_numeric_token'] if x.get('digital') and x.get('ocr') and x['digital']['value']=='17' and x['ocr']['value']=='7']}
        assert scope['all14']['matched_numbers']==214 and scope['all14']['disposition_moves']=={'digital->accepted':167,'digital->flagged':47} and not scope['all14']['accepted_value_disagreements'] and len(scope['page85_17_to_7'])==1
        emit('mixed-route-scopes.json',scope)
        quality=read('out/rag-core/wef-quality/diagnosis.json');vector=read('out/rag-core/vector-diagnosis/diagnosis.json')
        assert quality['metrics']['pages']==290 and len(sources[WEF]['snapshot']['outline'])==0 and quality['metrics']['sections']=={'layout_heading':488}
        assert quality['metrics']['chunks']=={'body':463,'table':233,'caption':7} and quality['metrics']['body_words']['min']==1 and quality['metrics']['body_words']['median']==19
        assert quality['citable_primary_words_by_chunk_kind']=={'body':28439,'table':79591,'caption':337}
        assert len(quality['letter_spaced_token_occurrences'])==74 and sum('TA B L E' in e.block.text for e in sources[WEF]['document'].elements)==19
        assert vector['D']['footnotes']['count']==137 and vector['D']['footnotes']['by_10_page_range']=={'0-9':6,'20-29':46,'30-39':73,'40-49':12}
        assert Counter(c.kind for key in DEV for c in sources[key]['document'].chunks)=={'body':427,'caption':151,'footnote':338,'table':59}
        candidate_modes=[('I1-labelled-chart-exclusion','sample_chart'),('I1-WEF-table-quarantine','quarantine_wef_tables'),('I1-all-source-table-quarantine-guard','quarantine_all_tables'),('I2-saved-healthy-digital-lower-bound','healthy_digital'),('I3-profile-heading-demotion','heading_demote'),('I4-join-uppercase-spaced-runs','spacing_join'),('I4-search-input-spacing-normalization','search_spacing'),('I5-one-body-block-per-chunk-on18pages','block_chunks'),('I6-monospace-footnote-to-text','mono_retype'),('I6-bare-monospace-gutter-exclusion','bare_exclude'),('I6-regular-line-number-gutter-exclusion','regular_gutter'),('I5-split-mixed-OCR-blocks-at-observed-gutter','split_gutter'),('I7-merge-tiny-same-section-kind','merge_tiny'),('I7-vector-exclude-under10','vector_short'),('producer-version-r-lite-3-migration','producer_version_migration'),('all-items-report-only','report_only')]
        predictions=[]
        for name,mode in candidate_modes:
            print('PREDICT',name,flush=True)
            predictions.append(predict(sources,cohorts,questions,name,mode))
        emit('predictions.json',{'seed':20261012,'definitions':DEFINITIONS,'limits':'Candidate cohorts are finite counterfactuals for decisions, not approved production rules; no retrieval gain claimed. Profile scope is explicit18pages; spacing join only upper-case runs; mono signals require font observations.','candidates':predictions})
        spacing,objects,crops=inspect_objects(sources,cohorts)
        spacing=enrich_spacing(spacing,objects)
        overrides=geometry_spacing_projection(sources,cohorts,objects)
        spacing['geometry_guided_word_join_texts']=overrides
        spacing['geometry_projection_limits']='Only digital cached uppercase tracking cohorts; relative0.2em with explicit native space guard; OCR blocks excluded. Evaluation projection, not a global threshold recommendation.'
        predictions.append(predict(sources,cohorts,questions,'I4-geometry-guarded-tracked-word-join','geometry_spacing',overrides))
        emit('predictions.json',{'seed':20261012,'definitions':DEFINITIONS,'limits':'Finite source cohorts, pure in-memory projections; producer-version migration is a separate overlay, not combined with fixes. No retrieval gain claimed.','candidates':predictions})
        fonts=[];short={};mixed=[];profile=[];headings=[];table=[]
        for key,source in sources.items():
            doc=source['document'];raw=raw_records(source);by={e.block.block_id:e for e in doc.elements}
            short[key]={kind:short_distribution([c.word_count for c in doc.chunks if c.kind==kind]) for kind in sorted({c.kind for c in doc.chunks})}
            for c in doc.chunks:
                if c.kind=='footnote':
                    f=Counter(w.get('font_face','') for s in c.primary for line in raw[s.block_id]['lines'] for w in line['words'])
                    fonts.append({'source':key,'chunk_id':c.chunk_id,'word_count':c.word_count,'pages':sorted({by[s.block_id].block.page_index for s in c.primary}),'fonts':dict(f),'primary_block_ids':[s.block_id for s in c.primary],'text':c.text})
            for p in source['snapshot']['pages']:
                if p['route']=='mixed':mixed.append({'source':key,'pdf_page_index':p['page_index'],'route':p['route'],'reasons':p['reasons'],'native_images':objects.get(f"{key}/{p['page_index']}",{}).get('images'),'source_block_ids':[r['block']['block_id'] for r in p['blocks']],'digital_layer_health':'mixed is reached only after broken glyph/0.97 agreement tests PASS; not accuracy proof; original reasons record rounded signals'})
            for s in doc.sections:
                headings.append({'source':key,'section_id':s.section_id,'heading_source':s.source,'heading_block_id':s.heading_block_id,'synthetic_opening':any(i.reason=='synthetic_opening' for i in s.issues),'page_range':list(s.page_range),'title':s.title,'block_ids':list(s.block_ids)})
            for bid in sorted(table_ids(doc)):
                e=by[bid];table.append({'source':key,'block_id':bid,'pdf_page_index':e.block.page_index,'bbox':list(e.block.bbox),'text':e.block.text,'native_objects_available':f'{key}/{e.block.page_index}' in objects,'sample_chart_selected':bid in cohorts[key]['chart_sample']})
        for page in PROFILE:
            doc=sources[WEF]['document'];es=[e for e in doc.elements if e.citable and e.block.page_index==page];by={e.block.block_id:e for e in doc.elements}
            cs=[c for c in doc.chunks if any(by[s.block_id].block.page_index==page for s in c.primary)]
            profile.append({'pdf_page_index':page,'crop':next(r['path'] for r in crops if r['source']==WEF and r['pdf_page_index']==page),'blocks':[{'block_id':e.block.block_id,'role':e.role,'bbox':list(e.block.bbox),'text':e.block.text} for e in es],'chunks':[{'chunk_id':c.chunk_id,'block_ids':list(dict.fromkeys(s.block_id for s in c.primary)),'text':c.text} for c in cs],'wide_mixed_block_ids':[e.block.block_id for e in es if page in cohorts[WEF]['mixed_pages'] and e.role=='text' and e.block.bbox[0]<345 and e.block.bbox[2]>358], 'visual_judgment':'Codex: native reviewed examples70/84/85 separate blocks can share chunks; native65/66/74/87 also have OCR blocks interleaving left/right paragraphs. Other pages enumerated; a mention of multiple countries in regional prose is not itself entity mixing.'})
        emit('item1-tables.json',{'blocks':table,'seeded_annotation_counts':read('eval/rag/dev-table-visual-annotations-20261012.json')['counts'],'mechanism_refs':['matn_reading/classify.py:122','matn_reading/read.py:144','matn_reading/read.py:156'],'limits':'Chart-labelled candidate covers source blocks in exactly20 annotated chunks; WEF table quarantine is intentionally overbroad, not a chart recovery heuristic.'})
        emit('item2-mixed.json',{'scopes':scope,'mixed_pages':mixed,'alignments_by_page':[{k:v for k,v in p.items() if k not in ('alignment','every_numeric_token','raw_ocr_reader_tokens')} for p in m['pages']],'numbers_policy':'Keep all non-digital mixed-page numbers unverified until source/scope decision; flagged never verified. Healthy digital comparison is conditional, not evidence of population accuracy.','image_alignment_observations':[{ 'pdf_page_index':p['pdf_page_index'], 'OCR_insertion_word_positions':{'inside_raster':sum(any(im['bbox'][0]<=(x['ocr']['bbox'][0]+x['ocr']['bbox'][2])/2<=im['bbox'][2] and im['bbox'][1]<=(x['ocr']['bbox'][1]+x['ocr']['bbox'][3])/2<=im['bbox'][3] for im in objects.get(f"{WEF}/{p['pdf_page_index']}",{}).get('images',[])) for x in p['alignment'] if x['operation']=='insertion'),'total_insertions':p['word_counts'].get('insertion',0)},'limits':'Alignment insertions are not novel-content or OCR accuracy evidence'} for p in m['pages'] if p['pdf_page_index']!=0], 'regional_OCR_prediction':'not performed; saved digital lower-bound only; unknown raster additions are not fabricated'})
        emit('item3-headings.json',{'cached_word_font_modes':{key:dict(Counter({size:sum(len(w['text']) for p in src['snapshot']['pages'] for r in p['blocks'] for line in r['lines'] for w in line['words'] if w.get('size') is not None and round(w['size']*2)/2==size) for size in sorted({round(w['size']*2)/2 for p in src['snapshot']['pages'] for r in p['blocks'] for line in r['lines'] for w in line['words'] if w.get('size') is not None})})) for key,src in sources.items()},'sections':headings,'counts_by_source_heading_source':{key:dict(Counter(s.source for s in src['document'].sections)) for key,src in sources.items()},'mechanism_refs':['matn_reading/classify.py:139','matn_reading/structure/sections.py:40','matn_reading/structure/chunks.py:40'],'synthetic_opening_policy':'section-identity-v2 preserved; no ID collision bypass'})
        emit('item4-spacing.json',spacing);emit('item5-profile-entities.json',profile)
        emit('item6-footnotes.json',{'chunks':fonts,'cohorts':{key:{'mono_footnote_block_ids':sorted(cohorts[key]['mono_footnotes']),'bare_gutter_block_ids':sorted(cohorts[key]['bare_gutter']),'regular_gutter_block_ids':sorted(cohorts[key]['regular_gutter'])} for key in sources},'early_arxiv_chunks':[r for r in fonts if r['source']==DEV[0] and max(r['pages'])<10], 'font_distribution_arxiv_all137':dict(sum((Counter(r['fonts']) for r in fonts if r['source']==DEV[0]),Counter())), 'font_distribution_arxiv_early6':dict(sum((Counter(r['fonts']) for r in fonts if r['source']==DEV[0] and max(r['pages'])<10),Counter())), 'regular_gutter_positions':[{'block_id':e.block.block_id,'page_index':e.block.page_index,'bbox':list(e.block.bbox),'text':e.block.text} for e in sources[DEV[0]]['document'].elements if e.block.block_id in cohorts[DEV[0]]['regular_gutter']], 'all_cached_monospace_blocks':{key:[bid for bid,r in raw_records(src).items() if any(MONO.search(w.get('font_face','')) for line in r['lines'] for w in line['words'])] for key,src in sources.items()},'mechanism_refs':['matn_reading/classify.py:148','matn_reading/read.py:179','matn_reading/pdf_page.py:298'],'limits':'mono font presence is a candidate signal; regular gutter also needs object x positions; no new Code enum in this session'})
        emit('item7-short-chunks.json',{'distribution':short,'short_chunks':{key:[{'chunk_id':c.chunk_id,'kind':c.kind,'word_count':c.word_count,'section_id':c.section_id,'block_ids':[s.block_id for s in c.primary]} for c in src['document'].chunks if c.word_count<10] for key,src in sources.items()},'mechanism':'tiny50 applies only same body batch final remainder; kind/section boundaries flush; captions and footnotes emitted per block','hypothesis':'Tiny-chunk hubness association is descriptive; no retrieval gain claimed'})
        # Write explicit P1-G derived route evidence with same source metadata, without inferring routes.
        root=Path('out/rag-core/wef-first-run/approved-acquisition'); spath=Path(sources[WEF]['snapshot_path'])
        route_sources=[]; rows=[{'pdf_page_index':p['page_index'],'route':p['route']} for p in sources[WEF]['snapshot']['pages']]
        canonical_routes={p['pdf_page_index']:p['route'] for p in rows}
        for path,field in [(spath,'$.pages[*].route'),(root/'digital_read.json','$.pages[*].route'),(root/'routes-before-ocr.json','$[*].route')]:
            obj=read(path); records=obj['pages'] if isinstance(obj,dict) else obj
            other={p.get('page_index',p.get('pdf_page_index')):p['route'] for p in records}
            assert all(canonical_routes[i]==route for i,route in other.items())
            route_sources.append({'path':str(path),'sha256':INPUTS[str(path)],'field_path':field,'records':len(other),'counts':dict(Counter(other.values()))})
        emit('wef-routes.json',{'status':'PASS','source_field_paths':['$.pages[*].page_index','$.pages[*].route'],'example':rows[0],'sources':route_sources,'search_findings':{'acquisition-manifest.json':'no route values/counts; OCR index set agrees','reports/rag-core-wef-stop-evidence.json':'none found','reports/rag-core-wef-first-run.md':'line 56: 276 digital_healthy/13 mixed/1 scanned; agrees'},'counts':dict(Counter(canonical_routes.values())),'ocr_routed_indices':sorted(i for i,r in canonical_routes.items() if r in ('mixed','scanned')),'pages':rows})
        emit('carried-fact-stop.json',{'status':'RESOLVED_BY_P1H_SCOPE_CORRECTION','source':'out/rag-core/mixed-route/measurement.json','source_sha256':INPUTS['out/rag-core/mixed-route/measurement.json'],'field_paths':['$.pages[*].pdf_page_index','$.pages[*].word_counts'],'counts':{'all_14_OCR_pages':scope['all14']['alignment'],'mixed_13_pages':scope['mixed13']['alignment']},'scanned_page_0_counts':scope['cover0'],'spec_claim':'3027/120/1694/1633 attributed to 13 mixed pages; actually totals all14 including scanned0','item_0_block_identity':'PASS; no mismatches','items_1_7':'Historical stop resolved by P1-H; see current plan'})
        import sys
        for module in list(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename:
                path=Path(filename).resolve()
                try:relative=path.relative_to(Path.cwd())
                except ValueError:continue
                if path.suffix=='.py' and not str(relative).startswith('.venv/'):
                    INPUTS[str(relative)]=hashlib.sha256(path.read_bytes()).hexdigest()
        for path in ('eval/reading/thresholds.json','eval/rag/function_words.json','matn_reading/rules/ocr.json'):
            if Path(path).is_file():INPUTS[path]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
        emit('diagnostic-input-hashes.json',INPUTS)
        print('CANDIDATES',[(p['candidate'],p['frozen']['counts']) for p in predictions]);print('INSPECTED_PAGES',len(objects));print('PREDICTION_FAILURES',[(p['candidate'],k,r['prediction_failure']) for p in predictions for k,r in p['sources'].items() if r.get('prediction_failure')])


if __name__=='__main__':main()
