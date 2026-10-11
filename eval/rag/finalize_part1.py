"""Recheck existing draft spans, merge WEF drafts and build owner review offline."""
import json
from pathlib import Path
from collections import Counter
from matn_contracts.structure import DocumentStructure
from .question_tools import question_checks,locate
from .build_review import build_review
from .prepare_drafts import splits_and_sample
from matn_rag.tokenizer import VERSION


def run():
    rows=json.load(open('out/rag-core/gold-drafts-preliminary.json'))['items']
    docs={key:DocumentStructure.model_validate_json((Path('out/rag-core/section-rebuild')/key/'05_document.json').read_bytes()) for key in ('2601-14525v1','gao-21-519sp','wb-eem-2021-12')}
    gates=json.load(open('out/rag-core/section-rebuild/gates.json'));rechecks=[]
    for r in rows:
        d=docs[r['source']];relevant,new_spans=locate(d,r['target_text']);checks=question_checks(r['question'],r['target_text'])
        if checks['shared_content_4grams']:raise ValueError('GOLD_DRAFT_4GRAM:'+r['id'])
        if bool(relevant)!=r['reachable']:raise ValueError('GOLD_REACHABILITY_CHANGED:'+r['id'])
        # Preserve original block spans; only update primary chunk references.
        mapping={i['old']:i['new'] for i in gates[r['source']]['changed_ids']}
        elements={e.block.block_id:e for e in d.elements}
        for s in r['target_spans']:
            e=elements[s['block_id']]
            if not e.citable or not 0<=s['start']<s['end']<=len(e.block.text):raise ValueError('TARGET_SPAN_CHANGED')
            s['primary_chunk_id']=mapping[s['primary_chunk_id']]
        r.update(relevant_chunk_ids=relevant,tokenizer_version=VERSION,**checks)
        r['scope_number_roles']=[{'token':n,'role':'question scope (year/fiscal period or training epoch), not requested answer'} for n in r['scope_numbers']]
        rechecks.append({'id':r['id'],'reachable':r['reachable'],'shared_content_4grams':checks['shared_content_4grams'],'relevant_chunk_count':len(relevant),'target_block_offsets':'unchanged'})
    wef=json.load(open('out/rag-core/wef-question-drafts.json'))
    for r in wef['items']:
        r['scope_number_roles']=[{'token':n,'role':'comparison year, not requested answer'} for n in r['scope_numbers']]
    rows+=wef['items'];splits_and_sample(rows)
    path=Path('out/rag-core/question-drafts-final.json');path.write_text(json.dumps({'schema':'matn-rag-question-drafts/1','state':'draft-not-frozen','provenance':'drafted by GPT (Codex)','seed':20261012,'items':rows},indent=2)+'\n')
    Path('out/rag-core/gold-draft-recheck.json').write_text(json.dumps(rechecks,indent=2)+'\n')
    sample=build_review(rows,Path('out/rag-core/owner-review-20.html'))
    profile=set(range(64,76))|set(range(83,89));ocr={0,19,21,32,35,37,65,66,74,75,80,83,85,87}
    summary={'drafts':len(rows),'reachable':sum(r['reachable'] for r in rows),'by_source':dict(Counter(r['source'] for r in rows)),'splits':dict(Counter((r['source']+'/'+r['split']) for r in rows)),'wef_ocr_targets':sum(any(s['pdf_page_index'] in ocr for s in r['target_spans']) for r in wef['items']),'wef_profile_targets':sum(any(s['pdf_page_index'] in profile for s in r['target_spans']) for r in wef['items']),'wef_kinds':dict(Counter(r['stratum']['kind'] for r in wef['items'])),'wef_thirds':dict(Counter(r['stratum']['page_third'] for r in wef['items'])),'wef_skips':len(wef['skips']),'owner_sample':[r['id'] for r in sample],'no_shared_content_4grams':True,'no_freeze_or_retrieval':True}
    Path('out/rag-core/part1-draft-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(summary)

if __name__=='__main__':run()
