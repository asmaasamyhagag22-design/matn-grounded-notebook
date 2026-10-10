"""P1 GAO tune p8–11: filled prose cells divert, table serializer copies them."""
import pytest
from .pdf_fixtures import write_pdf
from .r_lite_1_fixtures import text
from matn_reading.read import read_document
from matn_reading.structure.cache import page_record
from matn_reading.structure.elements import word_ledger


def diverted_cells(path):
    content=b''.join(text(72,750-i*14,'Ordinary outside prose has enough words to establish eleven point body.',size=11) for i in range(4))
    content+=b'0.9 g 70 410 230 180 re f 0 g\n'
    content+=b'70 410 460 250 re S 300 410 m 300 660 l S 70 590 m 530 590 l S\n'
    content+=text(82,630,'Practice framework',size=16)
    for i,s in enumerate(['1.1 Clear goals protect every decision.', 'Define sound processes with reliable evidence.', 'Assign roles before accepting new results.', 'Review the system for responsible use.']):
        content+=text(82,565-i*20,s,size=11)
    content+=text(320,630,'Other category',size=16)
    return write_pdf(path,content)


@pytest.mark.xfail(strict=True,reason='M3: serializer copies diverted cell text without its collected-word ledger')
def test_table_block_never_copies_text_from_another_source_block(tmp_path):
    p=read_document(diverted_cells(tmp_path/'diverted-cells.pdf')).pages[0]
    assert p.tables
    assert any(b.block_type=='text' and '1.1 Clear goals' in b.layout.text for b in p.blocks)
    records=page_record(p)['blocks']
    assert all(r['block']['text']==word_ledger(r,digital=True)[0] for r in records)
    assert sum('1.1 Clear goals' in r['block']['text'] for r in records)==1
