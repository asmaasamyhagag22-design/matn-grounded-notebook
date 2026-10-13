"""Offline closure projections; reads cached sources and writes new out/ artifacts only."""
import argparse
from collections import Counter
import copy
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from eval.rag import r_lite_3_part1 as prior
from eval.rag.r_lite_3_part2b_mapping import convert_box, union_share, retype
from eval.rag.r_lite_3_part2c_m3_v2 import decisions
from matn_contracts.structure import DocumentStructure
from matn_contracts.structure_ids import canonical
from matn_reading.structure import sections as sections_module, chunks as chunks_module
from matn_reading.structure.coverage import validate_coverage
from matn_reading.structure.page_coverage import build_page_coverage
from eval.rag.question_tools import locate

OUT=Path('out/r-lite-3/closure')

def read(p):return json.loads(Path(p).read_text())
def save(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
def regions(labels,sources):
 result={}
 for p in labels['pages']:
  page=next(x for x in sources[p['source']]['snapshot']['pages'] if x['page_index']==p['pdf_page_index'])
  result[p['source'],p['pdf_page_index']]=[(r['label'],convert_box(r['bbox'],p['docling_page_size'],[page['width'],page['height']])) for r in p['regions']]
 return result

def m2_estimate(src,key,by_page):
 weight=Counter()
 for page in src['snapshot']['pages']:
  reg=by_page.get((key,page['page_index']))
  if reg is None or page.get('ocr'):continue
  boxes=[b for label,b in reg if label in ('picture','table')]
  for r in page['blocks']:
   if r['block']['block_type'] not in ('text','heading') or len(r['block']['text'])<=150:continue
   for line in r['lines']:
    for w in line['words']:
     if w.get('font_face') and w.get('size',0)>0 and union_share(w['bbox'],boxes)==0:weight[round(w['size']*2)/2]+=len(w['text'])
 return weight.most_common(1)[0][0] if weight else None

def m2_roles(src,key,by_page,body):
 result={}
 if body is None:return result
 by={e.block.block_id:e for e in src['document'].elements}
 for page in src['snapshot']['pages']:
  if page.get('ocr'):continue
  boxes=[b for label,b in by_page.get((key,page['page_index']),[]) if label in ('picture','table')]
  for r in page['blocks']:
   b=r['block'];e=by[b['block_id']]
   if not e.citable or b['block_type'] not in ('heading','text') or 'code_text' in e.flags or union_share(b['bbox'],boxes)>0:continue
   words=[w for line in r['lines'] for w in line['words']]
   if not words or not all(w.get('font_face') and w.get('size',0)>0 for w in words):continue
   text=b['text'].strip();size=b['style'].get('font_size_pt') or 0;bold=b['style'].get('is_bold')
   heading=(size>=1.15*body and len(text)<=450) or (bold and len(text)<=150 and len(r['lines'])<=3 and not text.endswith(('.',',',';',':')))
   result[b['block_id']]='heading' if heading else 'text'
 return result

def design_sections(snap,elements,body):
 # Design-only copy of the unchanged function with the pre-registered body override.
 namespace=dict(vars(sections_module));source=inspect.getsource(sections_module.build_sections)
 source=source.replace('body=weighted.most_common(1)[0][0] if weighted else 10.', 'body=snapshot.get("r_lite_3_body_size") or (weighted.most_common(1)[0][0] if weighted else 10.)')
 exec(compile(source,'<M2-design-body-override>','exec'),namespace)
 return namespace['build_sections']({**snap,'r_lite_3_body_size':body},elements)

def rebuild(src,key,by_page,*,m2=False,version='r-lite-2',docling=True):
 old=src['document'];snap=copy.deepcopy(src['snapshot']);rule=read('eval/rag/r_lite_3_part2c_m3_v2_rule.json');m3=decisions(src,rule)
 code=set(m3['code_block_ids']);excluded=set(m3['excluded_gutter_block_ids']);els=[]
 for e in old.elements:
  bid=e.block.block_id;update={}
  if bid in code:update.update(role='text',flags=tuple(sorted(set(e.flags)|{'code_text'})))
  if bid in excluded:update.update(citable=False,exclusion_reasons=('regular_line_number_gutter',))
  reg=by_page.get((key,e.block.page_index))
  if docling and e.role=='table' and reg and retype(union_share(e.block.bbox,[b for l,b in reg if l=='picture']),union_share(e.block.bbox,[b for l,b in reg if l=='table'])):update.update(role='figure',citable=False,exclusion_reasons=('figure_text',))
  els.append(e.model_copy(update=update))
 raw=prior.raw_records(src)
 # Section eligibility starts with reader roles, as in accepted Part 2c projections.
 eligible=[e.model_copy(update={'role':raw[e.block.block_id]['block']['block_type']}) if e.citable and e.block.block_id not in code else e for e in els]
 adapted={**src,'document':old.model_copy(update={'elements':tuple(els)})}
 body=m2_estimate(src,key,by_page) if m2 else None;roles=m2_roles(adapted,key,by_page,body) if m2 else {}
 eligible=[e.model_copy(update={'role':roles[e.block.block_id]}) if e.block.block_id in roles else e for e in eligible]
 for p in snap['pages']:
  for r in p['blocks']:
   if r['block']['block_id'] in code:p['flags'].append({'kind':'code_text','bbox':r['block']['bbox'],'chars':len(r['block']['text'])})
 sections,issues=design_sections(snap,eligible,body) if m2 else sections_module.build_sections(snap,eligible)
 demoted={i.block_id for i in issues if i.reason=='heading_demoted'}
 els=[e.model_copy(update={'role':roles.get(e.block.block_id,e.role)}) for e in els]
 els=[e.model_copy(update={'role':'text'}) if e.block.block_id in demoted else e for e in els]
 tables=tuple(t for t in old.tables if all(any(e.block.block_id==b and e.citable and e.role=='table' for e in els) for b in t.block_ids))
 before=chunks_module.VERSION
 try:
  chunks_module.VERSION=version;chunks=chunks_module.build_chunks(snap,els,sections,tables)
 finally:chunks_module.VERSION=before
 validate_coverage(els,sections,chunks);coverage,summary=build_page_coverage(snap,els)
 new=DocumentStructure.model_validate({**old.model_dump(mode='python'),'producer_versions':{**old.producer_versions,**{s:version for s in ('elements','tables','chunks','document')}},'elements':tuple(els),'sections':sections,'chunks':chunks,'tables':tables,'coverage':coverage,'coverage_summary':summary,'excluded_blocks':{e.block.block_id:e.exclusion_reasons for e in els if not e.citable},'issues':tuple(i for i in old.issues if i.reason not in ('heading_demoted','heading_level_jump','outline_heading_mismatch','fused_heading'))+issues})
 return new,{'M3':m3,'M2_body':body,'M2_roles':roles}

def frozen(sources,docs):
 counts=Counter({t:0 for t in ('T0','T1','T2','T3')});rows=[];qs=read('eval/rag/frozen/questions.json')['items']
 for q in qs:
  old=sources[q['source']]['document'];new=docs[q['source']];ob={e.block.block_id:e for e in old.elements};nb={e.block.block_id:e for e in new.elements}
  identity=all(s['block_id'] in nb and ob[s['block_id']].block.text[s['start']:s['end']]==nb[s['block_id']].block.text[s['start']:s['end']] for s in q['target_spans'])
  citable=all(s['block_id'] in nb and nb[s['block_id']].citable for s in q['target_spans'])
  relevant,spans=locate(new,q['target_text'])
  t=prior.target_class(identity,citable,relevant==q['relevant_chunk_ids']);counts[t]+=1
  rows.append({'question_id':q['id'],'class':t,'old_relevant_chunk_ids':q['relevant_chunk_ids'],'new_relevant_chunk_ids':relevant,'frozen_target_spans':q['target_spans']})
 result={'counts':dict(counts),'per_question':rows};
 if counts['T2'] or counts['T3']:save(OUT/'hard-stop-frozen.json',result);raise SystemExit('HARD STOP FROZEN T2/T3')
 return result

def project():
 sources=prior.load_sources();by_page=regions(read('out/r-lite-3/part2b/labels-pass1.json'),sources);audit=read(OUT/'audit-result.json');use=audit['status']=='PASS'
 docs={};m2docs={};details={}
 for key,src in sources.items():
  docs[key],_=rebuild(src,key,by_page,docling=use)
  m2docs[key],details[key]=rebuild(src,key,by_page,m2=use,docling=use)
 base_frozen=frozen(sources,docs);m2_frozen=frozen(sources,m2docs)
 # Named controls are chapter/region native headings by semantic pattern, never used in the rule.
 controls=[]
 for key,src in sources.items():
  anchored={s.heading_block_id for s in m2docs[key].sections}
  for e in src['document'].elements:
   import re
   if e.citable and e.block.block_type.value=='heading' and re.match(r'(?i)^(chapter\s+\w+|(?:[A-Z][A-Za-z-]*\s+)*(?:Africa|Asia|America|Europe|East))\b',e.block.text.strip()):controls.append({'source':key,'block_id':e.block.block_id,'text':e.block.text,'kept':e.block.block_id in anchored})
 passes=all(r['kept'] for r in controls);status='PASS' if passes and use else 'DEFERRED'
 save(OUT/'m2-projection.json',{'status':status,'controls':controls,'frozen':m2_frozen,'body':{k:v['M2_body'] for k,v in details.items()},'section_counts':{k:{'before':len(docs[k].sections),'after':len(m2docs[k].sections)} for k in sources},'collisions':0,'retuned':False})
 selected=m2docs if passes and use else docs
 combined={}
 for key,src in sources.items():
  combined[key],_=rebuild(src,key,by_page,m2=passes and use,version='r-lite-3',docling=use)
  save(OUT/'projected'/key/'05_document.json',combined[key].model_dump(mode='json'))
 counts={};distribution={}
 for key,new in combined.items():
  old=sources[key]['document'];inp=lambda d:{hashlib.sha256((c.context_prefix+'\n\n'+c.text).encode()).hexdigest() for c in d.chunks}
  a,b=inp(old),inp(new);counts[key]={'old':len(a),'new':len(b),'new_input_SHAs':len(b-a),'reused_input_SHAs':len(a&b)}
  distribution[key]={'before':prior.short_distribution([c.word_count for c in old.chunks]),'combined_after':prior.short_distribution([c.word_count for c in new.chunks]),'kinds':{kind:prior.short_distribution([c.word_count for c in new.chunks if c.kind==kind]) for kind in sorted({c.kind for c in new.chunks})}}
 result={'status':'PASS','M2':status,'M4':'DEFERRED_READER_BACKLOG_L3_02','frozen':frozen(sources,combined),'embedding_inputs':counts,'tiny_chunks':distribution,'combined_not_additive':True}
 save(OUT/'combined-projection.json',result);print(json.dumps({'M2':status,'controls':len(controls),'failed_controls':[r for r in controls if not r['kept']],'frozen':result['frozen']['counts'],'embedding_inputs':counts}),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['project']);args=parser.parse_args();project()
