"""Standalone isolated offline M3 second opinion; unchanged Part 2b configuration."""
import sys
from pathlib import Path
if __name__!='__main__':raise ImportError('STANDALONE_ONLY')
if Path(sys.prefix)!=Path.home()/'.venvs/matn-docling':raise RuntimeError('ISOLATED_DOCLING_VENV_REQUIRED')
import os
os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
import hashlib,json,time,resource
import pypdfium2 as pdfium
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter,PdfFormatOption
root=Path('out/r-lite-3/part2c');request=json.loads((root/'docling-code-request.json').read_text());cfgraw=Path(request['configuration_path']).read_bytes();assert hashlib.sha256(cfgraw).hexdigest()==request['configuration_sha256'];cfg=json.loads(cfgraw)
assert request['source']=='2601-14525v1';assert hashlib.sha256(Path(request['pdf']).read_bytes()).hexdigest()==request['sha256'],'PDF_SHA_MISMATCH'
options=PdfPipelineOptions()
for key,value in cfg['pipeline_do_flags'].items():setattr(options,key,value)
options.layout_options=options.layout_options.model_copy(update={'model_spec':options.layout_options.model_spec.model_copy(update={'revision':cfg['model_revision']})})
assert options.layout_options.model_dump(mode='json')['engine_options']==cfg['layout_defaults']['engine_options']
assert all(not getattr(options,key) for key in cfg['pipeline_do_flags'])
assert not options.enable_remote_services and not options.allow_external_plugins
converter=DocumentConverter(format_options={InputFormat.PDF:PdfFormatOption(pipeline_options=options)})
with pdfium.PdfDocument(request['pdf']) as pdf:assert all(0<=p<len(pdf) for p in request['pages'])
records=[];costs=[];start=time.perf_counter();status='RUNNING'
def save():
    (root/'docling-code-labels.json').write_text(json.dumps({'status':status,'configuration_sha256':request['configuration_sha256'],'model_revision':cfg['model_revision'],'source_sha256':request['sha256'],'pages':records},sort_keys=True,indent=2)+'\n')
    (root/'docling-code-cost.json').write_text(json.dumps({'status':status,'pages':costs,'total_wall_seconds':time.perf_counter()-start,'layout_calls':len(costs),'OCR_calls':0,'LLM_calls':0,'embedding_calls':0,'network_enabled':False,'peak_RSS_KiB':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss},sort_keys=True,indent=2)+'\n')
try:
    for index in request['pages']:
        assert hashlib.sha256(Path(request['pdf']).read_bytes()).hexdigest()==request['sha256'],'PDF_SHA_MISMATCH'
        begin=time.perf_counter();result=converter.convert(Path(request['pdf']),page_range=(index+1,index+1));assert len(result.pages)==1 and result.pages[0].page_no==index+1
        page=result.pages[0];assert page.predictions.layout is not None;regions=[]
        def add(cluster):
            regions.append({'id':cluster.id,'label':cluster.label.value,'bbox':cluster.bbox.model_dump(mode='json'),'confidence':cluster.confidence})
            for child in cluster.children:add(child)
        for cluster in page.predictions.layout.clusters:add(cluster)
        regions.sort(key=lambda r:(r['label'],r['bbox']['l'],r['bbox']['t'],r['bbox']['r'],r['bbox']['b'],r['id']))
        records.append({'source':request['source'],'pdf_page_index':index,'docling_page_size':[page.size.width,page.size.height],'regions':regions});costs.append({'page_index':index,'wall_seconds':time.perf_counter()-begin})
        save();print('PAGE',index,'COMPLETED',len(records),'OF',len(request['pages']),flush=True)
    assert len(records)==len(request['pages']);status='COMPLETE';save()
except Exception:
    status='STOP_RUNNER_ERROR';save();raise
