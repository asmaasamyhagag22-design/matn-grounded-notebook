"""Faithful producer migration fixture: identical evidence, version changes only."""
import pytest
from .conftest import record,snapshot
from matn_reading.structure.document import assemble
from matn_rag.ingest import prepare

def test_r_lite_3_version_and_legacy_ingest():
 d=assemble(snapshot([record('Grounded statement 12.')]))
 assert d.producer_versions['chunks']=='r-lite-3'
 prepare(d)
 legacy=d.model_copy(update={'producer_versions':{**d.producer_versions,'chunks':'r-lite-2'}})
 prepare(legacy)


@pytest.mark.xfail(strict=True,reason='S5a compatibility revision RED: stored-source guard still rejects r-lite-3')
def test_stored_source_accepts_named_versions_and_refuses_unknown():
 import json
 from matn_rag.sqlite import SQLiteRepository
 d=assemble(snapshot([record('Grounded statement 12.')]))
 metadata,rows=prepare(d);repo=SQLiteRepository();repo.create_notebook('fixture')
 sid=repo.add_source('fixture',d.doc_id,metadata,rows)
 repo.validate_selection('fixture',[sid])
 for version in ('r-lite-2','r-lite-3'):
  changed={**metadata,'versions':{**metadata['versions'],'chunker':version}}
  repo.db.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(changed),sid))
  repo.validate_selection('fixture',[sid])
 changed={**metadata,'versions':{**metadata['versions'],'chunker':'unapproved'}}
 repo.db.execute('UPDATE sources SET metadata=? WHERE id=?',(json.dumps(changed),sid))
 with pytest.raises(ValueError,match='STORED_INDEX_VERSION_MISMATCH'):repo.validate_selection('fixture',[sid])
