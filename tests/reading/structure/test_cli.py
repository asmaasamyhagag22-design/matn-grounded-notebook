from tests.reading.pdf_fixtures import write_pdf
from matn_reading.structure import cli

def test_read_structure_only_no_reader_calls(tmp_path,monkeypatch):
    pdf=write_pdf(tmp_path/'digital.pdf',b'BT /F1 11 Tf 72 690 Td (Growth reached 12 percent.) Tj ET')
    out=tmp_path/'out'
    assert cli.main(['read',str(pdf),'--out',str(out)])==0
    docs=list((out/'runs').glob('*/document.json'));assert len(docs)==1
    before=docs[0].read_bytes()
    def forbidden(*a,**k): raise AssertionError('reader called')
    monkeypatch.setattr(cli,'read_document',forbidden)
    assert cli.main(['read',str(pdf),'--out',str(out),'--structure-only'])==0
    assert docs[0].read_bytes()==before
