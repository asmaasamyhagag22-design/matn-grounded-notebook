"""Offline independent identity proof for R-lite.3; never imported by production."""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

OUT = Path('out/r-lite-3/part1')
DEFINITIONS = {
 'TARGET-PRESERVING': 'a citability or typing change in which every block_id and every in-block character offset stays unchanged.',
 'TARGET-BREAKING': 'any change that splits or merges blocks, changes block text (for example letter-spacing repair), or changes any field that enters the block_id hash (for example a role, if step 1 shows the role is hashed).',
 'T0': 'target block, offsets and citability unchanged; relevant chunk set unchanged.',
 'T1': 'target block and offsets unchanged; relevant chunk set changes only.',
 'T2': 'target block and offsets unchanged but the target becomes non-citable or excluded (the question would become unreachable): retire candidate, owner decision.',
 'T3': 'target block_id or offsets change: target-breaking.'}
TRACE = {
 'doc_id': {'recipe': 'sha256- + SHA256 of exact PDF bytes', 'ref': 'matn_reading/read.py:67'},
 'section_id': {'recipe': 'structure_id(doc,s,section-identity-v2,[source,structural kind,path,anchor]); heading anchor=block_id; window anchor=[parent_id,*page_range]; synthetic opening anchor=parent_id; root anchor=document-root; DUPLICATE_SECTION_ID refusal preserved', 'refs': ['matn_contracts/structure_ids.py:9','matn_contracts/structure_ids.py:27','matn_reading/structure/sections.py:59']},
 'chunk_id': {'recipe': 'structure_id(doc,c,VERSION,[section_id,kind,text,offset_maps excluding primary_chunk_id,table_id,row_range]); canonical sorted-key JSON, UTF8 SHA256 first16hex; context_prefix and neighbors excluded', 'refs': ['matn_reading/structure/chunks.py:8','matn_reading/structure/chunks.py:24','matn_contracts/structure_ids.py:31']},
 'table_ids': {'recipe': 'reader legacy: doc:pNNNN:table:short_hash([doc,page,quantized_bbox]); structure: structure_id(doc,t,producer_version,full canonical model_dump excluding table_id/schema_version), including defaults, cells/provenance/issues', 'refs': ['matn_contracts/ids.py:69','matn_contracts/structure.py:188','matn_contracts/structure.py:212']},
 'offsets': {'recipe': 'Python character indices into exact Block.text; half-open start:end; word spaces/line joins/hyphenation already performed before identity. Digital/OCR choice already performed before assignment. Literal letter spacing remains. Chunk synthetic separators have only chunk offsets and no block offsets; repeated_context resolves primary. NFKC numeric/target search maps back to original offsets; does not change Block.text.', 'refs': ['matn_reading/layout.py:72','matn_reading/layout.py:154','matn_reading/layout.py:357','matn_reading/structure/elements.py:11','matn_reading/structure/chunks.py:13','eval/rag/question_tools.py:8']},
 'frozen_targets': {'fields': ['id','source','question','target_text','target_spans','relevant_chunk_ids','reachable','gold_page_index','split','state','provenance','tokenizer_version','question_kind'], 'span_fields': ['block_id','start','end','primary_chunk_id','pdf_page_index','page_label','bbox'], 'relevant_sets': 'existing locate(document,target_text) enumerates quote_on_page matches; normalized_map maps raw spans and spans_for ignores separators. For candidate structural audit preserve D1 spans and compare coverage/chunk mapping; do not use retrieval ranks.', 'refs': ['eval/rag/question_tools.py:33','eval/rag/question_tools.py:42','eval/rag/finalize_part1.py:27']}}



def recompute_block(b):
    coords=[]
    for v in b['bbox']:
        x=Decimal(str(float(v))).quantize(Decimal('0.1'),rounding=ROUND_HALF_UP)
        coords.append(format(Decimal('0.0') if x==0 else x,'.1f'))
    material=json.dumps([b['doc_id'],b['page_index'],coords,b['text']],ensure_ascii=False,separators=(',',':'))
    digest=hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]
    return f"{b['doc_id']}:p{b['page_index']:04d}:{digest}"


def inventory(sources):
    proof={}
    for name,blocks in sources.items():
        mismatches=[{'stored':b['block_id'],'computed':recompute_block(b)} for b in blocks if b['block_id']!=recompute_block(b)]
        if mismatches:raise ValueError('BLOCK_ID_MISMATCH:'+name+':'+json.dumps(mismatches))
        proof[name]={'count':len(blocks),'matches':len(blocks),'mismatches':[],'block_ids':[b['block_id'] for b in blocks]}
    return proof


def main():
    paths=[]
    for key in ['2601-14525v1','gao-21-519sp','wb-eem-2021-12']:
        paths.extend(sorted(Path('out/r-lite-2',key,'runs').glob('*/00_reading.json')))
        paths.extend(sorted(Path('out/r-lite-2',key,'runs').glob('*/05_document.json')))
    for key in ['statab_1951_part04','nbs_circular_31_e4_1956']:
        paths.extend([Path('out/r-lite-2/real',key,name) for name in ['00_reading.json','05_document.json']])
    paths.extend([Path('out/rag-core/wef-first-run/approved-acquisition/runs/sha256-f25987c0dee6eba2d832f80924b0e926a4705605cbd6a5c5f10323897da31271/00_reading.json'),Path('out/rag-core/section-rebuild/wef-future-of-jobs-2025/05_document.json')])
    sources={}; hashes={}
    for p in paths:
        raw=p.read_bytes();d=json.loads(raw);hashes[str(p)]=hashlib.sha256(raw).hexdigest()
        sources[str(p)]=([r['block'] for page in d['pages'] for r in page['blocks']] if 'elements' not in d else [e['block'] for e in d['elements']])
    result={'definitions':DEFINITIONS,'trace':TRACE,'proof':inventory(sources),'input_sha256':hashes,'recipe':{'inputs_in_order':['doc_id','page_index','quantized_bbox','text'],'bbox':'float -> Decimal(str(value)); 0.1 ROUND_HALF_UP; zero canonicalized 0.0; four .1f strings','serialization':'json.dumps(list, ensure_ascii=False, separators=(comma,colon)); UTF-8; SHA256 first16hex','normalization':'text exact, no whitespace/Unicode normalization','included':{'role_kind':False,'text':True,'bbox':True,'page_index':True,'reader_source_status':False,'OCR_values':False,'producer_versions':False},'OCR_note':'chosen OCR text enters as text; OCR verdicts and alternate values do not','references':['matn_contracts/ids.py:22','matn_contracts/ids.py:35','matn_contracts/ids.py:49','matn_contracts/ids.py:56','matn_contracts/domain.py:64']}}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'identity-inventory.json').write_text(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
    print(json.dumps({k:v['count'] for k,v in result['proof'].items()},indent=2))


if __name__=='__main__':main()
