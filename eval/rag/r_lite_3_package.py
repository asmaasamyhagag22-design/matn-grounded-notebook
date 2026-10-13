"""Package the approved Part1 evidence after offline diagnostic reproduction."""
import hashlib
import json
import subprocess
from pathlib import Path
from eval.rag.r_lite_3_part1 import OUT

OWNER_SHA='1dcad15eae87f2c4ba5b2942ea6ef9f732a2fa2088aab6032cd42a8649a85abd'


def verify_hashes(expected):
    after={str(path):hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in expected}
    changed=[str(path) for path,sha in expected.items() if after[str(path)]!=sha]
    if changed:raise ValueError('PROTECTED_INPUT_CHANGED:'+','.join(changed))
    return after


def main():
    inputs=json.loads((OUT/'diagnostic-input-hashes.json').read_text())
    inputs.update(json.loads((OUT/'identity-inventory.json').read_text())['input_sha256'])
    for path in ['eval/rag/r_lite_3_package.py','eval/tests/test_r_lite_3_identity.py','eval/tests/test_r_lite_3_part1.py']:
        inputs[path]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    for path in ['ENGINEERING_RULES.md','AGENTS.md','scripts/dev_environment.sh','.githooks/pre-commit','.githooks/pre_commit.py','docs/REVIEWER_BRIEF.md','reports/rag-core.md','reports/rag-core-wef-first-run.md','out/rag-core/part2/full-suite.xml','out/rag-core/part2/full-suite.log']:
        inputs[path]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
    baseline_handoff=subprocess.run(['git','show','6e054a5:reports/HANDOFF.md'],check=True,capture_output=True).stdout
    inputs['reports/HANDOFF.md@6e054a5']=hashlib.sha256(baseline_handoff).hexdigest()
    before={path:sha for path,sha in inputs.items() if path.startswith(('out/r-lite-2/','out/rag-core/','eval/incoming/'))}
    before['reports/r-lite-diagnostics.md']=OWNER_SHA
    core=json.loads(Path('reports/rag-core-evidence.json').read_text())
    before.update({'eval/rag/frozen/'+path:sha for path,sha in core['frozen_sha256'].items()})
    manifest_path='eval/rag/frozen/manifest.json'
    baseline_manifest=subprocess.run(['git','show','6e054a5:'+manifest_path],check=True,capture_output=True).stdout
    before[manifest_path]=hashlib.sha256(baseline_manifest).hexdigest()
    inputs[manifest_path]=before[manifest_path]
    after=verify_hashes(before)
    manifests=['out/r-lite-2/final-evidence.json','reports/rag-core-part1-evidence.json','reports/rag-core-wef-stop-evidence.json','reports/rag-core-evidence.json','out/rag-core/vector-diagnosis/final-evidence.json']
    recorded={}
    def scan(v):
        if isinstance(v,dict):
            for k,x in v.items():
                if isinstance(x,str) and len(x)==64 and k.startswith(('out/','eval/')):recorded[k]=x
                elif isinstance(x,(dict,list)):scan(x)
        elif isinstance(v,list):
            for x in v:scan(x)
    for p in manifests:
        scan(json.loads(Path(p).read_text()));inputs[p]=hashlib.sha256(Path(p).read_bytes()).hexdigest()
    no_hash=[]
    for path in sorted(p for p in before if p.startswith(('out/r-lite-2/','out/rag-core/'))):
        if path in recorded:
            if recorded[path]!=before[path]:raise ValueError('RECORDED_HASH_MISMATCH:'+path)
        elif Path(path).with_suffix('.sha256').exists():
            if Path(path).with_suffix('.sha256').read_text().strip()!=before[path]:raise ValueError('SIDECAR_MISMATCH:'+path)
        elif Path(path).name=='05_document.json' and (Path(path).parent/'06_run_manifest.json').exists():
            manifest=Path(path).parent/'06_run_manifest.json';expected=json.loads(manifest.read_text())['structure_hashes']['05_document.json']
            if expected!=before[path]:raise ValueError('RUN_MANIFEST_MISMATCH:'+path)
            manifests.append(str(manifest));inputs[str(manifest)]=hashlib.sha256(manifest.read_bytes()).hexdigest()
        else:no_hash.append(path)
    no_hash.extend(['eval/rag/wef-table-visual-annotations.json','eval/rag/dev-table-visual-annotations-20261012.json','eval/approvals/wef-ocr-2026-10-11.json'])
    inputs['reports/r-lite-3-plan.md']=hashlib.sha256(Path('reports/r-lite-3-plan.md').read_bytes()).hexdigest()
    outputs={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='final-evidence.json'}
    evidence={'status':'R_LITE_3_PART1_PLAN_READY_STOP_OWNER_APPROVAL','approvals':'P1-A..P1-I only','baseline_head':'6e054a5','freeze_commit':'ab765ed','focused_tests':8,'missing_module_RED':'ModuleNotFoundError; diagnostic modules only, no reading fixtures','model_calls':0,'embedding_calls':0,'new_OCR_calls':0,'network_calls':0,'new_acquisitions':0,'retrieval_runs':0,'full_suite_runs':0,'input_sha256':inputs,'protected_before_sha256':before,'protected_after_sha256':after,'protected_changed':[],'output_sha256':outputs,'recorded_hash_manifests':sorted(set(manifests)),'baseline_inputs_without_recorded_hash':sorted(set(no_hash)),'reproduction':'source scripts/dev_environment.sh && .venv/bin/python -m eval.rag.r_lite_3_part1 > out/r-lite-3/part1/reproduce.log 2>&1 && .venv/bin/python -m eval.rag.r_lite_3_package','limits':['Projections are not accepted production structures.','Finite cohorts and model family A visual judgment are not population accuracy claims.','Regional OCR additions and combined fixes are not guessed.','P1-G/P1-H resolve the earlier recorded STOPs.','Producer-version overlay is separate from per-mechanism projections.']}
    raw=json.dumps(evidence,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
    (OUT/'final-evidence.json').write_text(raw)
    Path('reports/r-lite-3-part1-evidence.json').write_text(raw)
    print('PACKAGE PASS; protected inputs unchanged; plan awaits named approval')


if __name__=='__main__':main()
