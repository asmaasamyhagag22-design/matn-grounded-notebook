"""Offline Part2a general-rule projections; stops at the first owner gate failure.

Reproduce: source scripts/dev_environment.sh && .venv/bin/python -m eval.rag.r_lite_3_part2a
No production import path uses this module. Frozen M1 is never adjusted by this runner.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from PIL import Image

from checks.egress_guard import block_egress
from eval.rag import r_lite_3_part1 as prior
from eval.rag.r_lite_3_m1_rule import decide, PARAMETERS

OUT=Path('out/r-lite-3/part2a')
RULE_COMMIT='0f3b180'
BASELINE='d1f3be0'
OWNER_SHA='1dcad15eae87f2c4ba5b2942ea6ef9f732a2fa2088aab6032cd42a8649a85abd'
INPUTS={}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def read(path):
    path=Path(path);raw=path.read_bytes();INPUTS[str(path)]=sha(raw);return json.loads(raw)


def emit(name,data):
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')


def stop_reasons(chart_hits,real_table_ids,taxonomy_ids,t2,t3):
    reasons=[]
    if real_table_ids:reasons.append('REAL_TABLE_RETYPED')
    if taxonomy_ids:reasons.append('WEF_TAXONOMY_TABLE_RETYPED')
    if chart_hits<18:reasons.append('WEF_CHART_CHECK_BELOW_18_OF_20')
    if t2 or t3:reasons.append('FROZEN_T2_OR_T3')
    return reasons


def protect():
    accepted=read('reports/r-lite-3-part1-evidence.json')
    expected=dict(accepted['protected_before_sha256'])
    expected.update({p:v for p,v in accepted['input_sha256'].items() if '@' not in p and p!='docs/REVIEWER_BRIEF.md'})
    expected.update(accepted['output_sha256'])
    for p,v in expected.items():INPUTS[p]=v
    expected['reports/r-lite-diagnostics.md']=OWNER_SHA
    for path,value in expected.items():
        if sha(Path(path).read_bytes())!=value:raise ValueError('PROTECTED_INPUT_CHANGED:'+path)
    brief=Path('docs/REVIEWER_BRIEF.md').read_bytes()
    baseline=subprocess.check_output(['git','show',BASELINE+':docs/REVIEWER_BRIEF.md'])
    if not brief.startswith(baseline) or len(brief[len(baseline):].decode().strip().splitlines())!=1:
        raise ValueError('EXISTING_DECISION_ROWS_CHANGED')
    INPUTS['docs/REVIEWER_BRIEF.md']=sha(brief)
    for path in ('eval/rag/r_lite_3_m1_rule.py','eval/rag/r_lite_3_m1_rule.json','eval/tests/test_r_lite_3_m1_rule.py'):
        raw=Path(path).read_bytes()
        if raw!=subprocess.check_output(['git','show',RULE_COMMIT+':'+path]):raise ValueError('FROZEN_M1_RULE_CHANGED:'+path)
        INPUTS[path]=sha(raw)
    return expected


def main():
    with block_egress():
        protected=protect()
        sources=prior.load_sources();INPUTS.update(prior.INPUTS)
        objects=read('out/r-lite-3/part1/objects.json')
        page_crops=read('out/r-lite-3/part1/crops-manifest.json')
        crop_by={(r['source'],r['pdf_page_index']):r for r in page_crops}
        decisions={};cohorts={};selected={}
        for key,source in sources.items():
            ids=prior.table_ids(source['document']);rows=[];selected[key]=set()
            for e in source['document'].elements:
                if e.block.block_id not in ids:continue
                result=decide(objects.get(key+'/'+str(e.block.page_index)),list(e.block.bbox),e.block.style.font_size_pt)
                result.update(block_id=e.block.block_id,pdf_page_index=e.block.page_index,bbox=list(e.block.bbox),before_role=e.role)
                rows.append(result)
                if result['chart']:selected[key].add(e.block.block_id)
            decisions[key]=rows;cohorts[key]={'chart_sample':selected[key]}
        questions=read('eval/rag/frozen/questions.json')['items']
        prediction=prior.predict(sources,cohorts,questions,'M1-general-object-rule-v1','sample_chart')
        prediction['mode']='general_object_rule';prediction['cohort_origin']='Frozen page-object rule, never annotation IDs or pages.'
        failures={k:r['prediction_failure'] for k,r in prediction['sources'].items() if r['prediction_failure']}
        emit('m1-decisions.json',{'rule_commit':RULE_COMMIT,'parameters':PARAMETERS,'sources':decisions})
        emit('m1-prediction.json',prediction)
        # Changed blocks and every annotation disagreement receive source-bbox native crops.
        crop_manifest=[];made={}
        def crop(key,bid,reason):
            if (key,bid) in made:
                made[key,bid]['reasons'].append(reason);return made[key,bid]['path']
            e=next(e for e in sources[key]['document'].elements if e.block.block_id==bid)
            src=crop_by.get((key,e.block.page_index))
            if src is None:raise ValueError('MISSING_NATIVE_CROP:'+key+':'+bid)
            raw=Path(src['path']).read_bytes();INPUTS[src['path']]=sha(raw)
            if sha(raw)!=src['sha256']:raise ValueError('NATIVE_CROP_SHA_MISMATCH:'+src['path'])
            box=list(e.block.bbox);scale=src['scale_px_per_pt'];origin=src['bbox'];path=OUT/'crops'/key/(bid.rsplit(':',1)[-1]+'.png');path.parent.mkdir(parents=True,exist_ok=True)
            with Image.open(src['path']) as im:
                pixel=(max(0,int((box[0]-origin[0])*scale)),max(0,int((box[1]-origin[1])*scale)),min(im.width,int((box[2]-origin[0])*scale+1)),min(im.height,int((box[3]-origin[1])*scale+1)))
                if pixel[2]<=pixel[0] or pixel[3]<=pixel[1]:raise ValueError('EMPTY_NATIVE_CROP:'+bid)
                im.crop(pixel).save(path)
            item={'source':key,'block_id':bid,'pdf_page_index':e.block.page_index,'bbox':box,'path':str(path),'sha256':sha(path.read_bytes()),'scale_px_per_pt':scale,'source_crop':src['path'],'source_crop_sha256':src['sha256'],'reasons':[reason],'judgment':'geometry diagnostic; not human truth'}
            crop_manifest.append(item);made[key,bid]=item;return str(path)
        for key,ids in selected.items():
            for bid in sorted(ids):crop(key,bid,'M1 general rule changed table-kind block')
        # Annotation files are first consulted here, after frozen-rule commit and projection.
        checks={};disagreements=[];real_lost=[];hits=0
        for path,is_wef in [('eval/rag/wef-table-visual-annotations.json',True),('eval/rag/dev-table-visual-annotations-20261012.json',False)]:
            labels=read(path);rows=[]
            for row in labels['items']:
                key=prior.WEF if is_wef else row['source']
                chunk=next(c for c in sources[key]['document'].chunks if c.chunk_id==row['chunk_id'])
                bids=sorted({s.block_id for s in chunk.primary});typed=[b for b in bids if b in selected[key]]
                expected=row['classification'];expected_chart=expected=='chart text'
                predicted_chart=bool(bids) and len(typed)==len(bids)
                agree=expected_chart==predicted_chart
                entry={'source':key,'sample_index':row['sample_index'],'chunk_id':row['chunk_id'],'block_ids':bids,'expected_class':expected,'predicted_class':'chart text' if predicted_chart else 'preserved table-kind','retyped_block_ids':typed,'agreement_chart_vs_nonchart':agree,'crops':[]}
                if is_wef:hits+=int(predicted_chart)
                if expected=='real table' and typed:real_lost.extend(typed)
                if not agree or (expected=='real table' and typed):
                    entry['crops']=[crop(key,b,'M1 annotation disagreement') for b in bids];disagreements.append(entry)
                rows.append(entry)
            checks[path]={'n':len(rows),'agreements_chart_vs_nonchart':sum(r['agreement_chart_vs_nonchart'] for r in rows),'rows':rows,'label_provenance':labels['provenance']}
        taxonomy=[b for b in selected[prior.WEF] if next(e.block.page_index for e in sources[prior.WEF]['document'].elements if e.block.block_id==b)==101]
        ft=prediction['frozen']['counts'];reasons=stop_reasons(hits,real_lost,taxonomy,ft['T2'],ft['T3'])
        if failures:reasons.append('PROJECTION_FAILURE')
        result={'status':'STOP_M1_OWNER_GATE_FAILED' if reasons else 'M1_PASS_CONTINUE_REQUIRED','rule_commit':RULE_COMMIT,'rule_commit_before_annotation_check':True,'rule_not_adjusted_after_results':True,'wef_chart_retyped':hits,'wef_required':18,'checks':checks,'disagreements':disagreements,'real_table_retyped_ids':sorted(set(real_lost)),'taxonomy_retyped_ids':sorted(taxonomy),'frozen_counts':ft,'frozen_stop_ids':prediction['frozen']['ids']['T2']+prediction['frozen']['ids']['T3'],'projection_failures':failures,'stop_reasons':reasons,'limits':['These labels were previously used in Part1; this is a frozen-rule check on reused model family A annotations, not independent human/population validation.','Preserved table-kind is not a semantic correction of prose; agreement is chart versus non-chart.','Missing native objects, raster-only plots and partial blocks remain conservative unknown/preserved.']}
        emit('m1-held-out-check.json',result)
        emit('crops-manifest.json',crop_manifest)
        emit('inspected-pages.json',[{'source':r['source'],'pdf_page_index':r['pdf_page_index'],'reason':r['reasons'],'new_pdf_access':False,'native_source_crop':r['source_crop']} for r in crop_manifest])
        emit('predictions.json',{'completed':['M1'],'not_run':[] if not reasons else ['M2','M3','M4','M5','M6'],'projections':[prediction],'status':result['status'],'stop_reasons':reasons})
        before=dict(protected);after={p:sha(Path(p).read_bytes()) for p in before}
        if before!=after:raise ValueError('PROTECTED_INPUT_CHANGED_DURING_DIAGNOSIS')
        for path in ('eval/rag/r_lite_3_part2a.py','eval/rag/r_lite_3_part1.py','eval/rag/r_lite_3_identity.py','eval/tests/test_r_lite_3_part2a.py'):
            INPUTS[path]=sha(Path(path).read_bytes())
        INPUTS.update(prior.INPUTS)
        emit('input-hashes.json',INPUTS)
        emit('protected-hashes.json',{'before':before,'after':after,'changed':[]})
        print(json.dumps({'status':result['status'],'chart_hits':hits,'frozen':ft,'stop_reasons':reasons},sort_keys=True))


def package():
    inputs=json.loads((OUT/'input-hashes.json').read_text())
    protected=json.loads((OUT/'protected-hashes.json').read_text())
    for path,value in inputs.items():
        if sha(Path(path).read_bytes())!=value:raise ValueError('INPUT_CHANGED_BEFORE_PACKAGING:'+path)
    report=Path('reports/r-lite-3-part2a.md')
    inputs[str(report)]=sha(report.read_bytes())
    rule=json.loads((OUT/'m1-held-out-check.json').read_text())
    outputs={str(p):sha(p.read_bytes()) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='final-evidence.json'}
    evidence={'status':rule['status'],'rule_commit':RULE_COMMIT,'decisions_commit':'73f83e5','baseline':BASELINE,'rule_not_adjusted_after_results':True,'stop_reasons':rule['stop_reasons'],'completed_mechanisms':['M1'],'not_run_mechanisms':['M2','M3','M4','M5','M6'],'focused_tests':14,'new_PDF_access':0,'new_OCR_calls':0,'model_calls':0,'network_calls':0,'embedding_calls':0,'retrieval_runs':0,'full_suite_runs':0,'input_sha256':inputs,'output_sha256':outputs,'protected_hashes':protected,'process_notes':['Initial diagnostic runner used questions instead of items for the frozen JSON envelope; fixed adapter only, frozen rule unchanged.','Missing-module RED recorded for both new diagnostic modules; no reading fixtures.'],'reproduction':'source scripts/dev_environment.sh && .venv/bin/python -m eval.rag.r_lite_3_part2a > out/r-lite-3/part2a/reproduce.log 2>&1 && .venv/bin/python -m eval.rag.r_lite_3_part2a --package','limits':rule['limits']}
    emit('final-evidence.json',evidence)
    print('PART2A PACKAGE: STOP evidence recorded; protected inputs unchanged')


if __name__=='__main__':
    if sys.argv[1:]==['--package']:package()
    elif sys.argv[1:]:raise ValueError('UNSUPPORTED_DIAGNOSTIC_ARGUMENT')
    else:main()
