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
