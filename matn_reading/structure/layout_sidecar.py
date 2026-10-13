"""Optional isolated label stage and fail-closed JSON-only source-bound consumer."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from .layout_mapping import convert_box,union_share,retype

SETTINGS=Path(__file__).with_name('layout_settings.json')

def consume(snapshot,elements,sidecar):
 settings=json.loads(SETTINGS.read_text())
 if sidecar.get('source_sha256')!=snapshot['doc_id'].removeprefix('sha256-'):raise ValueError('SIDECAR_SOURCE_SHA')
 if sidecar.get('schema_version')!=1 or sidecar.get('status')!='COMPLETE':raise ValueError('SIDECAR_INCOMPLETE')
 if sidecar.get('configuration_sha256')!=settings['configuration_sha256'] or sidecar.get('model_revision')!=settings['model_revision']:raise ValueError('SIDECAR_CONFIGURATION')
 if sidecar.get('model_files_SHA256')!=settings['model_files_SHA256']:raise ValueError('SIDECAR_MODEL_HASHES')
 pages={p['page_index']:p for p in snapshot['pages']};regions={}
 for row in sidecar['pages']:
  i=row['pdf_page_index']
  if i not in pages or i in regions:raise ValueError('SIDECAR_PAGE_ID')
  boxes=[]
  for region in row['regions']:
   box=convert_box(region['bbox'],row['docling_page_size'],[pages[i]['width'],pages[i]['height']])
   if not all(math.isfinite(v) for v in box):raise ValueError('SIDECAR_NONFINITE')
   boxes.append((region['label'],box))
  regions[i]=boxes
 result=[]
 for e in elements:
  reg=regions.get(e.block.page_index)
  if e.role=='table' and reg and retype(union_share(e.block.bbox,[b for l,b in reg if l=='picture']),union_share(e.block.bbox,[b for l,b in reg if l=='table'])):
   e=e.model_copy(update={'role':'figure','citable':False,'exclusion_reasons':tuple(dict.fromkeys((*e.exclusion_reasons,'figure_text')))})
  result.append(e)
 return tuple(result)

def label_sources(request,output,*,python,artifacts_path):
 """Run only the isolated interpreter, offline, with explicit existing artifacts."""
 python=Path(python).absolute();artifacts=Path(artifacts_path).resolve()
 if python==Path(sys.executable).absolute():raise ValueError('ISOLATED_INTERPRETER_REQUIRED')
 settings=json.loads(SETTINGS.read_text());model=artifacts/settings['model_repo'].replace('/','--')
 if not model.is_dir() or not (model/'config.json').is_file():raise ValueError('OFFLINE_ARTIFACTS_MISSING')
 for name,sha in settings['model_files_SHA256'].items():
  if hashlib.sha256((model/name).read_bytes()).hexdigest()!=sha:raise ValueError('OFFLINE_MODEL_HASH_MISMATCH:'+name)
 env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1'}
 return subprocess.run([str(python),str(Path(__file__).with_name('layout_runner.py')),'--request',str(Path(request).resolve()),'--output',str(Path(output).resolve()),'--artifacts-path',str(artifacts)],env=env,check=True)

def main():
 p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--output',required=True);p.add_argument('--python',required=True);p.add_argument('--artifacts-path',required=True);a=p.parse_args()
 label_sources(a.request,a.output,python=a.python,artifacts_path=a.artifacts_path)

if __name__=='__main__':main()
