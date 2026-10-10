"""Fixture-first B0: no threshold tuning on dev."""
import pytest
from .pdf_fixtures import write_pdf
from .r_lite_1_fixtures import text,chart_fixture
from matn_reading.read import read_document
from matn_reading.layout import join_hyphenation

def test_b0_rotated_reversed_chart_labels_and_body(tmp_path):
    page=read_document(chart_fixture(tmp_path/'chart.pdf')).pages[0]
    body=[b for b in page.blocks if 'Body prose' in b.layout.text]
    assert len(body)==1 and body[0].block_type=='text'
    assert all(b.block_type=='figure' for b in page.blocks if 'Better' in b.layout.text or 'retteB' in b.layout.text)
    assert not any(b.block_type!='figure' and any(w.text in {'0','25','50','75','100'} for l in b.layout.lines for w in l.words) for b in page.blocks)


def test_b0_pdfplumber_grid_chart_stays_figure(tmp_path):
    import pdfplumber
    path=tmp_path/'grid-chart.pdf'
    chart_fixture(path)
    # Regenerate the same chart with a complete grid, detected as a table.
    content=text(72,730,'Body prose remains citable and contains 123.')
    content+=b'0.9 g 70 370 230 260 re f 0 g\n'
    for y in range(390,611,20):content+=f'80 {y} m 280 {y} l S\n'.encode()
    for x in range(80,281,40):content+=f'{x} 390 m {x} 610 l S\n'.encode()
    content+=text(90,400,'25')+text(130,420,'50')
    content+=b'BT /F1 10 Tf 0 1 -1 0 100 430 Tm (Completion Rate) Tj ET\n'
    content+=b'BT /F1 10 Tf -1 0 0 -1 240 450 Tm (Higher is Better) Tj ET\n'
    write_pdf(path,content)
    with pdfplumber.open(path) as pdf:assert pdf.pages[0].find_tables()
    page=read_document(path).pages[0]
    chart=[b for b in page.blocks if any(w.vertical or w.text in {'25','50'} for l in b.layout.lines for w in l.words)]
    assert chart and all(b.block_type=='figure' for b in chart)
    assert any(b.block_type=='text' and 'Body prose' in b.layout.text for b in page.blocks)


