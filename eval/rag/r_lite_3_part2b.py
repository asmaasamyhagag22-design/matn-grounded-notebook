"""Main-venv JSON consumer for the precommitted eval-only Docling reference.

No Docling import or inference. All checks use saved label JSON in the owner order.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from eval.rag import r_lite_3_part1 as prior
from eval.rag.r_lite_3_part2b_mapping import convert_box,union_share,retype

OUT=Path('out/r-lite-3/part2b')
CONFIG=Path('eval/rag/r_lite_3_part2b_config.json')
CONFIG_COMMIT='0eb5651'
BASE='b0e4d61'
ANNOTATIONS=('eval/rag/wef-table-visual-annotations.json','eval/rag/dev-table-visual-annotations-20261012.json')
INPUTS={}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def read(path):
    path=Path(path);raw=path.read_bytes();INPUTS[str(path)]=sha(raw);return json.loads(raw)


def emit(name,data):
    OUT.mkdir(parents=True,exist_ok=True);(OUT/name).write_text(json.dumps(data,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n')


def sanity_match(box,text_regions):return max((union_share(box,[r]) for r in text_regions),default=0)>=0.5


def verify_initial():
    accepted=read('out/r-lite-3/part2a/final-evidence.json')
    expected=dict(accepted['protected_hashes']['before'])
    expected.pop('docs/REVIEWER_BRIEF.md',None)
    expected={k:v for k,v in expected.items() if k not in ANNOTATIONS}
    for p,v in expected.items():
        if sha(Path(p).read_bytes())!=v:raise ValueError('PROTECTED_INPUT_CHANGED:'+p)
    for p in (str(CONFIG),'eval/rag/r_lite_3_part2b_mapping.py'):
        if Path(p).read_bytes()!=subprocess.check_output(['git','show',CONFIG_COMMIT+':'+p]):raise ValueError('FIXED_CONFIGURATION_CHANGED:'+p)
    original=subprocess.check_output(['git','show',BASE+':docs/REVIEWER_BRIEF.md']);current=Path('docs/REVIEWER_BRIEF.md').read_bytes()
    if not current.startswith(original) or len(current[len(original):].decode().strip().splitlines())!=1:raise ValueError('DECISION_ROWS_CHANGED')
    INPUTS['docs/REVIEWER_BRIEF.md']=sha(current)
    return expected


def compare_labels(first, second):
    """Compare exact serialized results; expose raw changed pages, including confidence."""
    left=Path(first).read_bytes();right=Path(second).read_bytes()
    a=json.loads(left);b=json.loads(right)
    key=lambda r:(r['source'],r['pdf_page_index'])
    x={key(r):r for r in a['pages']};y={key(r):r for r in b['pages']}
    changed=[{'source':k[0],'pdf_page_index':k[1],'first':x.get(k),'second':y.get(k)} for k in sorted(x.keys()|y.keys()) if x.get(k)!=y.get(k)]
    return {'byte_equal':left==right,'first_sha256':sha(left),'second_sha256':sha(right),'changed_pages':changed,'metadata_equal':{k:v for k,v in a.items() if k!='pages'}=={k:v for k,v in b.items() if k!='pages'},'no_rounding_or_averaging':True}


def main():
    expected=verify_initial();cfg=read(CONFIG);sources=prior.load_sources();INPUTS.update(prior.INPUTS)
    labels=read(OUT/'labels-pass1.json')
    if labels['configuration_sha256']!=sha(CONFIG.read_bytes()):raise ValueError('LABEL_CONFIGURATION_MISMATCH')
    requested={(s['source'],i) for s in cfg['inputs'] for i in s['pages']}
    actual={(p['source'],p['pdf_page_index']) for p in labels['pages']}
    if actual!=requested or labels['status']!='COMPLETE':raise ValueError('REFERENCE_LABELS_INCOMPLETE')
    by_page={}
    for p in labels['pages']:
        source=sources[p['source']];page=next(q for q in source['snapshot']['pages'] if q['page_index']==p['pdf_page_index'])
        regions=[{'id':r['id'],'label':r['label'],'bbox':convert_box(r['bbox'],p['docling_page_size'],[page['width'],page['height']])} for r in p['regions']]
        by_page[p['source'],p['pdf_page_index']]=regions
    sanity={};global_rows=[]
    for key,source in sources.items():
        body={s.block_id for c in source['document'].chunks if c.kind=='body' for s in c.primary};rows=[]
        for e in source['document'].elements:
            if e.block.block_id not in body or (key,e.block.page_index) not in requested:continue
            regions=by_page[key,e.block.page_index];text=[r['bbox'] for r in regions if r['label'] in cfg['text_like_labels']]
            score=max((union_share(list(e.block.bbox),[b]) for b in text),default=0)
            rows.append({'block_id':e.block.block_id,'pdf_page_index':e.block.page_index,'maximum_single_text_region_share':score,'pass':sanity_match(list(e.block.bbox),text)})
        sanity[key]={'body_blocks':len(rows),'passing':sum(r['pass'] for r in rows),'rows':rows,'coverage':'not covered' if key in prior.REAL else 'processed table-page selection'};global_rows.extend(rows)
    fraction=sum(r['pass'] for r in global_rows)/len(global_rows) if global_rows else None
    sane=fraction is not None and fraction>=cfg['sanity']['passing_block_fraction_min']
    emit('coordinate-sanity.json',{'status':'PASS' if sane else 'STOP_COORDINATE_SANITY_BELOW_0_8','annotations_read':False,'passing_fraction':fraction,'passing':sum(r['pass'] for r in global_rows),'body_blocks':len(global_rows),'sources':sanity,'criterion':cfg['sanity']})
    status='STOP_COORDINATE_SANITY_BELOW_0_8';completed=['coordinate sanity'];not_run=['coverage','agreement','projection','L3-15','second labeler pass']
    if sane:
        decisions={};selected={};unknown=[]
        for key,source in sources.items():
            rows=[];selected[key]=set()
            for e in source['document'].elements:
                if e.role!='table':continue
                regions=by_page.get((key,e.block.page_index));reason=None
                if regions is None:reason='NOT_COVERED_UNREGISTERED_REAL6' if key in prior.REAL else 'MISSING_PROCESSED_PAGE'
                elif not regions:reason='NO_LAYOUT_REGIONS'
                picture=table=None;chosen=False
                if not reason:
                    picture=union_share(list(e.block.bbox),[r['bbox'] for r in regions if r['label']==cfg['picture_label']]);table=union_share(list(e.block.bbox),[r['bbox'] for r in regions if r['label']==cfg['table_label']]);chosen=retype(picture,table)
                row={'block_id':e.block.block_id,'pdf_page_index':e.block.page_index,'bbox':list(e.block.bbox),'picture_union_share':picture,'table_union_share':table,'retyped':chosen,'decision':'UNKNOWN' if reason else 'FIGURE_NONCITABLE' if chosen else 'PRESERVED','reason':reason};rows.append(row)
                if chosen:selected[key].add(e.block.block_id)
                if reason:unknown.append({'source':key,**row})
            decisions[key]=rows
        emit('mapping.json',{'configuration_commit':CONFIG_COMMIT,'sources':decisions,'unknown':unknown})
        emit('coverage.json',{'processed_pages':len(actual),'requested_pages':len(requested),'sources':{k:{'table_blocks':len(v),'known':sum(r['decision']!='UNKNOWN' for r in v),'unknown':sum(r['decision']=='UNKNOWN' for r in v),'retyped':sum(r['retyped'] for r in v)} for k,v in decisions.items()},'unknown':unknown,'real6':'not covered; not classifier evidence'})
        completed.append('coverage')
        checks={};disagreements=[];real_lost=[];hits=0
        for path,is_wef in zip(ANNOTATIONS,(True,False)):
            annotation=read(path);rows=[]
            expected[path]=json.loads(Path('out/r-lite-3/part2a/final-evidence.json').read_text())['protected_hashes']['before'][path]
            if INPUTS[path]!=expected[path]:raise ValueError('ANNOTATION_INPUT_CHANGED:'+path)
            for row in annotation['items']:
                key=prior.WEF if is_wef else row['source'];doc=sources[key]['document'];chunk=next(c for c in doc.chunks if c.chunk_id==row['chunk_id']);bids=sorted({s.block_id for s in chunk.primary})
                assert all(next(e.block.page_index for e in doc.elements if e.block.block_id==b) in next(s['pages'] for s in cfg['inputs'] if s['source']==key) for b in bids),'ANNOTATED_PAGE_NOT_PROCESSED'
                changed=sorted(set(bids)&selected[key]);prediction=bool(bids) and len(changed)==len(bids);expected_chart=row['classification']=='chart text';agree=prediction==expected_chart
                entry={'source':key,'sample_index':row['sample_index'],'chunk_id':row['chunk_id'],'block_ids':bids,'expected':row['classification'],'retyped_block_ids':changed,'predicted_chart':prediction,'agreement':agree}
                if is_wef:hits+=int(prediction)
                if row['classification']=='real table' and changed:real_lost.extend(changed)
                if not agree or (row['classification']=='real table' and changed):disagreements.append(entry)
                rows.append(entry)
            checks[path]={'n':len(rows),'agreements_chart_vs_nonchart':sum(r['agreement'] for r in rows),'rows':rows,'provenance':annotation['provenance']}
        taxonomy=sorted(r['block_id'] for r in decisions[prior.WEF] if r['pdf_page_index']==101 and r['retyped']);gao39=sorted(r['block_id'] for r in decisions['gao-21-519sp'] if r['pdf_page_index']==39 and r['retyped'])
        reasons=[]
        if hits<18:reasons.append('WEF_CHART_CHECK_BELOW_18_OF_20')
        if real_lost:reasons.append('REAL_TABLE_RETYPED')
        if taxonomy:reasons.append('TAXONOMY_TABLE_RETYPED')
        if gao39:reasons.append('GAO_INDEX39_RETYPED')
        if any(r['source'] not in prior.REAL for r in unknown):reasons.append('ELIGIBLE_BLOCK_UNKNOWN')
        emit('agreement.json',{'status':'STOP_AGREEMENT_FAILED' if reasons else 'PASS','configuration_commit':CONFIG_COMMIT,'wef_chart_retyped':hits,'checks':checks,'disagreements':disagreements,'real_table_retyped_ids':sorted(set(real_lost)),'taxonomy_retyped_ids':taxonomy,'gao39_retyped_ids':gao39,'stop_reasons':reasons,'no_configuration_or_mapping_change_after_check':True,'limits':'Reused Codex annotations are a reference check, not independent human/population ground truth.'})
        completed.append('agreement');status='STOP_AGREEMENT_FAILED' if reasons else 'CHECKS_PASS_CONTINUE_DETERMINISM_REQUIRED';not_run=['projection','L3-15','second labeler pass']
        required_crops={(r['source'],b) for r in disagreements for b in r['block_ids']}|{(k,b) for k in prior.DEV for b in selected[k]}
        # Also preserve special-control disagreements, without expanding the inference input set.
        required_crops|={('gao-21-519sp',b) for b in gao39}|{(prior.WEF,b) for b in taxonomy}
        if not reasons:
            questions=read('eval/rag/frozen/questions.json')['items'];prediction=prior.predict(sources,{k:{'chart_sample':v} for k,v in selected.items()},questions,'P2B-Docling-reference-mapping','sample_chart');prediction['mode']='precommitted_docling_reference';prediction['real6']='not covered'
            emit('projection.json',prediction);completed.append('projection')
            bad=prediction['frozen']['ids']['T2']+prediction['frozen']['ids']['T3'];failures={k:r['prediction_failure'] for k,r in prediction['sources'].items() if r['prediction_failure']}
            if bad or failures:
                status='STOP_FROZEN_TARGET_OR_PROJECTION_FAILURE';not_run=['L3-15','second labeler pass'];emit('projection-stop.json',{'frozen_stop_ids':bad,'failures':failures})
            else:
                doc=sources[prior.WEF]['document'];available=set();links=[]
                for t in doc.tables:
                    if t.structure=='available' and t.cells:
                        available.update(t.block_ids);links.append({'table_id':t.table_id,'block_ids':list(t.block_ids),'cells_available':len(t.cells)})
                chart_bids={b for r in checks[ANNOTATIONS[0]]['rows'] for b in r['block_ids']};table_bids={r['block_id'] for r in decisions[prior.WEF]};chart_available=sorted(chart_bids&available)
                emit('table-number-safety.json',{'state':'L3-15_PROPOSED_MEASUREMENT','WEF_table_blocks':len(table_bids),'WEF_table_blocks_with_available_cells':len(table_bids&available),'available_original_table_block_ids':sorted(table_bids&available),'available_original_table_blocks_retyped_figure':sorted(table_bids&available&selected[prior.WEF]),'available_original_table_blocks_preserved':sorted((table_bids&available)-selected[prior.WEF]),'seeded_chart_blocks':len(chart_bids),'seeded_chart_blocks_with_available_cells':len(chart_available),'available_seeded_chart_ids':chart_available,'available_table_links':links,'rule':'Only available structured-table cell values from table-kind blocks may be verification evidence; unavailable-table numbers never evidence. Proposed, not implemented.'})
                required_crops|={(prior.WEF,b) for b in chart_available};completed.append('L3-15');not_run=['second labeler pass']
        crop_manifest=[]
        if required_crops:
            import pypdfium2 as pdfium
            from PIL import Image
            previous=read('out/r-lite-3/part1/crops-manifest.json');previous={(r['source'],r['pdf_page_index']):r for r in previous};opened={}
            try:
                for key,bid in sorted(required_crops):
                    e=next(e for e in sources[key]['document'].elements if e.block.block_id==bid);page=next(p for p in sources[key]['snapshot']['pages'] if p['page_index']==e.block.page_index);src=previous.get((key,e.block.page_index));scale=1.5
                    if src:
                        INPUTS[src['path']]=sha(Path(src['path']).read_bytes());assert INPUTS[src['path']]==src['sha256'];im=Image.open(src['path']).convert('RGB')
                    else:
                        data=next(s for s in cfg['inputs'] if s['source']==key);assert sha(Path(data['pdf']).read_bytes())==data['sha256']
                        if key not in opened:opened[key]=pdfium.PdfDocument(data['pdf'])
                        pg=opened[key][e.block.page_index];bmp=pg.render(scale=scale);im=bmp.to_pil().copy();bmp.close();pg.close()
                    box=list(e.block.bbox);pixel=(max(0,int(box[0]*scale)),max(0,int(box[1]*scale)),min(im.width,int(box[2]*scale+1)),min(im.height,int(box[3]*scale+1)));path=OUT/'crops'/key/(bid.rsplit(':',1)[-1]+'.png');path.parent.mkdir(parents=True,exist_ok=True);im.crop(pixel).save(path);im.close()
                    crop_manifest.append({'source':key,'block_id':bid,'pdf_page_index':e.block.page_index,'bbox':box,'scale':scale,'path':str(path),'sha256':sha(path.read_bytes()),'crop_origin':'native PDF or preserved native PNG','judgment':'Codex reference crop, not human ground truth'})
            finally:
                for d in opened.values():d.close()
        emit('crops-manifest.json',crop_manifest)
    if 'L3-15' in completed and (OUT/'labels-pass2.json').exists():
        second=read(OUT/'labels-pass2.json')
        second_keys={(p['source'],p['pdf_page_index']) for p in second['pages']}
        if second_keys!=requested or second['status']!='COMPLETE':raise ValueError('SECOND_REFERENCE_LABELS_INCOMPLETE')
        result=compare_labels(OUT/'labels-pass1.json',OUT/'labels-pass2.json')
        costs={name:read(OUT/(name+'.json')) for name in ('cost-pass1','cost-pass2')}
        if any(c['status']!='COMPLETE' or c['measured_pages']!=len(requested) for c in costs.values()):raise ValueError('COST_RECORD_INCOMPLETE')
        result['cost_records']={k:str(OUT/(k+'.json')) for k in costs}
        result['status']='PASS' if result['byte_equal'] else 'STOP_LABEL_BYTES_DIFFER'
        emit('determinism.json',result)
        completed.append('determinism and cost');not_run=[]
        status='REFERENCE_GATES_PASS_STOP_OWNER_DECISION' if result['byte_equal'] else 'STOP_LABEL_BYTES_DIFFER'
    before=expected;after={p:sha(Path(p).read_bytes()) for p in before};assert before==after,'PROTECTED_INPUT_CHANGED_DURING_CHECKS'
    INPUTS.update(prior.INPUTS)
    for p in ('eval/rag/r_lite_3_part2b.py','eval/rag/r_lite_3_part2b_mapping.py','eval/run_docling_part2b.py','eval/tests/test_r_lite_3_part2b.py','eval/tests/test_r_lite_3_part2b_mapping.py','eval/tests/test_r_lite_3_part2b_runner.py'):INPUTS[p]=sha(Path(p).read_bytes())
    emit('protected-hashes.json',{'before':before,'after':after,'changed':[]});emit('input-hashes.json',INPUTS);emit('check-status.json',{'status':status,'completed':completed,'not_run':not_run,'coordinate_sanity_fraction':fraction,'configuration_commit':CONFIG_COMMIT,'fixed_configuration_unchanged':True,'M2_M6':'not run; await owner decision','L3_15':'measured' if 'L3-15' in completed else 'not run at earlier ordered STOP'})
    print(json.dumps({'status':status,'coordinate_fraction':fraction,'completed':completed,'not_run':not_run},sort_keys=True))


DIAGNOSTIC_FILES=('coordinate-sanity.json','mapping.json','coverage.json','agreement.json','projection.json','table-number-safety.json','crops-manifest.json','protected-hashes.json','input-hashes.json','check-status.json','determinism.json')


def package():
    status=json.loads((OUT/'check-status.json').read_text())
    if 'determinism and cost' not in status['completed']:raise ValueError('DETERMINISM_NOT_COMPLETED')
    before=read(OUT/'session-before.json')['protected']
    after={p:sha(Path(p).read_bytes()) for p in before}
    if before!=after:raise ValueError('OWNER_OR_DEPENDENCY_INPUT_CHANGED')
    if (OUT/'main-venv-before.freeze.txt').read_bytes()!=(OUT/'main-venv-after.freeze.txt').read_bytes():raise ValueError('MAIN_ENVIRONMENT_CHANGED')
    replay_record=json.loads((OUT/'byte-replay.json').read_text())
    if replay_record['status']!='PASS':raise ValueError('BYTE_REPLAY_NOT_PASSED')
    records={str(p):sha(p.read_bytes()) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name not in ('final-evidence.json','byte-replay.json')}
    emit('final-evidence.json',{'status':status['status'],'inputs':json.loads((OUT/'input-hashes.json').read_text()),'saved_artifact_hashes':records,'protected':{'before':before,'after':after,'changed':[]},'main_environment_freeze_byte_equal':True,'byte_replay':replay_record,'byte_replay_sha256':sha((OUT/'byte-replay.json').read_bytes()),'configuration_commit':CONFIG_COMMIT,'decisions_commit':'a78c4ee','baseline_commit':BASE,'offline_reproduce':'source scripts/dev_environment.sh && .venv/bin/python -m eval.rag.r_lite_3_part2b --replay && .venv/bin/python -m eval.rag.r_lite_3_part2b --package','labeler_reproduce':'See reproduce.md; inference only through /home/asmaa/.venvs/matn-docling/bin/python','M2_M6':'NOT RUN; owner decision required','production_changes':False,'sealed_test_access':False})


def replay():
    paths=[OUT/n for n in DIAGNOSTIC_FILES if (OUT/n).exists()]+sorted((OUT/'crops').rglob('*.png'))
    before={str(p):sha(p.read_bytes()) for p in paths}
    main()
    after={str(p):sha(p.read_bytes()) for p in paths}
    changed=[p for p in before if before[p]!=after[p]]
    emit('byte-replay.json',{'status':'PASS' if not changed else 'FAIL','files':len(paths),'before':before,'after':after,'changed':changed,'scope':'Main-venv diagnostics and native crops from saved labels; timing/license/freeze records are retained inputs, not rerun inference.'})
    if changed:raise ValueError('BYTE_REPLAY_DIFFERS')


if __name__=='__main__':
    if sys.argv[1:]==['--package']:package()
    elif sys.argv[1:]==['--replay']:replay()
    elif sys.argv[1:]:raise ValueError('UNKNOWN_ARGUMENTS')
    else:main()
