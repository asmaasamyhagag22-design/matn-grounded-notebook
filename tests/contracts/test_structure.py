import math
import pytest
from pydantic import ValidationError
from matn_contracts.structure import BBoxRef, OffsetSpan, NumberTokenRef, Table, TableCell
from matn_contracts.structure_ids import structure_id

DOC='sha256-'+'a'*64

def test_boxes_and_typed_separators_fail_closed():
    with pytest.raises(ValidationError):
        BBoxRef(coordinates=(0,0,math.nan,2),bbox_precision='word')
    with pytest.raises(ValidationError):
        BBoxRef(coordinates=(0,0,2,2),bbox_precision='char',invented=True)
    assert OffsetSpan(kind='separator',start=0,end=2,separator='\n\n').block_id is None
    with pytest.raises(ValidationError):
        OffsetSpan(kind='separator',start=0,end=2,separator='\n\n',block_id='x',char_start=0,char_end=2)
    with pytest.raises(ValidationError):
        OffsetSpan(kind='primary',start=0,end=2,block_id='x',char_start=0,char_end=1)

def test_digital_and_ocr_dispositions_are_distinct():
    box=BBoxRef(coordinates=(0,0,2,2),bbox_precision='word')
    common=dict(text='12',pdf_page_index=0,block_id='x',start=0,end=2,bbox=box,reader_ref='r:0',reader1='12')
    digital=NumberTokenRef(**common,reader_source='digital',status='digital')
    ocr=NumberTokenRef(**common,reader_source='ocr',status='accepted',reader_status='agreed',reader2='12',reader_bbox=box)
    assert digital.status != ocr.status
    with pytest.raises(ValidationError):
        NumberTokenRef(**common,reader_source='digital',status='accepted')
    with pytest.raises(ValidationError):
        NumberTokenRef(**common,reader_source='ocr',status='flagged-unlinked')

def test_table_identity_and_grid_are_validated():
    box=BBoxRef(coordinates=(0,0,2,2),bbox_precision='region')
    cell=TableCell(row=0,col=0,text='12',bbox=box,source_spans=())
    data=dict(doc_id=DOC,pdf_page_index=0,bbox=box,block_ids=('b',),structure='available',rows=1,cols=1,cells=(cell,))
    table=Table.create(**data)
    assert table.table_id.startswith(DOC+':t:')
    with pytest.raises(ValidationError): Table.create(**{**data,'cells':(cell,cell)})
    with pytest.raises(ValidationError): Table.create(**{**data,'structure':'unavailable'})
    assert structure_id(DOC,'s','v1',['a'])==structure_id(DOC,'s','v1',['a'])
    assert structure_id(DOC,'s','v1',['a'])!=structure_id(DOC,'s','v2',['a'])
