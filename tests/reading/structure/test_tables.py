from pathlib import Path
import pytest
from tests.reading.pdf_fixtures import write_pdf
from .conftest import record,snapshot
from matn_reading.structure.elements import build_elements
from matn_reading.structure.tables import build_tables
from matn_reading.structure.cache import page_record
from matn_reading.read import read_document


def test_digital_fixture_exact_cells(tmp_path):
    commands=[]
    for x in (72,172,272): commands.append(f'{x} 600 m {x} 660 l S')
    for y in (600,620,640,660): commands.append(f'72 {y} m 272 {y} l S')
    for y,values in [(648,('Label','Value')),(628,('A','12')),(608,('B','24'))]:
        for x,text in zip((80,180),values): commands.append(f'BT /F1 10 Tf {x} {y} Td ({text}) Tj ET')
    pdf=write_pdf(tmp_path/'cells.pdf',('\n'.join(commands)).encode())
    r=read_document(pdf);s={'schema_version':1,'doc_id':r.doc_id,'title':'fixture','core_fingerprint':'f','cache_key':'k','pages':[page_record(p) for p in r.pages]}
    es,_=build_elements(s);ts=build_tables(s,es,pdf)
    assert len(ts)==1 and ts[0].structure=='available'
    assert [(c.row,c.col,c.text) for c in ts[0].cells]==[(0,0,'Label'),(0,1,'Value'),(1,0,'A'),(1,1,'12'),(2,0,'B'),(2,1,'24')]
    assert ts[0].header_rows==(0,)
    assert all(n.status=='digital' for c in ts[0].cells for n in c.numeric_tokens)

def test_ocr_ambiguous_assignment_unavailable():
    ocr={'tokens':[],'preprocess':{'size':[2550,3300],'rotation_deg':0},'lines':[]}
    s=snapshot([record('A 12 B 24','table',ocr=ocr)],ocr);s['pages'][0]['tables']=[[10,10,200,25]]
    es,_=build_elements(s);tables=build_tables(s,es)
    assert tables[0].structure=='unavailable'
    assert tables[0].unavailable_reason and not tables[0].cells
