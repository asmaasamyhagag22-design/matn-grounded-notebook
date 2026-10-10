import pytest
from matn_reading.structure.cache import preflight_ocr, save_snapshot, load_snapshot, core_fingerprint

def test_global_cap_before_any_ocr_and_cache_integrity(tmp_path,snap):
    docs=[{'pages':[{'page_index':i,'route':'scanned','reasons':['ink']} for i in range(11)]}]
    with pytest.raises(ValueError,match='OCR_CAP'): preflight_ocr(docs)
    assert len(preflight_ocr([{'pages':docs[0]['pages'][:10]}]))==10
    p=tmp_path/'00_reading.json'; save_snapshot(p,snap)
    assert load_snapshot(p)['doc_id']==snap['doc_id']
    p.write_text(p.read_text().replace('Growth','Changed'))
    with pytest.raises(ValueError,match='CACHE'): load_snapshot(p)
    assert len(core_fingerprint())==64
