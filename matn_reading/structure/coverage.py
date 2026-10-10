"""Independent interval coverage, typed reconstruction and citation resolution."""
from collections import Counter,defaultdict


def interval_partition(lengths,spans):
    by_block=defaultdict(list)
    for s in spans:
        if s.block_id not in lengths or s.start<0 or s.start>=s.end or s.end>lengths[s.block_id]: raise ValueError('PRIMARY_OUTSIDE_CITABLE_BLOCK')
        by_block[s.block_id].append((s.start,s.end))
    for bid,length in lengths.items():
        cursor=0
        for start,end in sorted(by_block[bid]):
            if start!=cursor: raise ValueError('PRIMARY_GAP' if start>cursor else 'PRIMARY_OVERLAP')
            cursor=end
        if cursor!=length: raise ValueError('PRIMARY_GAP')


def reconstruct(chunk,texts):
    pieces=[]
    for m in chunk.offset_map:
        piece=m.separator if m.kind=='separator' else texts[m.block_id][m.char_start:m.char_end]
        if len(piece)!=m.end-m.start: raise ValueError('MAP_LENGTH')
        pieces.append(piece)
    return ''.join(pieces)


def resolve_citation(chunk,start,end,chunks):
    if not 0<=start<end<=len(chunk.text): raise ValueError('CITATION_BOUNDS')
    by_id={c.chunk_id:c for c in chunks};result=[]
    for m in chunk.offset_map:
        a=max(start,m.start);z=min(end,m.end)
        if a>=z: continue
        if m.kind=='separator': raise ValueError('SEPARATOR_NOT_CITABLE')
        bs=m.char_start+a-m.start;be=m.char_start+z-m.start
        target=chunk
        if m.kind=='repeated_context':
            target=by_id.get(m.primary_chunk_id)
            if target is None or not any(s.block_id==m.block_id and s.start<=bs and s.end>=be for s in target.primary): raise ValueError('REPEAT_PRIMARY_MISSING')
        result.append({'block_id':m.block_id,'start':bs,'end':be,'primary_chunk_id':target.chunk_id})
    return result


def validate_coverage(elements,sections,chunks):
    citable={e.block.block_id:e for e in elements if e.citable}
    interval_partition({b:len(e.block.text) for b,e in citable.items()},[s for c in chunks for s in c.primary])
    ownership=Counter(b for s in sections for b in s.block_ids)
    if set(ownership)!=set(citable) or any(v!=1 for v in ownership.values()): raise ValueError('LEAF_OWNERSHIP')
    by_section={s.section_id:s for s in sections};texts={e.block.block_id:e.block.text for e in elements}
    for c in chunks:
        if c.section_id not in by_section: raise ValueError('UNKNOWN_SECTION')
        if reconstruct(c,texts)!=c.text: raise ValueError('ROUND_TRIP')
        mapped_primary=[(m.block_id,m.char_start,m.char_end) for m in c.offset_map if m.kind=='primary']
        if mapped_primary!=[(s.block_id,s.start,s.end) for s in c.primary]: raise ValueError('PRIMARY_MAP_DISAGREEMENT')
        mapped_repeat=[(m.block_id,m.char_start,m.char_end,m.primary_chunk_id) for m in c.offset_map if m.kind=='repeated_context']
        if mapped_repeat!=[(s.block_id,s.start,s.end,s.primary_chunk_id) for s in c.repeated_context]: raise ValueError('REPEAT_MAP_DISAGREEMENT')
        for m in c.offset_map:
            if m.kind=='separator': continue
            if m.block_id not in citable: raise ValueError('LEAKAGE')
            if m.block_id not in by_section[c.section_id].block_ids: raise ValueError('CROSS_SECTION')
            if m.kind=='repeated_context': resolve_citation(c,m.start,m.end,chunks)
        for n in c.numeric_tokens:
            matches=[t for t in citable[n.block_id].number_tokens if t.start==n.start and t.end==n.end]
            if len(matches)!=1 or n.model_dump(exclude={'chunk_start','chunk_end'})!=matches[0].model_dump(exclude={'chunk_start','chunk_end'}): raise ValueError('NUMBER_LEDGER')
            if not any(m.block_id==n.block_id and m.char_start<=n.start and m.char_end>=n.end for m in c.offset_map if m.kind!='separator'): raise ValueError('NUMBER_MAP')
    return True
