"""Owner-approved exact-set fixtures; default cap test remains unchanged."""
import json
from pathlib import Path
import pytest
from matn_reading.structure.cache import preflight_ocr

ROOT=Path(__file__).resolve().parents[3]
CASES=json.loads((Path(__file__).parent/'fixtures/ocr_approval_cases.json').read_text())

@pytest.mark.parametrize('case',CASES,ids=[c['name'] for c in CASES])
def test_scoped_approval(case):
    snapshot={'doc_id':'sha256-'+case['sha256'],'pages':[
        {'page_index':i,'route':'mixed','reasons':['fixture']} for i in case['routed_indices']]}
    approval=ROOT/'eval/approvals/wef-ocr-2026-10-11.json'
    if case['error']:
        with pytest.raises(ValueError,match=case['error']):
            preflight_ocr([snapshot],approval_file=approval)
    else:
        result=preflight_ocr([snapshot],approval_file=approval)
        assert [p['page_index'] for p in result]==case['routed_indices']


def test_digital_mismatch_stops_before_ocr_worker(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from matn_reading.structure import cli
    from matn_reading.structure.cache import save_snapshot
    pdf=tmp_path/'fixture.pdf';pdf.write_bytes(b'synthetic input')
    page={'page_index':0,'route':'mixed','reasons':['fixture'],'text':'fresh'}
    snapshot={'schema_version':1,'doc_id':'sha256-fixture','pages':[{**page,'text':'saved'}]}
    baseline=tmp_path/'baseline.json';save_snapshot(baseline,snapshot)
    monkeypatch.setattr(cli,'read_document',lambda _:SimpleNamespace(doc_id=snapshot['doc_id'],pages=[page]))
    monkeypatch.setattr(cli,'page_record',lambda p:p)
    def forbidden():
        raise AssertionError('OCR WORKER CONSTRUCTED')
    with pytest.raises(ValueError,match='DIGITAL_MISMATCH'):
        cli.run(pdf,tmp_path/'out',worker_factory=forbidden,compare_digital=baseline)
    manifest=json.loads((tmp_path/'out/acquisition-manifest.json').read_text())
    assert manifest['digital_comparison']['differing_pages']==[0]
    assert manifest['ocr_pages']==[]
