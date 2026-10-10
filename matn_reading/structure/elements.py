"""Exact Block text with conservative source geometry and unchanged reader verdicts."""
import re
import unicodedata
from matn_contracts.domain import Block
from matn_contracts.structure import Element,BlockSpan,NumberTokenRef,StructureIssue,BBoxRef
from matn_reading.ocr.numbers import NUMBER_PATTERN, normalize
from .geometry import box_ref,inside


def normalized_spans(text):
    """Normalization-to-original ledger; no normalized offsets index raw text."""
    chars=[];positions=[]
    for i,ch in enumerate(text):
        out=normalize(ch)
        if ch.isspace(): out=' '
        for c in out: chars.append(c);positions.append(i)
    norm=''.join(chars)
    for m in NUMBER_PATTERN.finditer(norm):
        yield m.group(),positions[m.start()],positions[m.end()-1]+1


def word_ledger(record):
    """Frozen line joining with a parallel character->word ledger."""
    text='';mapping=[];words=[]
    for line in record['lines']:
        line_text='';line_map=[]
        for w in line['words']:
            index=len(words);words.append(w)
            if line_text: line_text+=' ';line_map.append(index)
            line_text+=w['text'];line_map.extend([index]*len(w['text']))
        # Match LayoutBlock.finish strip + join_hyphenation without editing reader.
        start=len(line_text)-len(line_text.lstrip());end=len(line_text.rstrip())
        line_text=line_text[start:end];line_map=line_map[start:end]
        if not text: text=line_text;mapping=line_map;continue
        if text.endswith('-') and len(text)>=2 and line_text:
            if text[-2].isalpha() and line_text[0].islower(): text=text[:-1]+line_text;mapping=mapping[:-1]+line_map;continue
            if text[-2].isalnum() and (line_text[0].isdigit() or line_text[0].isupper()): text+=line_text;mapping+=line_map;continue
        text+=' '+line_text;mapping+=[line_map[0] if line_map else mapping[-1]]+line_map
    return text,mapping,words


def build_elements(snapshot):
    elements=[];issues=[]
    for page in snapshot['pages']:
        used=set()
        for record in page['blocks']:
            block=Block.model_validate(record['block']);role=block.block_type.value
            flags=[f['kind'] for f in page['flags'] if f.get('bbox') and inside(f['bbox'],block.bbox) and inside(block.bbox,f['bbox'])]
            reasons=[]
            if block.visibility.value!='visible': reasons.append(block.visibility.value)
            if role in ('header','footer','figure'): reasons.append('figure_text' if role=='figure' else role)
            if any(k in flags for k in ('marginalia','figure_text','vertical_text')): reasons.extend(k for k in flags if k in ('marginalia','figure_text','vertical_text'))
            if role in ('header','footer') and re.fullmatch(r'\s*[\divxlcdmIVXLCDM]+\s*',block.text): reasons.append('page_number')
            joined,mapping,words=word_ledger(record)
            # Tables can contain reader-created pipes/newlines; geometry is honestly region precision.
            source=[]
            if block.text:
                if joined==block.text:
                    start=0
                    while start<len(mapping):
                        end=start+1
                        while end<len(mapping) and mapping[end]==mapping[start]: end+=1
                        source.append(BlockSpan(block_id=block.block_id,start=start,end=end,boxes=(box_ref(words[mapping[start]]['bbox'],'word',page),)))
                        start=end
                else:
                    source=[BlockSpan(block_id=block.block_id,start=0,end=len(block.text),boxes=(box_ref(block.bbox,'region',page),))]
                    issues.append(StructureIssue(reason='region_precision_text_alignment',pdf_page_index=block.page_index,block_id=block.block_id))
            numbers=[]
            # Source word token ledger for exact digital numeric provenance and OCR placement.
            candidate_words=[]
            for w in words:
                for token,_,_ in normalized_spans(w['text']): candidate_words.append((token,w))
            digital_used=set()
            for token,start,end in normalized_spans(block.text):
                candidates=[(j,w) for j,(value,w) in enumerate(candidate_words) if value==token and j not in digital_used]
                w=candidates[0][1] if candidates else None
                if candidates: digital_used.add(candidates[0][0])
                geometry=box_ref(w['bbox'],'word',page) if w else box_ref(block.bbox,'region',page)
                common=dict(text=token,pdf_page_index=block.page_index,block_id=block.block_id,start=start,end=end,bbox=geometry)
                if page.get('ocr'):
                    matches=[(j,t) for j,t in enumerate(page['ocr']['tokens']) if j not in used and t['token']==token and inside(t['bbox'],w['bbox'] if w else block.bbox)]
                    if len(matches)==1:
                        j,t=matches[0];used.add(j)
                        numbers.append(NumberTokenRef(**common,reader_source='ocr',status='flagged' if t['flagged'] else 'accepted',reader_ref=f"{snapshot['cache_key']}:p{block.page_index}:n{j}",reader_status=t['status'],reader1=t['token'],reader2=t.get('reader2'),reasons=tuple(t['reasons']),reader_bbox=BBoxRef(coordinates=tuple(t['bbox']),bbox_precision='word',frame='reader_points',interpolated=True)))
                    else:
                        numbers.append(NumberTokenRef(**common,reader_source='ocr',status='flagged-unlinked',reasons=('no_unique_reader_token',)))
                else:
                    if w is None: raise ValueError(f'DIGITAL_NUMBER_UNPLACED:{block.page_index}:{block.block_id}:{token}')
                    numbers.append(NumberTokenRef(**common,reader_source='digital',status='digital',reader_ref=f"{snapshot['cache_key']}:p{block.page_index}:b{block.reading_order}:n{start}",reader1=token))
            elements.append(Element(block=block,role=role,citable=not reasons,exclusion_reasons=tuple(dict.fromkeys(reasons)),flags=tuple(sorted(set(flags))),source_spans=tuple(source),number_tokens=tuple(numbers),bbox=box_ref(block.bbox,'region',page),reader_frame='deskewed_points' if page.get('ocr') else 'pdf_points'))
    return tuple(elements),tuple(issues)
