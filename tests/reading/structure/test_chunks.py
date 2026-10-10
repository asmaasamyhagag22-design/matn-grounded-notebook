import pytest
from .conftest import record,snapshot
from matn_reading.structure.elements import build_elements
from matn_reading.structure.sections import build_sections
from matn_reading.structure.chunks import build_chunks
from matn_reading.structure.coverage import validate_coverage,resolve_citation,reconstruct

def make(texts):
    s=snapshot([record(t,order=i) for i,t in enumerate(texts)]);es,_=build_elements(s);secs,_=build_sections(s,es)
    return s,es,secs,build_chunks(s,es,secs,())

def test_glued_boundary_separators_and_non_citable_offsets():
    _,es,secs,chunks=make(['Growth.','The result.'])
    c=chunks[0];assert c.text=='Growth.\n\nThe result.'
    assert reconstruct(c,{e.block.block_id:e.block.text for e in es})==c.text
    validate_coverage(es,secs,chunks)
    separator=next(m for m in c.offset_map if m.kind=='separator')
    with pytest.raises(ValueError,match='SEPARATOR'): resolve_citation(c,separator.start,separator.end,chunks)
    assert resolve_citation(c,0,6,chunks)[0]['start']==0

def test_sentence_overflow_and_neighbor_partition():
    _,es,secs,chunks=make([('word '*351)+'.',('small '*100)+'.',('other '*160)+'.'])
    assert chunks[0].word_count==352 and 'single_sentence_overflow' in chunks[0].flags
    assert chunks[0].next_chunk_id==chunks[1].chunk_id
    validate_coverage(es,secs,chunks)
    assert all(c.word_count<=350 or 'single_sentence_overflow' in c.flags for c in chunks)

from matn_contracts.structure import Table,TableCell,BlockSpan,BBoxRef

def test_table_cell_row_separators_and_repeat_citation():
    s=snapshot([record('LabelValueABCD','table')]);es,_=build_elements(s);secs,_=build_sections(s,es)
    bid=es[0].block.block_id;box=BBoxRef(coordinates=(10,10,200,25),bbox_precision='region')
    cells=tuple(TableCell(row=r,col=c,text=text,bbox=box,source_spans=(BlockSpan(block_id=bid,start=a,end=z),),is_header=r==0) for r,c,text,a,z in [(0,0,'Label',0,5),(0,1,'Value',5,10),(1,0,'AB',10,12),(1,1,'CD',12,14)])
    table=Table.create(doc_id=s['doc_id'],pdf_page_index=0,bbox=box,block_ids=(bid,),structure='available',rows=2,cols=2,header_rows=(0,),cells=cells)
    chunks=build_chunks(s,es,secs,(table,))
    assert chunks[0].text=='Label\tValue\nAB\tCD'
    validate_coverage(es,secs,chunks)
    for m in chunks[0].offset_map:
        if m.kind=='separator':
            with pytest.raises(ValueError,match='SEPARATOR'): resolve_citation(chunks[0],m.start,m.end,chunks)

    texts=['Header ',('word '*300),('more '*300)];text=''.join(texts)
    s=snapshot([record(text,'table')]);es,_=build_elements(s);secs,_=build_sections(s,es);bid=es[0].block.block_id
    cells=[];a=0
    for r,t in enumerate(texts):
        cells.append(TableCell(row=r,col=0,text=t,bbox=box,source_spans=(BlockSpan(block_id=bid,start=a,end=a+len(t)),),is_header=r==0));a+=len(t)
    table=Table.create(doc_id=s['doc_id'],pdf_page_index=0,bbox=box,block_ids=(bid,),structure='available',rows=3,cols=1,header_rows=(0,),cells=tuple(cells))
    chunks=build_chunks(s,es,secs,(table,));assert len(chunks)==2
    validate_coverage(es,secs,chunks)
    repeat=next(m for m in chunks[1].offset_map if m.kind=='repeated_context')
    assert resolve_citation(chunks[1],repeat.start,repeat.end,chunks)[0]['primary_chunk_id']==chunks[0].chunk_id
