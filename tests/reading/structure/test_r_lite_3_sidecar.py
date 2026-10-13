"""A native table Block inside a layout picture must keep identity and lose citability."""
import pytest
from .conftest import record,snapshot,DOC
from matn_reading.structure.document import assemble

CONFIG_SHA='5b5be2882997ae54af119a2831a57d955f20234fe58fc59b36f9c432451196b1'
REVISION='8f39ad3c0b4c58e9c2d2c84a38465abf757272d8'
def sidecar(regions,sha=DOC.removeprefix('sha256-')):
 from matn_reading.structure.layout_sidecar import SETTINGS
 import json
 hashes=json.loads(SETTINGS.read_text())['model_files_SHA256']
 return {'schema_version':1,'source_sha256':sha,'configuration_sha256':CONFIG_SHA,'model_revision':REVISION,'model_files_SHA256':hashes,'status':'COMPLETE','pages':[{'pdf_page_index':0,'docling_page_size':[612.,792.],'regions':regions}]}
def region(label):return {'label':label,'bbox':{'l':0.,'t':0.,'r':250.,'b':100.,'coord_origin':'TOPLEFT'}}

def test_picture_retyping_keeps_block_and_offsets():
 r=record('Series 12','table');s=snapshot([r]);d=assemble(s,layout_sidecar=sidecar([region('picture')]))
 e=d.elements[0];assert e.role=='figure' and not e.citable
 assert e.block.model_dump(mode='json')==r['block']
 assert not d.chunks
 veto=assemble(s,layout_sidecar=sidecar([region('picture'),region('table')]))
 assert veto.elements[0].role=='table' and veto.elements[0].citable
 assert assemble(s).elements[0].role=='table'
 with pytest.raises(ValueError,match='SIDECAR_SOURCE_SHA'):
  assemble(s,layout_sidecar=sidecar([region('picture')],sha='c'*64))


def test_subprocess_keeps_venv_entrypoint_when_python_is_a_symlink(tmp_path,monkeypatch):
 import hashlib,json,sys
 from matn_reading.structure import layout_sidecar as stage
 isolated=tmp_path/'isolated'/'bin'/'python';isolated.parent.mkdir(parents=True);isolated.symlink_to(sys.executable)
 artifact=tmp_path/'artifacts';model=artifact/'test--model';model.mkdir(parents=True);(model/'config.json').write_text('{}')
 settings=tmp_path/'settings.json';settings.write_text(json.dumps({'model_repo':'test/model','model_files_SHA256':{'config.json':hashlib.sha256(b'{}').hexdigest()}}))
 monkeypatch.setattr(stage,'SETTINGS',settings);called=[]
 monkeypatch.setattr(stage.subprocess,'run',lambda argv,**kwargs:called.append((argv,kwargs)))
 stage.label_sources(tmp_path/'request.json',tmp_path/'output',python=isolated,artifacts_path=artifact)
 assert called[0][0][0]==str(isolated)
 assert called[0][1]['env']['HF_HUB_OFFLINE']=='1'
 assert called[0][1]['env']['TRANSFORMERS_OFFLINE']=='1'
