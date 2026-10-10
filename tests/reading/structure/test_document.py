import pytest
from .conftest import record,snapshot
from matn_reading.structure.document import assemble,write_structure

def test_document_roundtrip_determinism_and_graph(tmp_path):
    s=snapshot([record('Growth 12.'),record('Hidden 99.','text','hidden',order=1)])
    doc=assemble(s)
    assert len(doc.excluded_blocks)==1
    for name in ('one','two'): write_structure(s,tmp_path/name)
    for f in (tmp_path/'one').glob('*'):
        if f.name!='06_run_manifest.json': assert f.read_bytes()==(tmp_path/'two'/f.name).read_bytes()
    with pytest.raises(ValueError):
        type(doc).model_validate({**doc.model_dump(),'excluded_blocks':{}})
