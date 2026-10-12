"""Standalone eval-only reference runner. Execute solely in the approved external venv."""
import sys
from pathlib import Path

if __name__!='__main__':
    raise ImportError('STANDALONE_ONLY: this runner must not be imported')
if Path(sys.prefix)!=Path.home()/'.venvs'/'matn-docling':
    raise RuntimeError('ISOLATED_DOCLING_VENV_REQUIRED')

import time
PROCESS_START=time.perf_counter()
import os
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
import argparse
import hashlib
import json
import resource
import time
import pypdfium2 as pdfium
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter,PdfFormatOption

parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--metrics',required=True)
args=parser.parse_args();cfg_path=Path('eval/rag/r_lite_3_part2b_config.json');raw=cfg_path.read_bytes();cfg=json.loads(raw)
options=PdfPipelineOptions()
for key,value in cfg['pipeline_do_flags'].items():setattr(options,key,value)
options.layout_options=options.layout_options.model_copy(update={'model_spec':options.layout_options.model_spec.model_copy(update={'revision':cfg['model_revision']})})
assert options.layout_options.model_dump(mode='json')['engine_options']==cfg['layout_defaults']['engine_options']
assert not getattr(options,'enable_remote_services',False) and not getattr(options,'allow_external_plugins',False)
assert all(not getattr(options,key) for key in cfg['pipeline_do_flags'])
converter=DocumentConverter(format_options={InputFormat.PDF:PdfFormatOption(pipeline_options=options)})
output=Path(args.output);metrics_path=Path(args.metrics);output.parent.mkdir(parents=True,exist_ok=True)
records=[];metrics=[];opened=[];start=PROCESS_START;status='RUNNING';estimate=None

def save():
    data={'configuration_sha256':hashlib.sha256(raw).hexdigest(),'model_repo':cfg['model_repo'],'model_revision':cfg['model_revision'],'status':status,'sources_opened':opened,'pages':records,'real6':cfg['real6']}
    output.write_text(json.dumps(data,sort_keys=True,indent=2,allow_nan=False)+'\n')
    metrics_path.write_text(json.dumps({'status':status,'pages':metrics,'total_wall_seconds':time.perf_counter()-start,'peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'requested_pages':sum(len(s['pages']) for s in cfg['inputs']),'measured_pages':len(metrics),'projected_two_pass_seconds':estimate,'model_calls_layout':len(metrics),'OCR_calls':0,'LLM_calls':0,'embedding_calls':0,'network_enabled':False},sort_keys=True,indent=2)+'\n')

try:
    for source in cfg['inputs']:
        path=Path(source['pdf']);assert hashlib.sha256(path.read_bytes()).hexdigest()==source['sha256'],'PDF_SHA_MISMATCH'
        pdf=pdfium.PdfDocument(str(path));opened.append({'source':source['source'],'sha256':source['sha256'],'page_count':len(pdf),'selected_pages':source['pages']});pdf.close()
        for index in source['pages']:
            assert hashlib.sha256(path.read_bytes()).hexdigest()==source['sha256'],'PDF_SHA_MISMATCH'
            then=time.perf_counter();result=converter.convert(path,page_range=(index+1,index+1))
            assert len(result.pages)==1 and result.pages[0].page_no==index+1,'PAGE_RANGE_MISMATCH'
            page=result.pages[0];assert page.predictions.layout is not None,'NO_LAYOUT_RESULT'
            regions=[]
            def add(cluster):
                regions.append({'id':cluster.id,'label':cluster.label.value,'bbox':cluster.bbox.model_dump(mode='json'),'confidence':cluster.confidence})
                for child in cluster.children:add(child)
            for cluster in page.predictions.layout.clusters:add(cluster)
            regions.sort(key=lambda r:(r['label'],r['bbox']['l'],r['bbox']['t'],r['bbox']['r'],r['bbox']['b'],r['id']))
            records.append({'source':source['source'],'pdf_page_index':index,'docling_page_size':[page.size.width,page.size.height],'regions':regions})
            metrics.append({'source':source['source'],'pdf_page_index':index,'wall_seconds':time.perf_counter()-then,'peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
            if len(metrics)==cfg['cost_gate']['sample_pages']:
                estimate=(time.perf_counter()-start)/len(metrics)*sum(len(s['pages']) for s in cfg['inputs'])*2
                if estimate>cfg['cost_gate']['seconds_limit']:status='STOP_PROJECTED_COST_OVER_3_HOURS';save();print(status,estimate,flush=True);raise SystemExit(30)
            save();print('PAGE',len(metrics),source['source'],index,'SECONDS',round(metrics[-1]['wall_seconds'],2),flush=True)
    status='COMPLETE';save();print('LABELER_COMPLETE',len(records),flush=True)
except Exception as e:
    status='STOP_RUNNER_ERROR';save()
    Path(str(metrics_path)+'.error.json').write_text(json.dumps({'error_type':type(e).__name__,'message':str(e)},sort_keys=True,indent=2)+'\n')
    raise
