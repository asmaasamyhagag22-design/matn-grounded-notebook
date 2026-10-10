"""Whole sentence body chunks; table row groups; typed synthetic separators."""
from matn_contracts.structure import Chunk,OffsetSpan,PrimarySpan,RepeatedContextSpan,SentenceSpan
from matn_contracts.structure_ids import structure_id
from .versions import VERSION,TARGET_WORDS,MAX_WORDS,TINY_WORDS
from .sentences import sentence_spans


def _make(snapshot,section,kind,parts,elements,table_id=None,row_range=None,flags=()):
    text='';maps=[];primary=[];repeats=[];numbers=[];sentences=[]
    for part in parts:
        if 'separator' in part:
            piece=part['separator'];maps.append(OffsetSpan(kind='separator',start=len(text),end=len(text)+len(piece),separator=piece));text+=piece;continue
        bid=part['block_id'];a=part['start'];z=part['end'];e=elements[bid];piece=e.block.text[a:z];offset=len(text)
        if not piece: continue
        repeat=part.get('primary_chunk_id');kind_span='repeated_context' if repeat else 'primary'
        maps.append(OffsetSpan(kind=kind_span,start=offset,end=offset+len(piece),block_id=bid,char_start=a,char_end=z,primary_chunk_id=repeat))
        if repeat: repeats.append(RepeatedContextSpan(block_id=bid,start=a,end=z,primary_chunk_id=repeat))
        else: primary.append(PrimarySpan(block_id=bid,start=a,end=z))
        for n in e.number_tokens:
            if a<=n.start and n.end<=z: numbers.append(n.model_copy(update={'chunk_start':offset+n.start-a,'chunk_end':offset+n.end-a}))
            elif n.start<z and n.end>a: raise ValueError('NUMBER_SPLIT_AT_CHUNK_BOUNDARY')
        for s in sentence_spans(piece): sentences.append(SentenceSpan(start=offset+s.start,end=offset+s.end,flags=s.flags))
        text+=piece
    identity=[section.section_id,kind,text,[m.model_dump(exclude={'primary_chunk_id'}) for m in maps],table_id,row_range]
    return Chunk(producer_version=VERSION,chunk_id=structure_id(snapshot['doc_id'],'c',VERSION,identity),doc_id=snapshot['doc_id'],section_id=section.section_id,
      kind=kind,text=text,context_prefix=snapshot['title']+' / '+' / '.join(section.path),offset_map=tuple(maps),primary=tuple(primary),
      repeated_context=tuple(repeats),sentence_spans=tuple(sentences),numeric_tokens=tuple(numbers),table_id=table_id,row_range=row_range,word_count=len(text.split()),flags=tuple(flags))


def _body(snapshot,section,batch,by_id):
    units=[]
    for e in batch:
        for sentence in sentence_spans(e.block.text): units.append({'block_id':e.block.block_id,'start':sentence.start,'end':sentence.end})
    groups=[];group=[];count=0
    for u in units:
        n=len(by_id[u['block_id']].block.text[u['start']:u['end']].split())
        if group and (count>=TARGET_WORDS or count+n>MAX_WORDS): groups.append(group);group=[];count=0
        group.append(u);count+=n
        if n>MAX_WORDS: groups.append(group);group=[];count=0
    if group:
        if groups and count<TINY_WORDS and count+sum(len(by_id[u['block_id']].block.text[u['start']:u['end']].split()) for u in groups[-1])<=MAX_WORDS: groups[-1]+=group
        else: groups.append(group)
    result=[]
    for group in groups:
        parts=[];last=None
        for u in group:
            if last and last!=u['block_id']: parts.append({'separator':'\n\n'})
            parts.append(u);last=u['block_id']
        flags=('single_sentence_overflow',) if len(group)==1 and len(by_id[group[0]['block_id']].block.text[group[0]['start']:group[0]['end']].split())>MAX_WORDS else ()
        result.append(_make(snapshot,section,'body',parts,by_id,flags=flags))
    return result


def _table(snapshot,section,table,by_id):
    if table.structure=='unavailable':
        parts=[]
        for bid in table.block_ids:
            if parts: parts.append({'separator':'\n'})
            if by_id[bid].block.text: parts.append({'block_id':bid,'start':0,'end':len(by_id[bid].block.text)})
        return [_make(snapshot,section,'table',parts,by_id,table.table_id,flags=('structure_unavailable',))] if parts else []
    # Preserve reader-owned interstitial characters (pipes/whitespace) adjacent
    # to their preceding cell; synthetic tabs/newlines remain separately typed.
    all_spans=sorted([(s.block_id,s.start,s.end,c.row,c.col) for c in table.cells for s in c.source_spans],key=lambda s:(table.block_ids.index(s[0]),s[1]))
    rows={r:[] for r in range(table.rows)};covered={b:[] for b in table.block_ids}
    for i,(bid,a,z,row,col) in enumerate(all_spans):
        previous=all_spans[i-1] if i else None
        if previous is None or previous[0]!=bid: a=0
        nxt=all_spans[i+1] if i+1<len(all_spans) else None
        z=nxt[1] if nxt and nxt[0]==bid else len(by_id[bid].block.text)
        if rows[row]: rows[row].append({'separator':'\t'})
        rows[row].append({'block_id':bid,'start':a,'end':z});covered[bid].append((a,z))
    # Detect cells whose structure omits a full reader block; no silent loss.
    if any(not covered[b] and by_id[b].block.text for b in table.block_ids): raise ValueError('TABLE_BLOCK_NOT_IN_CELLS')
    groups=[];group=[];count=0
    header_count=sum(sum(len(by_id[u['block_id']].block.text[u['start']:u['end']].split()) for u in rows[r] if 'block_id' in u) for r in table.header_rows)
    for r in range(table.rows):
        n=sum(len(by_id[u['block_id']].block.text[u['start']:u['end']].split()) for u in rows[r] if 'block_id' in u)
        if group and count+n>MAX_WORDS: groups.append(group);group=[];count=header_count
        group.append(r);count+=n
    if group: groups.append(group)
    result=[];primary_header={}
    for gi,group in enumerate(groups):
        parts=[]
        render_rows=(list(table.header_rows)+group) if gi else group
        for r in render_rows:
            if parts: parts.append({'separator':'\n'})
            for u in rows[r]:
                if gi and r in table.header_rows and r not in group and 'block_id' in u:
                    target=primary_header.get((u['block_id'],u['start'],u['end']))
                    if target is None: raise ValueError('HEADER_PRIMARY_MISSING')
                    parts.append({**u,'primary_chunk_id':target})
                else: parts.append(u)
        c=_make(snapshot,section,'table',parts,by_id,table.table_id,(min(group),max(group)),flags=('table_row_overflow',) if count>MAX_WORDS else ())
        result.append(c)
        for r in table.header_rows:
            if r in group:
                for u in rows[r]:
                    if 'block_id' in u: primary_header[(u['block_id'],u['start'],u['end'])]=c.chunk_id
    return result


def build_chunks(snapshot,elements,sections,tables):
    by_id={e.block.block_id:e for e in elements};table_by_block={b:t for t in tables for b in t.block_ids};chunks=[]
    leaves=[s for s in sections if not s.child_ids]
    order={e.block.block_id:i for i,e in enumerate(elements)}
    leaves.sort(key=lambda s:min((order[b] for b in s.block_ids),default=10**12))
    for section in leaves:
        batch=[];seen=set();local=[]
        def flush():
            if batch: local.extend(_body(snapshot,section,batch,by_id));batch.clear()
        for bid in section.block_ids:
            e=by_id[bid]
            if e.role in ('caption','footnote'):
                flush()
                if e.block.text: local.append(_make(snapshot,section,e.role,[{'block_id':bid,'start':0,'end':len(e.block.text)}],by_id))
            elif e.role=='table':
                flush();t=table_by_block.get(bid)
                if t and t.table_id not in seen:
                    if any(b not in section.block_ids for b in t.block_ids): raise ValueError('TABLE_CROSSES_SECTION')
                    local.extend(_table(snapshot,section,t,by_id));seen.add(t.table_id)
                elif not t and e.block.text: local.append(_make(snapshot,section,'table',[{'block_id':bid,'start':0,'end':len(e.block.text)}],by_id,flags=('structure_unavailable',)))
            else: batch.append(e)
        flush()
        for i,c in enumerate(local): chunks.append(c.model_copy(update={'prev_chunk_id':local[i-1].chunk_id if i else None,'next_chunk_id':local[i+1].chunk_id if i+1<len(local) else None}))
    if len({c.chunk_id for c in chunks})!=len(chunks): raise ValueError('CHUNK_ID_COLLISION')
    return tuple(chunks)
