"""Visible, non-exclusive loss counts and flag-only layout suspicions.

No detector changes Elements, sections, table cells, chunks or numeric verdicts.
The M2 detector repeats the existing line-gap/visibility/gutter predicates;
missing object metadata is a suspicion, never a repaired sentence.
"""
from collections import Counter
from matn_contracts.structure import PageCoverage,CoverageSummary
from matn_reading.layout import (Word,Line,LayoutBlock,find_gutters,LINE_SPLIT_GAP_EM,
                                SIZE_TOLERANCE_PT)
from matn_reading.classify import PROSE_MIN_WORDS_PER_LINE


def suspected_order_breaks(page,elements):
    by_id={e.block.block_id:e for e in elements}
    rows=[];blocks=[]
    for record in page['blocks']:
        e=by_id[record['block']['block_id']]
        if e.role not in ('text','heading','list_item'):continue
        lines=[]
        for line in record['lines']:
            words=[]
            for data in line['words']:
                w=Word(data['text'],*data['bbox'],size=data.get('size',11),
                       bold=data.get('bold',False),vertical=data.get('vertical',False),
                       visibility=data.get('visibility',e.block.visibility.value),
                       font_face=data.get('font_face',''),text_object_id=data.get('text_object_id'))
                if not w.vertical:rows.append((w,e.block.block_id));words.append(w)
            if words:lines.append(Line(words))
        if lines:blocks.append(LayoutBlock(lines).finish())
    gutters=find_gutters([b for b in blocks if len(b.lines)>1])
    flagged=set()
    # Full comparison avoids dependence on interleaved object output order.
    for i,(left,lid) in enumerate(rows):
        for right,rid in rows[i+1:]:
            if lid==rid:continue
            if right.x0<left.x0:left_w,right_w=right,left
            else:left_w,right_w=left,right
            size=max(left_w.size,right_w.size)
            if abs(left_w.size-right_w.size)>SIZE_TOLERANCE_PT:continue
            if abs(left_w.bottom-right_w.bottom)>0.2*size:continue
            if any(left_w.x1<=a and b<=right_w.x0 for a,b in gutters):continue
            gap=right_w.x0-left_w.x1
            state_change=left_w.visibility!=right_w.visibility
            same_object=(left_w.text_object_id is not None and left_w.text_object_id==right_w.text_object_id)
            unavailable=left_w.text_object_id is None or right_w.text_object_id is None
            if (same_object or unavailable) and (gap>LINE_SPLIT_GAP_EM*size or state_change):
                flagged.update((lid,rid))
    return tuple(sorted(flagged))


def build_page_coverage(snapshot,elements):
    coverage=[]
    for page in snapshot['pages']:
        es=[e for e in elements if e.block.page_index==page['page_index']]
        excluded=Counter();unlinked=Counter()
        possible=[]
        for e in es:
            for reason in e.exclusion_reasons:excluded[reason]+=len(e.block.text.split())
            if (e.role=='figure' and e.block.visibility.value=='visible'
                    and not any(f in e.flags for f in ('marginalia','vertical_text'))
                    and len(e.block.text.split())>=PROSE_MIN_WORDS_PER_LINE):
                possible.append(e.block.block_id)
            for n in e.number_tokens:
                if e.citable and n.status in ('digital-unlinked','flagged-unlinked'):unlinked[n.status]+=1
        suspected=suspected_order_breaks(page,es)
        coverage.append(PageCoverage(pdf_page_index=page['page_index'],
            excluded_words_by_reason=dict(sorted(excluded.items())),
            possible_prose_in_figure_count=len(possible),possible_prose_in_figure_block_ids=tuple(sorted(possible)),
            suspected_order_break_count=len(suspected),suspected_order_break_block_ids=suspected,
            unlinked_numbers_by_disposition=dict(sorted(unlinked.items()))))
    return tuple(coverage),CoverageSummary.from_pages(coverage)
