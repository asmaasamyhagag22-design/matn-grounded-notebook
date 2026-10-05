"""Real measurement must use the independent embedded reading, not just display it."""
from contextlib import nullcontext
from types import SimpleNamespace

from PIL import Image


def test_real_runner_passes_embedded_layer_to_reader(monkeypatch, tmp_path):
    from eval.reading import closeout as c
    from eval.reading.real import verify
    from matn_reading.triage import Route
    box=(10,20,30,40)
    data=SimpleNamespace(cropbox=(0,0,612,792),page_label='1',signals=None,
                         words=[SimpleNamespace(text='64',x0=10,top=20,x1=30,bottom=40)])
    class Pdf:
        def __init__(self, path): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def page(self, index): return data
    monkeypatch.setattr(c,'OUT',tmp_path)
    monkeypatch.setattr(c,'specs',lambda subset:[{'doc_id':'mock','page_index':0,'kinds':['table']}])
    monkeypatch.setattr(c,'dev_documents',lambda:[])
    monkeypatch.setattr(c,'RapidOcrWorker',lambda:nullcontext(None))
    monkeypatch.setattr(c,'block_egress',nullcontext)
    monkeypatch.setattr(c,'GlmReader',lambda:None)
    monkeypatch.setattr(c,'OpenPdf',Pdf)
    monkeypatch.setattr(verify,'require_verified',lambda doc:tmp_path/'mock.pdf')
    monkeypatch.setattr(c,'decide_route',lambda signals:(Route.SCANNED_WITH_OCR_LAYER,[]))
    image=Image.new('L',(40,40),'white')
    monkeypatch.setattr(c,'render_page_image',lambda *args:image)
    monkeypatch.setattr(c,'preprocess',lambda *args:(image,{}))
    def read(*args, **kwargs):
        assert kwargs.get('text_layer') == [('64',box)]
        ocr={'preprocess_seconds':0,'tokens':[],'lines':[],'layout':[],'layout_seconds':0,'preprocess':{}}
        return SimpleNamespace(ocr=ocr,flags=[])
    monkeypatch.setattr(c,'read_scan_page',read)
    monkeypatch.setattr(c,'_timing',lambda *args:{})
    monkeypatch.setattr(c,'draw_scan_overlay',lambda *args:image)
    monkeypatch.setattr(c,'write_reading',lambda *args:None)
    monkeypatch.setattr(c,'write_report',lambda *args:None)
    assert c.run('real') == 0
