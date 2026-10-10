"""Fixture-first B2: >=3 body-size lines; >=80% with >=4 words; >=2 sentence endings; no axes/rotation; <=3 numeric label lines."""
import pytest
from .pdf_fixtures import write_pdf
from .r_lite_1_fixtures import text,chart_fixture
from matn_reading.read import read_document
from matn_reading.layout import join_hyphenation

def test_b2_prose_sidebar_and_filled_chart_are_separated(tmp_path):
    # Predominantly prose sidebar, vector-heavy border, body-size lines.
    content=text(330,710,'Ordinary body prose outside the sidebar.')
    content+=b'0.9 g 60 490 235 200 re f 0 g\n'
    for x in range(60,281,20):
        for y in range(500,681,20):
            for offset in (0,2,4):content+=f'{x+offset} {y} m {x+offset+1} {y} l S\n'.encode()
    for i,s in enumerate(['Managers ensure accountability with reliable evidence.',
                          'Use accurate data for every important decision.',
                          'Review each process before accepting its results.',
                          'Document all findings for the responsible owner.']):content+=text(72,665-i*15,s)
    page=read_document(write_pdf(tmp_path/'sidebar.pdf',content)).pages[0]
    assert all(b.block_type!='figure' for b in page.blocks if 'Managers' in b.layout.text or 'Use accurate' in b.layout.text)
    chart=read_document(chart_fixture(tmp_path/'filled-chart.pdf')).pages[0]
    assert any(b.block_type=='figure' for b in chart.blocks)
    assert not any(b.block_type=='text' and 'Completion' in b.layout.text for b in chart.blocks)


def test_b2_axis_geometry_rejects_prose_annotations_even_without_numeric_ticks():
    from matn_reading.classify import prose_box
    from matn_reading.layout import Line,Word
    lines=[Line([Word(w,20+j*25,20+i*15,40+j*25,30+i*15,size=10) for j,w in enumerate('This chart annotation ends here.'.split())]) for i in range(3)]
    assert not prose_box((0,0,200,150),lines,10,[(10,10,10,130)])


