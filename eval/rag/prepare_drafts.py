"""Reproduce Part1 WEF draw order and check drafted questions offline.

No PDFs, sealed gold or retrieval code are read. Draft wording is an annotation input.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import random
from matn_contracts.structure import DocumentStructure
from matn_rag.tokenizer import VERSION
from .question_tools import question_checks,spans_for,locate

SEED=20261012


def draw_order(document):
    elements={e.block.block_id:e for e in document.elements}
    bags=defaultdict(list)
    for c in sorted(document.chunks,key=lambda c:c.chunk_id):
        if c.kind not in ('body','table','caption') or not c.primary:continue
        if any(not elements[s.block_id].citable for s in c.primary):continue
        page=min(elements[s.block_id].block.page_index for s in c.primary)
        third=min(2,page*3//len(document.pages))
        bags[(third,c.kind)].append(c)
    rng=random.Random(SEED)
    for key in sorted(bags):rng.shuffle(bags[key])
    result=[]
    while any(bags.values()):
        for key in sorted(bags):
            if not bags[key]:continue
            chunk=bags[key].pop()
            sentences=[]
            for index,s in enumerate(chunk.sentence_spans):
                spans=spans_for(chunk,s.start,s.end)
                sentences.append({'sentence_index':index,'chunk_start':s.start,'chunk_end':s.end,
                    'text':chunk.text[s.start:s.end],'target_spans':spans})
            result.append({'draw_index':len(result),'chunk_id':chunk.chunk_id,'third':key[0],
                'kind':key[1],'context_prefix':chunk.context_prefix,'sentences':sentences})
    return result


def annotate(document,selection):
    order=draw_order(document);by_id={c.chunk_id:c for c in document.chunks}
    elements={e.block.block_id:e for e in document.elements}
    rows=[];skips=[]
    if [c['draw_index'] for c in selection]!=list(range(len(selection))):
        raise ValueError('DRAW_ORDER_GAP_OR_REORDER')
    for choice in selection:
        draw=order[choice['draw_index']]
        if 'skip_reason' in choice:
            skips.append({**draw,'skip_reason':choice['skip_reason']});continue
        sentence=draw['sentences'][choice['sentence_index']];text=sentence['text'];q=choice['question']
        c=by_id[draw['chunk_id']]
        relevant,_=locate(document,text)
        checks=question_checks(q,text)
        if checks['shared_content_4grams']:raise ValueError('QUESTION_4GRAM:'+q)
        spans=sentence['target_spans']
        if not spans or not relevant:raise ValueError('TARGET_UNREACHABLE')
        for span in spans:
            b=elements[span['block_id']].block
            span.update(pdf_page_index=b.page_index,page_label=b.page_label,bbox=list(b.bbox))
        rows.append({'id':f'wef-q-{len(rows)+1:02}','source':'wef-future-of-jobs-2025',
            'question':q,'target_text':text,'target_spans':spans,'target_sentence':
            {'draw_chunk_id':c.chunk_id,'sentence_index':sentence['sentence_index'],
             'start':sentence['chunk_start'],'end':sentence['chunk_end']},
            'relevant_chunk_ids':relevant,'reachable':True,'draw_index':draw['draw_index'],
            'stratum':{'page_third':draw['third'],'kind':draw['kind']},**checks,
            'overlap_ratio_definition':'unique question content tokens also in target / unique question content tokens',
            'provenance':'drafted by model family A','tokenizer_version':VERSION,'state':'draft','split':None})
    if len(rows)!=40:raise ValueError(f'WEF_DRAFT_COUNT:{len(rows)}')
    return {'schema':'matn-rag-question-drafts/1','state':'draft-not-frozen','seed':SEED,
        'draw_method':'chunk_id sort, seeded shuffle each (page third,kind), round-robin nonempty strata; next draw after skips',
        'items':rows,'skips':skips}


def splits_and_sample(rows):
    grouped=defaultdict(list)
    for r in rows:grouped[r['source']].append(r)
    split_rng=random.Random(SEED);sample_rng=random.Random(SEED);sample=[]
    for source in sorted(grouped):
        items=sorted(grouped[source],key=lambda r:r['id'])
        ids=[r['id'] for r in items];split_rng.shuffle(ids)
        tune=set(ids[:len(ids)//2])
        for r in items:r['split']='tune' if r['id'] in tune else 'check'
        sample.extend(sample_rng.sample(items,5))
    return sample


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['draw','annotate'])
    parser.add_argument('--structure',type=Path,required=True)
    parser.add_argument('--selection',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    d=DocumentStructure.model_validate_json(args.structure.read_bytes())
    value=draw_order(d) if args.command=='draw' else annotate(d,json.loads(args.selection.read_text()))
    args.out.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
