"""A native table Block inside a layout picture must keep identity and lose citability."""
import pytest
from .conftest import record,snapshot,DOC
from matn_reading.structure.document import assemble

CONFIG_SHA='5b5be2882997ae54af119a2831a57d955f20234fe58fc59b36f9c432451196b1'
REVISION='8f39ad3c0b4c58e9c2d2c84a38465abf757272d8'
def sidecar(regions,sha=DOC.removeprefix('sha256-')):
 return {'schema_version':1,'source_sha256':sha,'configuration_sha256':CONFIG_SHA,'model_revision':REVISION,'status':'COMPLETE','pages':[{'pdf_page_index':0,'docling_page_size':[612.,792.],'regions':regions}]}
def region(label):return {'label':label,'bbox':{'l':0.,'t':0.,'r':250.,'b':100.,'coord_origin':'TOPLEFT'}}

@pytest.mark.xfail(strict=True,reason='S5c RED: structure assembler has no SHA-bound label sidecar stage')
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
