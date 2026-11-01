"""Candidate source copies after blocked drafts; every unit needs native L0–L4.

This never promotes a failed generated sentence. It copies one contiguous source
unit nominated by that draft, retains its original handles, and verifies anew.
An intentional empty answer does not open this path.
"""
import re
from .block_rank import LexicalBlockRanker


def candidates(engine, documents, result):
    by={e.block.block_id:e for d in documents for e in d.elements}
    failed={}
    for attempt in engine.trace:
        if attempt.get('kind') in ('excerpt_fallback','native_source_copy'):continue
        for item in attempt.get('sentences',[]):
            if item.get('receipt',{}).get('status')=='verified':continue
            part=item.get('part')
            if type(part) is not int or not 0<=part<len(engine.parts):continue
            failed.setdefault(part,set()).update(c['block_id'] for c in item.get('citations',[]))
    groups={}
    for key,h in engine.handles.items():
        ids={c['block_id'] for c in h['citations']}
        if len(ids)==1:groups.setdefault(next(iter(ids)),[]).append((key,h))
    for part,blocks in sorted(failed.items()):
        options=[]
        for block in sorted(blocks & groups.keys()):
            rows=sorted(groups[block],key=lambda row:min(c['start'] for c in row[1]['citations']))
            windows=[rows] if len(rows)<=3 else [rows[i:j] for i in range(len(rows)) for j in range(i+1,min(len(rows),i+3)+1)]
            for window in windows:
                refs=sorted((c for _,h in window for c in h['citations']),key=lambda c:c['start'])
                if any(a['end']!=b['start'] for a,b in zip(refs,refs[1:])):continue
                text=by[block].block.text[refs[0]['start']:refs[-1]['end']]
                if len(text)>900:continue
                requested=set(re.findall(r'\d+(?:\.\d+)?%?',engine.parts[part]))
                if not requested<=set(re.findall(r'\d+(?:\.\d+)?%?',text)):continue
                options.append(dict(chunk_id='copy:'+block+':'+str(refs[0]['start'])+':'+str(refs[-1]['end']),block_id=block,text=text,
                    handles=[key for key,_ in window],part=part,
                    section_path=(window[0][1].get('source_sections') or [[]])[0]))
        ranking=LexicalBlockRanker().rank(engine.parts[part],options)
        if ranking:yield {k:ranking[0][k] for k in ('text','handles','part')}


def add_native_copies(engine, documents, result):
    for candidate in candidates(engine,documents,result):
        entry=dict(attempt=len(engine.trace),kind='native_source_copy',sentences=[],timings={'verification_seconds':0.},
            provenance='original_contiguous_retrieved_source_unit_after_blocked_draft',candidate=candidate)
        engine.trace.append(entry)
        values=engine._verify([candidate],entry,documents,result['timings'],result['receipts'])
        item,index=values[0]
        if item['receipt']['status']!='verified':continue
        blocks={c['block_id'] for c in item['citations']}
        # Replace overlapping weaker excerpts; retain every failed receipt.
        result['sentences']=[s for s in result['sentences'] if not (
            any(c['block_id'] in blocks for c in s['citations']) and
            (s.get('kind')=='source_excerpt' or s.get('question_part')==candidate['part']))]
        result['sentences'].append(dict(text=item['text'],handles=item['handles'],citations=item['citations'],receipt_index=index,
            question_part=candidate['part'],kind='source_copy',origin='code_source_unit_fallback',
            verification_scope='native_L0_L4_and_preserved_scope'))
        result['state']='partial_answer'
        result['message']='Verified source copies included; generated paraphrase could not be fully verified. Answer completeness remains unestablished.'
    result['sentences'].sort(key=lambda s:s.get('question_part') if s.get('question_part') is not None else 10**6)
