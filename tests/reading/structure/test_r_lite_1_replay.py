"""Acquisition must replay cached OCR without constructing an OCR worker."""
import hashlib,json
from types import SimpleNamespace
from pathlib import Path
from matn_reading.structure import cache


def test_acquisition_replays_ocr_before_worker_construction(tmp_path,monkeypatch):
    repo=tmp_path/'reader';repo.mkdir();(tmp_path/'eval').mkdir()
    keys=['2601-14525v1','gao-21-519sp','wb-eem-2021-12'];docs=[];old=tmp_path/'old';expected={}
    for key in keys:
        data=key.encode();(tmp_path/'eval'/key).write_bytes(data);digest=hashlib.sha256(data).hexdigest();doc_id='sha256-'+digest
        docs.append({'doc_id':key,'file':key,'split':'dev','sha256':digest})
        page={'page_index':0,'page_label':None,'width':612.,'height':792.,'cropbox':[0.,0.,612.,792.],'route':'mixed','reasons':['fixture'],'blocks':[],'flags':[],'tables':[],'figure_regions':[],'ocr':{'tokens':[{'token':'12','flagged':True,'status':'uncertain_number'}]}}
        cache.save_snapshot(old/key/'00_reading.json',{'schema_version':1,'doc_id':doc_id,'cache_key':'old','pages':[page]});expected[doc_id]=page
    (tmp_path/'eval/registry.json').write_text(json.dumps({'documents':docs}))
    monkeypatch.setattr(cache,'REPO',repo);monkeypatch.setattr(cache,'core_fingerprint',lambda:'new')
    monkeypatch.setattr(cache,'page_record',lambda p:p)
    def digital(path):
        doc_id='sha256-'+hashlib.sha256(path.read_bytes()).hexdigest();p={**expected[doc_id],'ocr':None}
        return SimpleNamespace(doc_id=doc_id,pages=[p])
    monkeypatch.setattr('matn_reading.read.read_document',digital)
    def forbidden(*a,**k):raise AssertionError('NEW OCR WORKER')
    monkeypatch.setattr('matn_reading.ocr.reader1.RapidOcrWorker',forbidden)
    paths=cache.acquire_dev(tmp_path/'new',reuse_ocr_from=old)
    for p in paths:
        s=cache.load_snapshot(p)
        assert s['pages'][0]==expected[s['doc_id']]
        assert s['ocr_replay']['page_indices']==[0]
        assert s['core_fingerprint']=='new'
