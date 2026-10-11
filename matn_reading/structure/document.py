"""Validated assembly and inspectable deterministic stage files."""
from datetime import datetime,timezone
import hashlib
import time
from pathlib import Path
from matn_contracts.structure import DocumentStructure,PageGeometry,BBoxRef,Table
from matn_contracts.structure_ids import canonical,SECTION_IDENTITY_VERSION
from .cache import save_snapshot,load_snapshot,core_fingerprint,cache_key,page_record
from .elements import build_elements
from .sections import build_sections
from .tables import build_tables
from .chunks import build_chunks
from .coverage import validate_coverage
from .page_coverage import build_page_coverage
from .versions import VERSION

COORDINATES='PDF points; MediaBox top-left origin; x right, y down; per-page cropbox and size; OCR inverse deskew applied; bbox_precision explicit'


def prepare_snapshot(snapshot,pdf_path):
    """Cache additive metadata and cell observations once; preserve reader Blocks."""
    from .pdf_metadata import read_metadata
    metadata=read_metadata(pdf_path)
    result={**snapshot,**metadata}
    if not result['title']: result['title']=snapshot['title']
    elements,_=build_elements(result)
    result['table_structures']=[t.model_dump(mode='json') for t in build_tables(result,elements,pdf_path)]
    return result


def assemble(snapshot):
    elements,ei=build_elements(snapshot);sections,si=build_sections(snapshot,elements)
    demoted={i.block_id for i in si if i.reason=='heading_demoted'}
    elements=tuple(e.model_copy(update={'role':'text','flags':e.flags+('heading_demoted',)}) if e.block.block_id in demoted else e for e in elements)
    tables=tuple(Table.model_validate(t) for t in snapshot['table_structures']) if 'table_structures' in snapshot else build_tables(snapshot,elements)
    chunks=build_chunks(snapshot,elements,sections,tables)
    validate_coverage(elements,sections,chunks)
    meta={p['page_index']:p for p in snapshot.get('pdf_metadata_pages',[])}
    pages=tuple(PageGeometry(pdf_page_index=p['page_index'],page_label=p['page_label'],width=p['width'],height=p['height'],cropbox=BBoxRef(coordinates=tuple(p['cropbox']),bbox_precision='region'),rotation=meta.get(p['page_index'],{}).get('rotation',0),route=p['route']) for p in snapshot['pages'])
    coverage,summary=build_page_coverage(snapshot,elements)
    return DocumentStructure(coverage=coverage,coverage_summary=summary,doc_id=snapshot['doc_id'],title=snapshot['title'],producer_versions={**{s:VERSION for s in ('elements','tables','chunks','document')},'sections':SECTION_IDENTITY_VERSION},reader_fingerprint=snapshot['core_fingerprint'],coordinate_convention=COORDINATES,pages=pages,elements=elements,sections=sections,tables=tables,chunks=chunks,excluded_blocks={e.block.block_id:e.exclusion_reasons for e in elements if not e.citable},issues=ei+si)


def write_structure(snapshot,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);started=time.perf_counter();stamp=datetime.now(timezone.utc).isoformat()
    document=assemble(snapshot)
    files={
      '01_elements.jsonl':''.join(canonical(e.model_dump(mode='json'))+'\n' for e in document.elements),
      '02_sections.json':canonical([s.model_dump(mode='json') for s in document.sections])+'\n',
      '03_tables.json':canonical([t.model_dump(mode='json') for t in document.tables])+'\n',
      '04_chunks.jsonl':''.join(canonical(c.model_dump(mode='json'))+'\n' for c in document.chunks),
      '05_document.json':canonical(document.model_dump(mode='json'))+'\n'}
    files['document.json']=files['05_document.json']
    for name,content in files.items():
        target=folder/name;tmp=target.with_suffix('.pending');tmp.write_text(content,encoding='utf-8');tmp.replace(target)
    manifest={'schema_version':1,'doc_id':document.doc_id,'started_at':stamp,'completed_at':datetime.now(timezone.utc).isoformat(),'wall_seconds':time.perf_counter()-started,'cache_key':snapshot['cache_key'],'structure_hashes':{n:hashlib.sha256(v.encode()).hexdigest() for n,v in files.items()}}
    (folder/'06_run_manifest.json').write_text(canonical(manifest)+'\n')
    return document


def from_reading(pdf,out,reading,pages):
    fingerprint=core_fingerprint()
    snap={'schema_version':1,'doc_id':reading.doc_id,'title':Path(pdf).stem,'core_fingerprint':fingerprint,'cache_key':cache_key(reading.doc_id,fingerprint),'pages':[page_record(p) for p in pages],'outline':[]}
    snap=prepare_snapshot(snap,pdf);target=Path(out)/'runs'/reading.doc_id
    save_snapshot(target/'00_reading.json',snap)
    return write_structure(snap,target)


def structure_only(out):
    out=Path(out)
    candidates=[out/'00_reading.json'] if (out/'00_reading.json').exists() else sorted((out/'runs').glob('*/00_reading.json'))
    if not candidates: raise ValueError('STRUCTURE_CACHE_MISSING')
    for source in candidates: write_structure(load_snapshot(source),source.parent)
    return candidates


def replay_real(record,doc_id,page_label=None,width=None,height=None):
    """Replay cached OCR words with frozen pure grouping; never invoke inference."""
    from statistics import median
    from matn_reading.layout import Word,group_lines,group_blocks,order_blocks
    from matn_reading.classify import block_type
    from matn_reading.ocr.regions import role as region_role
    from matn_contracts.domain import Block,BlockStyle,ExtractorInfo
    from matn_contracts.enums import BlockType,ExtractionRoute,Visibility
    crop=record['cropbox'];pre=record['preprocess'];dpi=300
    width=width or crop[2]-crop[0];height=height or crop[3]-crop[1]
    heights=[w['bbox'][3]-w['bbox'][1] for l in record['lines'] for w in l['words']];body_height=median(heights) if heights else 10.
    groups={}
    for l in record['lines']:
        for w in l['words']:
            box=w['bbox'];px=[(box[0]-crop[0])*dpi/72,(box[1]-crop[1])*dpi/72,(box[2]-crop[0])*dpi/72,(box[3]-crop[1])*dpi/72]
            semantic=region_role(px,record['layout'])
            if semantic=='vertical_text': semantic='text'
            if l['role'] in ('marginalia','header','footer'): semantic=l['role']
            size=box[3]-box[1];size=body_height if abs(size-body_height)<=0.25*body_height else max(size,0.1)
            groups.setdefault(semantic,[]).append(Word(w['text'],*box,size=size))
    role_blocks=[(b,role) for role,words in groups.items() for b in group_blocks(group_lines(words))]
    ordered=order_blocks([b for b,role in role_blocks],width);roles={id(b):role for b,role in role_blocks};blocks=[]
    body=median(w.size for words in groups.values() for w in words) if groups else 10.
    for order,b in enumerate(ordered):
        kind={'figure_text':'figure','marginalia':'figure','vertical_text':'figure','header':'header','footer':'footer','caption':'caption','table':'table','footnote':'footnote','heading':'heading'}.get(roles[id(b)],block_type(b,body,height,False))
        box=b.bbox;box=(box[0],box[1],max(box[2],box[0]+.01),max(box[3],box[1]+.01))
        contract=Block.create(doc_id=doc_id,page_index=record['page_index'],page_label=page_label,bbox=box,block_type=BlockType(kind),text=b.text,reading_order=order,style=BlockStyle(font_size_pt=None,is_bold=None),extractor=ExtractorInfo(name='matn_reading.ocr',version='rapidocr-3.9.2+PP-OCRv5-mobile-onnx+glm-ocr-bf16'),route=ExtractionRoute.OCR,visibility=Visibility.VISIBLE)
        blocks.append({'block':contract.model_dump(mode='json'),'flagged':False,'lines':[{'words':[{'text':w.text,'bbox':[w.x0,w.top,w.x1,w.bottom],'size':w.size,'bold':w.bold} for w in line.words]} for line in b.lines]})
    # These observations remain in their cached processed frame; elements invert it.
    regions=[[(r['bbox'][0]*72/dpi)+crop[0],(r['bbox'][1]*72/dpi)+crop[1],(r['bbox'][2]*72/dpi)+crop[0],(r['bbox'][3]*72/dpi)+crop[1]] for r in record['layout'] if r['class']=='table']
    return {'page_index':record['page_index'],'page_label':page_label,'width':width,'height':height,'cropbox':crop,'route':'scanned','reasons':['cached real-scan replay'],'blocks':blocks,'flags':record['flags'],'tables':regions,'ocr':{'tokens':record['tokens'],'lines':record['lines'],'layout':record['layout'],'preprocess':pre}}
