"""Standalone isolated Docling subprocess. Main environment never imports this runner."""
if __name__!='__main__':raise ImportError('STANDALONE_ISOLATED_ONLY')
import argparse,hashlib,importlib.metadata,json,os,re,sys,time
from pathlib import Path
if Path(sys.prefix).resolve()==(Path(__file__).resolve().parents[2]/'.venv').resolve():raise RuntimeError('ISOLATED_INTERPRETER_REQUIRED')
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--output',required=True);p.add_argument('--artifacts-path',required=True);args=p.parse_args()
settings=json.loads(Path(__file__).with_name('layout_settings.json').read_text());request=json.loads(Path(args.request).read_text());output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
for name,value in settings['installed_versions'].items():
 if importlib.metadata.version(name)!=value:raise RuntimeError('ISOLATED_PACKAGE_MISMATCH:'+name)
artifacts=Path(args.artifacts_path).resolve();model=artifacts/settings['model_repo'].replace('/','--')
if not model.is_dir() or not (model/'config.json').is_file():raise RuntimeError('OFFLINE_ARTIFACTS_MISSING')
for name,sha in settings['model_files_SHA256'].items():
 if hashlib.sha256((model/name).read_bytes()).hexdigest()!=sha:raise RuntimeError('OFFLINE_MODEL_HASH_MISMATCH:'+name)
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter,PdfFormatOption
options=PdfPipelineOptions(artifacts_path=artifacts)
for key,value in settings['pipeline_do_flags'].items():setattr(options,key,value)
options.layout_options=options.layout_options.model_copy(update={'model_spec':options.layout_options.model_spec.model_copy(update={'revision':settings['model_revision']})})
assert options.layout_options.model_dump(mode='json')['engine_options']==settings['layout_defaults']['engine_options']
assert all(not getattr(options,k) for k in settings['pipeline_do_flags'])
assert not options.enable_remote_services and not options.allow_external_plugins
converter=DocumentConverter(format_options={InputFormat.PDF:PdfFormatOption(pipeline_options=options)})
cost=[];started=time.perf_counter()
def save(name,value):(output/name).write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n')
for source in request['sources']:
 name=source['source'];pdf=Path(source['pdf']);indices=source['pages']
 if not re.fullmatch(r'[A-Za-z0-9_-]+',name):raise ValueError('INVALID_SOURCE_NAME')
 if len(indices)!=len(set(indices)) or any(not isinstance(i,int) or i<0 for i in indices):raise ValueError('INVALID_PAGE_SELECTION')
 if hashlib.sha256(pdf.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('PDF_SHA_MISMATCH')
 result={'schema_version':1,'source_sha256':source['sha256'],'configuration_sha256':settings['configuration_sha256'],'model_repo':settings['model_repo'],'model_revision':settings['model_revision'],'model_files_SHA256':settings['model_files_SHA256'],'status':'RUNNING','pages':[]}
 save(name+'.json',result)
 for i in indices:
  if hashlib.sha256(pdf.read_bytes()).hexdigest()!=source['sha256']:raise ValueError('PDF_SHA_MISMATCH')
  tick=time.perf_counter();converted=converter.convert(pdf,page_range=(i+1,i+1));assert len(converted.pages)==1 and converted.pages[0].page_no==i+1
  page=converted.pages[0];assert page.predictions.layout is not None
  regs=[]
  def add(cluster):
   regs.append({'id':cluster.id,'label':cluster.label.value,'bbox':cluster.bbox.model_dump(mode='json'),'confidence':cluster.confidence})
   for child in cluster.children:add(child)
  for cluster in page.predictions.layout.clusters:add(cluster)
  regs.sort(key=lambda r:(r['label'],r['bbox']['l'],r['bbox']['t'],r['bbox']['r'],r['bbox']['b'],r['id']))
  result['pages'].append({'pdf_page_index':i,'docling_page_size':[page.size.width,page.size.height],'regions':regs});save(name+'.json',result)
  cost.append({'source':name,'pdf_page_index':i,'seconds':time.perf_counter()-tick});print('LAYOUT',len(cost),name,i,flush=True)
 result['status']='COMPLETE';save(name+'.json',result)
save('cost.json',{'status':'COMPLETE','pages':cost,'total_seconds':time.perf_counter()-started,'layout_calls':len(cost),'OCR_calls':0,'LLM_calls':0,'embedding_calls':0,'network_downloads':0,'explicit_artifacts_path':str(artifacts)})
print('LAYOUT COMPLETE',len(cost),flush=True)
