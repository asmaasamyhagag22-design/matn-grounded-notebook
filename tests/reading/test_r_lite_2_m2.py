"""P1 WB tune p18: one regular justified text object, no font-face change."""
import pytest
from .pdf_fixtures import write_pdf
from .r_lite_1_fixtures import text
from matn_reading.read import read_document
from matn_reading.pdf_page import OpenPdf


def justified_line(path,bold=False):
    font='F2' if bold else 'F1'
    content=text(72,714,'The source paragraph starts with ordinary body prose.',size=11)
    content+=f'BT /{font} 11 Tf 15 Tw 72 700 Td (The ledger details remain intact) Tj ET\n'.encode()
    content+=text(72,686,'The next line completes this source paragraph.',size=11)
    return write_pdf(path,content)


@pytest.mark.parametrize('bold',[False,True])
@pytest.mark.xfail(strict=True,reason='M2: same-face justified gaps split a single source text object')
def test_same_text_object_justification_preserves_sentence(tmp_path,bold):
    path=justified_line(tmp_path/'justified.pdf',bold)
    with OpenPdf(path) as pdf:
        p=pdf.page(0)
        assert any('ledger details remain' in t.text for t in p.text_objects)
        words=[w for w in p.words if w.text in ('ledger','details','remain')]
        assert all(w.bold==bold for w in words)
        assert any(b.x0-a.x1>1.5*11 for a,b in zip(words,words[1:]))
    p=read_document(path).pages[0]
    assert any('The ledger details remain intact' in b.layout.text for b in p.blocks)


def test_distinct_heading_object_stays_heading(tmp_path):
    content=text(72,720,'Actual section heading','F2',16)
    content+=text(72,700,'Ordinary body sentence follows the section.',size=11)
    p=read_document(write_pdf(tmp_path/'heading.pdf',content)).pages[0]
    assert any(b.block_type=='heading' and b.layout.text=='Actual section heading' for b in p.blocks)
    assert not any('heading Ordinary' in b.layout.text for b in p.blocks)
