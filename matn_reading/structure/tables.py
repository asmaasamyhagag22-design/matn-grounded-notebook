"""Cell extraction inside frozen table regions, without text-strategy recovery."""
from contextlib import nullcontext
import pdfplumber
from matn_contracts.structure import Table,TableCell,BlockSpan,StructureIssue
from matn_reading.ocr.consistency import Cell,check_table_totals
from .geometry import box_ref,inside
from .versions import VERSION


def _source_cell(text,box,elements,used):
    spans=[];numbers=[]
    if not text: return (),()
    matches=[]
    for e in elements:
        pos=0
        while True:
            pos=e.block.text.find(text,pos)
            if pos<0: break
            end=pos+len(text)
            overlapping=[s for s in e.source_spans if s.start<end and s.end>pos]
            # Exact cell string plus word/region placement, never text-only association.
            if (e.block.block_id,pos,end) not in used and all(any(inside(b.coordinates,box,1.) or inside(box,b.coordinates,1.) or (b.bbox_precision=='region' and min(b.coordinates[2],box[2])>max(b.coordinates[0],box[0]) and min(b.coordinates[3],box[3])>max(b.coordinates[1],box[1])) for b in s.boxes) for s in overlapping):
                matches.append((e,pos,end))
            pos+=1
    if len(matches)!=1: raise ValueError('cell_source_ambiguous')
    e,start,end=matches[0];used.add((e.block.block_id,start,end))
    spans=[BlockSpan(block_id=e.block.block_id,start=start,end=end,boxes=(box_ref(box,'region'),))]
    numbers=[n for n in e.number_tokens if n.start>=start and n.end<=end]
    if any(n.status in ('flagged-unlinked','digital-unlinked') for n in numbers): raise ValueError('cell_number_unlinked')
    return tuple(spans),tuple(numbers)


def _digital_cells(page,region,elements):
    crop=page.crop(tuple(region),strict=False)
    found=crop.find_tables()
    if len(found)!=1: raise ValueError('digital_region_table_count')
    table=found[0];texts=table.extract();used=set();cells=[]
    rows=len(texts);cols=max((len(r) for r in texts),default=0)
    header_rows=[];body_started=False
    for r,row in enumerate(table.rows):
        values=texts[r]
        header=not body_started and all(not any(ch.isdigit() for ch in (t or '')) for t in values)
        if header: header_rows.append(r)
        else: body_started=True
        if len(values)!=cols or len(row.cells)!=cols: raise ValueError('ragged_grid')
        for c,(bbox,text) in enumerate(zip(row.cells,values)):
            if bbox is None: raise ValueError('merged_or_missing_cell_bounds')
            text=(text or '').replace('\n',' ')
            spans,numbers=_source_cell(text,bbox,elements,used)
            cells.append(TableCell(row=r,col=c,text=text,bbox=box_ref(bbox,'region'),source_spans=spans,numeric_tokens=numbers,is_header=header))
    return rows,cols,tuple(header_rows),tuple(cells)


def _ocr_cells(page,region,elements):
    words=[]
    for line in page['ocr']['lines']:
        for w in line['words']:
            if inside(w['bbox'],region): words.append(w)
    if not words: raise ValueError('ocr_no_cell_words')
    # Disjoint y-overlap row bands; each word belongs exactly once.
    bands=[]
    for w in sorted(words,key=lambda w:(w['bbox'][1],w['bbox'][0])):
        matches=[row for row in bands if min(min(v['bbox'][3] for v in row),w['bbox'][3])>max(max(v['bbox'][1] for v in row),w['bbox'][1])]
        if len(matches)>1: raise ValueError('ocr_row_assignment_ambiguous')
        if matches: matches[0].append(w)
        else: bands.append([w])
    bands=[sorted(row,key=lambda w:w['bbox'][0]) for row in bands]
    cols=len(bands[0])
    if len(bands)<2 or cols<2 or any(len(row)!=cols for row in bands): raise ValueError('ocr_column_assignment_ambiguous')
    column_boxes=[]
    for c in range(cols):
        left=max(row[c]['bbox'][0] for row in bands);right=min(row[c]['bbox'][2] for row in bands)
        if left>=right: raise ValueError('ocr_column_assignment_ambiguous')
        column_boxes.append((left,right))
    if any(column_boxes[c][1]>=column_boxes[c+1][0] for c in range(cols-1)): raise ValueError('ocr_overlapping_columns')
    used=set();cells=[];headers=[];body_started=False
    for r,row in enumerate(bands):
        header=not body_started and all(not any(ch.isdigit() for ch in w['text']) for w in row)
        if header: headers.append(r)
        else: body_started=True
        for c,w in enumerate(row):
            bbox=box_ref(w['bbox'],'word',page)
            spans,numbers=_source_cell(w['text'],bbox.coordinates,elements,used)
            cells.append(TableCell(row=r,col=c,text=w['text'],bbox=bbox,source_spans=spans,numeric_tokens=numbers,is_header=header))
    return len(bands),cols,tuple(headers),tuple(cells)


def build_tables(snapshot,elements,pdf_path=None):
    result=[];seen=set()
    with pdfplumber.open(pdf_path) if pdf_path else nullcontext(None) as pdf:
        for p in snapshot['pages']:
            candidates=[e for e in elements if e.citable and e.role=='table' and e.block.page_index==p['page_index']]
            regions=list(p.get('tables',[]))
            for e in candidates:
                if not any(inside(e.block.bbox,r) or inside(r,e.block.bbox) for r in regions): regions.append(e.block.bbox)
            regions=list(dict.fromkeys(tuple(r) for r in regions))
            assignments={e.block.block_id:[r for r in regions if inside(e.block.bbox,r,2.) or inside(r,e.block.bbox,2.)] for e in candidates}
            for raw in regions:
                if tuple(raw) in seen: continue
                # Region identity includes page, not geometry alone.
                key=(p['page_index'],tuple(raw))
                if key in seen: continue
                seen.add(key)
                ambiguous=[e for e in candidates if raw in assignments[e.block.block_id] and len(assignments[e.block.block_id])>1]
                owned=[e for e in candidates if assignments[e.block.block_id]==[raw]]
                box=box_ref(raw,'region',p)
                base=dict(doc_id=snapshot['doc_id'],pdf_page_index=p['page_index'],bbox=box,block_ids=tuple(e.block.block_id for e in owned))
                try:
                    if ambiguous: raise ValueError('table_region_assignment_ambiguous:'+','.join(e.block.block_id for e in ambiguous))
                    if not owned: raise ValueError('no_citable_table_blocks')
                    if p.get('ocr'): rows,cols,headers,cells=_ocr_cells(p,raw,owned)
                    elif pdf: rows,cols,headers,cells=_digital_cells(pdf.pages[p['page_index']],raw,owned)
                    else: raise ValueError('digital_cells_not_cached')
                    represented={span.block_id for cell in cells for span in cell.source_spans}
                    if any(e.block.text and e.block.block_id not in represented for e in owned): raise ValueError('table_block_not_in_cells')
                    check_rows=[[Cell(c.text,c.bbox.coordinates) for c in cells if c.row==r] for r in range(rows)]
                    failures=check_table_totals(check_rows)
                    if failures: raise ValueError('table_total_mismatch')
                    result.append(Table.create(producer_version=VERSION,**base,structure='available',rows=rows,cols=cols,header_rows=headers,cells=cells))
                except ValueError as error:
                    result.append(Table.create(producer_version=VERSION,**base,structure='unavailable',unavailable_reason=str(error)))
    return tuple(result)
