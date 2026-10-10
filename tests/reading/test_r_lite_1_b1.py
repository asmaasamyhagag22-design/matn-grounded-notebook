"""Fixture-first B1: no threshold tuning on dev."""
import pytest
from .pdf_fixtures import write_pdf
from .r_lite_1_fixtures import text,chart_fixture
from matn_reading.read import read_document
from matn_reading.layout import join_hyphenation

@pytest.mark.parametrize('columns',[1,2])
def test_b1_font_weight_line_changes_keep_paragraph_order(tmp_path,columns):
    content=b''
    for x in [72] if columns==1 else [72,330]:
        content+=text(x,714,'Evidence matters.','F2')
        content+=text(x,700,'A body paragraph begins with ordinary')
        content+=text(x,686,'bold words in its middle and then','F2')
        content+=text(x,672,'continues until the sentence ends.')
    page=read_document(write_pdf(tmp_path/'inline.pdf',content)).pages[0]
    blocks=[b for b in page.blocks if 'body paragraph' in b.layout.text]
    assert len(blocks)==columns
    assert all('ordinary bold words in its middle and then continues' in b.layout.text for b in blocks)
    assert all(b.layout.text.startswith('Evidence matters.') for b in blocks)


def test_b1_nonadjacent_bold_pdf_run_rejoins_same_line(tmp_path):
    # PDF emits the main lines before the mid-line bold run. The 17pt face
    # boundary gap straddles the frozen 1.5em line split at 10pt body size.
    content=text(72,700,'This')+text(158,700,'supports every decision.')
    content+=text(72,686,'The next body line completes this paragraph.')
    content+=text(72,640,'An unrelated paragraph follows later.')
    content+=text(108,700,'evidence','F2')
    page=read_document(write_pdf(tmp_path/'late-bold.pdf',content)).pages[0]
    blocks=[b for b in page.blocks if 'supports every decision' in b.layout.text]
    assert len(blocks)==1
    assert 'This evidence supports every decision.' in blocks[0].layout.text
    assert not any(b.layout.text=='evidence' for b in page.blocks)


