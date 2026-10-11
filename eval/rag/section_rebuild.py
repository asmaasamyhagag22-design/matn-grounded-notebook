"""Offline section-identity migration gates; never acquire PDFs or model text."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from checks.egress_guard import block_egress
from matn_reading.structure.cache import load_snapshot,save_snapshot
from matn_reading.structure.document import write_structure
from eval.reading.r_lite import assert_gates,quote_coverage,metrics

ROOT=Path('out/rag-core/section-rebuild')
DEV=('2601-14525v1','gao-21-519sp','wb-eem-2021-12')
REAL=('nbs_circular_31_e4_1956','statab_1951_part04')


def replace(value,mapping):
    if isinstance(value,dict):return {k:replace(v,mapping) for k,v in value.items()}
    if isinstance(value,list):return [replace(v,mapping) for v in value]
    return mapping.get(value,value) if isinstance(value,str) else value


def id_only(before,after):
    mapping={};changed=[]
    for field,key in [('sections','section_id'),('chunks','chunk_id')]:
        if len(before[field])!=len(after[field]):raise ValueError('NON_ID_COUNT_CHANGE:'+field)
        for old,new in zip(before[field],after[field]):
            mapping[old[key]]=new[key];changed.append({'kind':field,'old':old[key],'new':new[key]})
    expected=replace(before,mapping)
    expected['producer_versions']['sections']=after['producer_versions']['sections']
    for s,n in zip(expected['sections'],after['sections']):s['producer_version']=n['producer_version']
    if expected!=after:
        fields=[k for k in expected if expected[k]!=after[k]]
        raise ValueError('NON_ID_DIFFERENCE:'+','.join(fields))
    if any(r['old']==r['new'] for r in changed):raise ValueError('EXPECTED_ALL_IDS_CHANGED')
    return changed


def run():
    inputs=[]
    for k in DEV:inputs.append((k,next((Path('out/r-lite-2')/k/'runs').glob('*/00_reading.json')),True))
    for k in REAL:inputs.append((k,Path('out/r-lite-2/real')/k/'00_reading.json',True))
    inputs.append(('wef-future-of-jobs-2025',next(Path('out/rag-core/wef-first-run/approved-acquisition/runs').glob('*/00_reading.json')),False))
    result={};seen=0
    for key,path,compare in inputs:
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        with block_egress():
            snap=load_snapshot(path);folder=ROOT/key
            save_snapshot(folder/'00_reading.json',snap)
            doc=write_structure(snap,folder)
            gates=assert_gates(doc)
            changes=id_only(json.loads((path.parent/'05_document.json').read_bytes()),doc.model_dump(mode='json')) if compare else []
        save_snapshot(folder/'determinism/00_reading.json',snap)
        subprocess.run([sys.executable,'-m','eval.rag.section_rebuild','--worker',str(folder/'determinism')],check=True)
        files=('01_elements.jsonl','02_sections.json','03_tables.json','04_chunks.jsonl','05_document.json','document.json')
        if any((folder/n).read_bytes()!=(folder/'determinism'/n).read_bytes() for n in files):raise ValueError('G5_BYTES:'+key)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('INPUT_MUTATED')
        row={'gates':{**gates,'G5':'PASS'},'input':str(path),'input_sha256':digest,'id_only':compare,'changed_ids':changes,'metrics':metrics(doc)}
        if key in DEV:
            g=json.loads((Path('eval/gold/dev')/(key+'.json')).read_text());row['gold']=quote_coverage(doc,g['key_points']+g['key_numbers']);seen+=row['gold']['single_chunk']
            old=json.loads(Path('out/r-lite-2/metrics.json').read_text())[key]['gold']
            if row['gold']!=old:raise ValueError('G4_CHANGED:'+key)
        result[key]=row
        ROOT.mkdir(exist_ok=True,parents=True);(ROOT/'gates.json').write_text(json.dumps(result,indent=2)+'\n')
        print(key,'PASS',len(changes),'id changes',flush=True)
    if seen!=68:raise ValueError('G4_TOTAL')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--worker',type=Path);args=p.parse_args()
    if args.worker:
        with block_egress():write_structure(load_snapshot(args.worker/'00_reading.json'),args.worker)
    else:run()
