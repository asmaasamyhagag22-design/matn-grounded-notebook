"""P1 GAO tune p50/p60: connected filled cells, local10pt/global11pt."""
import pytest
from .pdf_fixtures import write_pdf
from .r_lite_1_fixtures import text,chart_fixture
from matn_reading.read import read_document
from matn_reading.classify import prose_box
from matn_reading.layout import Line,Word


def local_font_cells(path):
    content=b''.join(text(72,750-i*14,'Ordinary outside prose establishes an eleven point body font with many words.',size=11) for i in range(5))
    content+=b'0.9 g 70 410 225 180 re f 305 410 225 180 re f 0 g\n'
    for i,label in enumerate(['1.1','1.2','1.3','1.4']):content+=text(75+i*110,599,label,size=10)
    for x in [80,315]:
        for i,s in enumerate(['Who reviews every important decision?', 'Collect reliable documentation for review.', 'Managers assess results before approval.', 'Record evidence for responsible oversight.']):content+=text(x,565-i*18,s,size=10)
    return write_pdf(path,content)


@pytest.mark.xfail(strict=True,reason='M1: eligible filled prose cells use local10pt, document body11pt')
def test_local_font_filled_cells_remain_prose(tmp_path):
    p=read_document(local_font_cells(tmp_path/'local-font.pdf')).pages[0]
    assert p.figure_regions
    blocks=[b for b in p.blocks if 'Who reviews' in b.layout.text]
    assert len(blocks)==2
    assert all(b.block_type!='figure' for b in blocks)


def test_local_font_chart_annotation_with_axes_stays_figure(tmp_path):
    p=read_document(chart_fixture(tmp_path/'chart.pdf')).pages[0]
    assert any(b.block_type=='figure' for b in p.blocks)
    lines=[Line([Word(w,20+j*25,20+i*15,40+j*25,30+i*15,size=9) for j,w in enumerate('This chart annotation ends here.'.split())]) for i in range(4)]
    assert not prose_box((0,0,200,150),lines,11,[(10,10,10,130)])
