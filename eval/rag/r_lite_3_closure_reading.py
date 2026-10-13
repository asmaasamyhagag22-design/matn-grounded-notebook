"""Cached-only production reading gates and independent process byte comparison."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
from matn_contracts.structure import DocumentStructure
from matn_reading.structure.document import write_structure
from eval.reading.r_lite import assert_gates,quote_coverage,metrics
from eval.rag.r_lite_3_closure import OUT,read,save,frozen
from eval.rag.r_lite_3_part1 import load_sources,DEV,REAL,WEF
FILES=('00_structure_input.json','01_elements.jsonl','02_sections.json','03_tables.json','04_chunks.jsonl','05_document.json','document.json')

def worker(folder):
 sources=load_sources()
 for key,src in sources.items():
  path=OUT/'sidecars'/f'{key}.json';labels=read(path) if path.exists() else None
  d=write_structure(src['snapshot'],Path(folder)/key,layout_sidecar=labels)
  print('STRUCTURE',key,len(d.chunks),flush=True)

def run():
 for folder in ('production','production-replay'):
  if (OUT/folder).exists():raise ValueError('READING_OUTPUT_EXISTS:'+folder)
  subprocess.run([sys.executable,'-m','eval.rag.r_lite_3_closure_reading','worker','--folder',str(OUT/folder)],check=True)
 sources=load_sources();docs={};rows={};hashes={};changed=[]
 for key,src in sources.items():
  first=OUT/'production'/key;second=OUT/'production-replay'/key
  for name in FILES:
   a,b=(first/name).read_bytes(),(second/name).read_bytes();hashes[str(first/name)]=hashlib.sha256(a).hexdigest()
   if a!=b:changed.append(str(first/name))
  d=DocumentStructure.model_validate(read(first/'05_document.json'));docs[key]=d;g=assert_gates(d)
  g['G5']='PASS' if not changed else 'FAIL'
  old={e.block.block_id:e for e in src['document'].elements}
  assert all(e.block.model_dump(mode='json')==old[e.block.block_id].block.model_dump(mode='json') for e in d.elements),'BLOCK_ID_TEXT_OR_OFFSETS_CHANGED'
  rows[key]={'gates':g,'metrics':metrics(d),'Blocks_byte_equal':True,'layout_coverage':'not covered' if key in REAL else 'SHA-bound sparse sidecar; absent pages unknown'}
  if key in DEV:
   data=read(Path('eval/gold/dev')/(key+'.json'));items=data['key_points']+data['key_numbers'] if isinstance(data,dict) else data
   before=quote_coverage(src['document'],items);after=quote_coverage(d,items);oldmiss={r['id'] for r in before['missing']};newmiss={r['id'] for r in after['missing']}
   rows[key]['G4']={'status':'PASS' if newmiss<=oldmiss else 'FAIL','before':before,'after':after,'new_miss_ids':sorted(newmiss-oldmiss)}
   g['G4']=rows[key]['G4']['status']
  if key in REAL:
   assert [(e.block.block_id,e.role,e.citable,e.number_tokens) for e in d.elements]==[(e.block.block_id,e.role,e.citable,e.number_tokens) for e in src['document'].elements],'REAL6_SEMANTICS_CHANGED'
 total=sum(r['G4']['after']['total']-len(r['G4']['after']['missing']) for r in rows.values() if 'G4' in r);assert total>=68,'G4_BELOW_68_OF_73'
 fr=frozen(sources,docs);save(OUT/'production-frozen.json',fr)
 status='PASS' if not changed and all(v=='PASS' for r in rows.values() for v in r['gates'].values()) else 'FAIL'
 result={'status':status,'sources':rows,'byte_determinism':{'processes':2,'files':len(hashes),'changed':changed,'SHA256':hashes},'G4_seen':{'covered':total,'total':73,'new_misses':sum(len(r['G4']['new_miss_ids']) for r in rows.values() if 'G4' in r)},'frozen':fr['counts'],'G_R1_G_R2':'NOT_APPLICABLE_READER_UNCHANGED','OCR_calls':0,'PDF_reads':0,'M2':'DEFERRED','M4':'DEFERRED'}
 save(OUT/'reading-gates.json',result);print(json.dumps({'status':status,'G4':result['G4_seen'],'frozen':fr['counts'],'bytes_changed':changed}),flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('stage',choices=['run','worker']);p.add_argument('--folder');a=p.parse_args()
 if a.stage=='worker':worker(a.folder)
 else:run()
