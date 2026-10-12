"""In-memory projections and exact frozen D1 audit; never writes production structures."""
from collections import defaultdict
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from eval.rag import r_lite_3_part1 as prior
from matn_contracts.domain import Block
from matn_reading.structure.sections import build_sections
from matn_reading.structure.chunks import build_chunks

OUT=Path('out/r-lite-3/part2c')


def emit(name,data):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(json.dumps(data,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def project(sources, changes, questions, name):
    all_after={};rows={};remaps=[]
    for key,src in sources.items():
        old=src['document'];change=changes.get(key,{});code=set(change.get('code_block_ids',[]));excluded=set(change.get('excluded_gutter_block_ids',[]));texts=change.get('texts',{})
        snap=copy.deepcopy(src['snapshot']);records=prior.raw_records(src);elements=[];idmap={}
        for e in old.elements:
            bid=e.block.block_id;updates={}
            if bid in code:updates['role']='text'
            if bid in excluded:updates.update(citable=False,exclusion_reasons=('regular_line_number_gutter',))
            if bid in texts:
                data=e.block.model_dump(mode='json');data['text']=texts[bid];data['block_id']=prior.recompute_block(data)
                block=Block.model_validate(data);idmap[bid]=block.block_id
                updates.update(block=block,source_spans=(),number_tokens=())
                remaps.append({'source':key,'old_block_id':bid,'new_block_id':block.block_id,
                               'normalization':'M4-native-space-guarded-tracking-v1',
                               'old_text':e.block.text,'new_text':block.text,
                               'offset_remap':change['offset_remaps'][bid],
                               'provenance_remap_required':'rebuild source/number references; removed only synthetic join spaces; not accepted structure'})
            elements.append(e.model_copy(update=updates))
        for p in snap['pages']:
            for r in p['blocks']:
                bid=r['block']['block_id']
                if bid in code:
                    r['block']['block_type']='text'
                    # Existing reader representation: page.flags, not a Block contract field.
                    p['flags'].append({'kind':'code_text','bbox':r['block']['bbox'],'chars':len(r['block']['text'])})
                if bid in texts:r['block']['text']=texts[bid];r['block']['block_id']=idmap[bid]
        failure=None
        try:
            if code or excluded or texts:
                # Preserve original reader-role section eligibility on unchanged blocks.
                eligible=[e.model_copy(update={'role':records[e.block.block_id]['block']['block_type']})
                          if e.block.block_id in records and e.block.block_id not in code and e.block.block_id not in excluded else e for e in elements]
                sections,issues=build_sections(snap,eligible)
                demoted={i.block_id for i in issues if i.reason=='heading_demoted'}
                elements=[e.model_copy(update={'role':'text'}) if e.block.block_id in demoted else e for e in elements]
                table_ids={e.block.block_id for e in elements if e.citable and e.role=='table'}
                tables=[t for t in old.tables if set(t.block_ids)<=table_ids]
                chunks=build_chunks(snap,elements,sections,tables)
                lengths={e.block.block_id:len(e.block.text) for e in elements if e.citable and e.block.text};covered=defaultdict(list)
                for c in chunks:
                    for s in c.primary:covered[s.block_id].append((s.start,s.end))
                for bid,n in lengths.items():
                    cursor=0
                    for a,b in sorted(covered[bid]):
                        assert a==cursor, 'PRIMARY_COVERAGE_GAP_OR_OVERLAP';cursor=b
                    assert cursor==n,'PRIMARY_COVERAGE_INCOMPLETE'
            else:sections=old.sections;chunks=old.chunks
        except (ValueError,AssertionError) as exc:
            failure=str(exc);sections=old.sections;chunks=old.chunks
        newby={e.block.block_id:e for e in elements};oldby={e.block.block_id:e for e in old.elements}
        changed=[bid for bid,e in oldby.items() if bid not in newby or e.model_dump(mode='json')!=newby[bid].model_dump(mode='json')]
        rows[key]={'changed_block_ids':sorted(changed),'code_flag_block_ids':sorted(code),
                   'excluded_gutter_block_ids':sorted(excluded),'text_changed_block_ids':sorted(texts),
                   'prediction_failure':failure,'old_chunks':len(old.chunks),'new_chunks':len(chunks),
                   'chunk_distribution':{kind:prior.short_distribution([c.word_count for c in chunks if c.kind==kind]) for kind in sorted({c.kind for c in chunks})},
                   'changed_chunk_ids':sorted(set(c.chunk_id for c in old.chunks)^set(c.chunk_id for c in chunks)),
                   'code_flag_representation':'page.flags[kind=code_text] in projection snapshot',
                   'section_collisions':failure if failure and 'DUPLICATE_SECTION_ID' in failure else None}
        all_after[key]=SimpleNamespace(elements=elements,chunks=chunks)
    counts={t:0 for t in ('T0','T1','T2','T3')};details=[]
    for q in questions:
        old=sources[q['source']]['document'];new=all_after[q['source']];oldby={e.block.block_id:e for e in old.elements};newby={e.block.block_id:e for e in new.elements};spans=q['target_spans']
        identity=all(s['block_id'] in newby and s['end']<=len(newby[s['block_id']].block.text) and newby[s['block_id']].block.text[s['start']:s['end']]==oldby[s['block_id']].block.text[s['start']:s['end']] for s in spans)
        citable=all(s['block_id'] in newby and newby[s['block_id']].citable for s in spans)
        def covering(chunks):
            return sorted(c.chunk_id for c in chunks if spans and all(any(p.block_id==s['block_id'] and p.start<=s['start'] and p.end>=s['end'] for p in c.primary) for s in spans))
        before=covering(old.chunks);assert before==q['relevant_chunk_ids'],'BASELINE_LOCATOR_MISMATCH'
        after=covering(new.chunks);t=prior.target_class(identity,citable,before==after);counts[t]+=1
        details.append({'question_id':q['id'],'class':t,'old_covering_ids':before,'new_covering_ids':after,'unchanged_target_spans':spans})
    result={'name':name,'sources':rows,'frozen':{'counts':counts,'per_question':details},'remaps':remaps,
            'scope':'isolated in-memory design; no cached or production structure overwritten'}
    return result,all_after


def crops(sources, requests, stem):
    """Crop only from already SHA-recorded native renders; no new PDF access."""
    import hashlib
    from PIL import Image
    manifest=json.loads(Path('out/r-lite-3/part1/crops-manifest.json').read_text())
    native={(r['source'],r['pdf_page_index']):r for r in manifest};rows=[]
    for key,bid in sorted(set(requests)):
        block=next(e.block for e in sources[key]['document'].elements if e.block.block_id==bid)
        record=native.get((key,block.page_index))
        if record is None:raise ValueError('REQUIRED_NATIVE_CROP_NOT_CACHED:'+key+':'+bid)
        assert hashlib.sha256(Path(record['path']).read_bytes()).hexdigest()==record['sha256'],'NATIVE_RENDER_SHA_MISMATCH'
        with Image.open(record['path']) as im:
            scale=record['scale_px_per_pt'];x0,y0,x1,y1=block.bbox
            box=(max(0,int(x0*scale)),max(0,int(y0*scale)),min(im.width,int(x1*scale+1)),min(im.height,int(y1*scale+1)))
            path=OUT/'crops'/stem/key/(bid.rsplit(':',1)[-1]+'.png');path.parent.mkdir(parents=True,exist_ok=True);im.crop(box).save(path)
        rows.append({'source':key,'block_id':bid,'pdf_page_index':block.page_index,'bbox':list(block.bbox),'path':str(path),
                     'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'parent_render_path':record['path'],
                     'parent_render_sha256':record['sha256'],'scale_px_per_pt':scale})
    emit(stem+'-crops-manifest.json',rows)
    return rows


def m3():
    from eval.rag.r_lite_3_part2c_m3 import decisions
    sources=prior.load_sources();rule=json.loads(Path('eval/rag/r_lite_3_part2c_m3_rule.json').read_text())
    result={k:decisions(src,rule) for k,src in sources.items()};emit('m3-decisions.json',result)
    questions=json.loads(Path('eval/rag/frozen/questions.json').read_text())['items']
    projection,after=project(sources,result,questions,rule['name']);emit('m3-projection.json',projection)
    ar=sources[prior.DEV[0]]['document'];by={e.block.block_id:e for e in ar.elements}
    early=[c for c in ar.chunks if c.kind=='footnote' and all(by[s.block_id].block.page_index<10 for s in c.primary)]
    newby={e.block.block_id:e for e in after[prior.DEV[0]].elements}
    early_rows=[{'chunk_id':c.chunk_id,'block_ids':sorted({s.block_id for s in c.primary}),
                 'unchanged':all(by[s.block_id].model_dump(mode='json')==newby[s.block_id].model_dump(mode='json') and s.block_id not in result[prior.DEV[0]]['code_block_ids'] for s in c.primary)} for c in early]
    markers=[]
    for k,src in sources.items():
        newby={e.block.block_id:e for e in after[k].elements}
        for e in src['document'].elements:
            if '+' in e.block.text or '-' in e.block.text:
                n=newby[e.block.block_id]
                markers.append({'source':k,'block_id':e.block.block_id,'text_exact':e.block.text==n.block.text,
                                'plus_before':e.block.text.count('+'),'minus_before':e.block.text.count('-'),
                                'plus_after':n.block.text.count('+'),'minus_after':n.block.text.count('-'),
                                'citable_preserved':not e.citable or n.citable})
    requests={(k,b) for k,r in projection['sources'].items() if k!=prior.DEV[0] for b in r['changed_block_ids']}
    cropped=crops(sources,requests,'m3')
    failure=[k for k,r in projection['sources'].items() if r['prediction_failure']]
    passed=len(early)==6 and all(r['unchanged'] for r in early_rows) and all(r['text_exact'] and r['citable_preserved'] for r in markers) and not failure and not projection['frozen']['counts']['T2'] and not projection['frozen']['counts']['T3']
    gates={'status':'PASS' if passed else 'STOP_M3_GATE_FAILURE','six_early_footnotes':early_rows,'early_count':len(early),
           'every_plus_minus_retained':all(r['text_exact'] and r['citable_preserved'] for r in markers),'marker_blocks':markers,
           'non_arxiv_changed_crop_count':len(cropped),'projection_failures':failure,'frozen':projection['frozen']['counts'],
           'arxiv_footnote_after':projection['sources'][prior.DEV[0]]['chunk_distribution'].get('footnote',prior.short_distribution([]))}
    emit('m3-gates.json',gates);print(json.dumps({k:v for k,v in gates.items() if k not in ('six_early_footnotes','marker_blocks')},sort_keys=True))
    if not passed:raise SystemExit(31)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('step',choices=['m3']);a=p.parse_args();m3()
