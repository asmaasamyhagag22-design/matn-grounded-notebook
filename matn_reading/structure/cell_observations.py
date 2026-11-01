"""Explicit source-bound rectangular cell observations, never detector-only numbers."""
from matn_contracts.structure import Table,TableCell,BlockSpan,BBoxRef
from matn_reading.structure.geometry import inside
import hashlib

def sha(data):return hashlib.sha256(data).hexdigest()


def observed_tables(snapshot, elements, observations):
    if observations.get('version')!=1 or observations.get('doc_id')!=snapshot['doc_id']:
        raise ValueError('CELL_OBSERVATION_SOURCE')
    by={e.block.block_id:e for e in elements};tables=[]
    for item in observations['tables']:
        e=by[item['block_id']]
        if not e.citable or e.role!='table':raise ValueError('CELL_LAYOUT_UNCONFIRMED')
        if sha(e.block.text.encode())!=item['block_text_sha256'] or e.block.page_index!=item['page_index']:
            raise ValueError('CELL_BLOCK_IDENTITY')
        cells=[];occupied=set();spans=[]
        for cell in item['cells']:
            a,z=cell['start'],cell['end'];box=tuple(cell['bbox'])
            if not 0<=a<z<=len(e.block.text):raise ValueError('CELL_SPAN_BOUNDS')
            words=[s for s in e.source_spans if s.start<z and a<s.end]
            if not words or any(not inside(b.coordinates,box,1.) or b.bbox_precision not in ('word','char') for s in words for b in s.boxes):
                raise ValueError('CELL_WORD_GEOMETRY')
            numbers=tuple(n for n in e.number_tokens if a<=n.start and n.end<=z)
            if any(n.status not in ('digital','accepted') for n in numbers):raise ValueError('CELL_NUMBER_UNCERTAIN')
            row,col=cell['row'],cell['col'];rs=cell.get('row_span',1);cs=cell.get('col_span',1)
            for r in range(row,row+rs):
                for c in range(col,col+cs):
                    if (r,c) in occupied:raise ValueError('CELL_GRID_OVERLAP')
                    occupied.add((r,c))
            ref=BlockSpan(block_id=e.block.block_id,start=a,end=z,boxes=(BBoxRef(coordinates=box,bbox_precision='region'),))
            cells.append(TableCell(row=row,col=col,row_span=rs,col_span=cs,text=e.block.text[a:z],
                bbox=BBoxRef(coordinates=box,bbox_precision='region'),source_spans=(ref,),numeric_tokens=numbers,
                is_header=row in item['header_rows']))
            spans.append((a,z))
        if occupied!={(r,c) for r in range(item['rows']) for c in range(item['cols'])}:raise ValueError('CELL_GRID_GAP')
        for i,ch in enumerate(e.block.text):
            if not ch.isspace() and sum(a<=i<z for a,z in spans)!=1:raise ValueError('CELL_SOURCE_COVERAGE')
        tables.append(Table.create(doc_id=snapshot['doc_id'],pdf_page_index=e.block.page_index,bbox=e.bbox,
            block_ids=(e.block.block_id,),structure='available',rows=item['rows'],cols=item['cols'],
            header_rows=tuple(item['header_rows']),cells=tuple(cells),producer_version='source-cell-observation-v1'))
    return tables
