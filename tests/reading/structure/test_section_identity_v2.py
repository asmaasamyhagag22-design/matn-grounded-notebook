"""Real cached WEF geometry and parent/opening identity regressions."""
import json
from pathlib import Path
import pytest
from matn_contracts.structure_ids import structure_id
from matn_reading.structure.elements import build_elements
from matn_reading.structure.sections import build_sections
from .conftest import record,snapshot


def test_real_wef_repeated_table_openings_have_unique_ids():
    s=json.loads((Path(__file__).parent/'fixtures/wef-section-identity.json').read_text())
    elements,_=build_elements(s);sections,_=build_sections(s,elements)
    openings=[n for n in sections if n.parent_id and n.heading_block_id is None]
    assert len([n for n in openings if n.title=='TA B L E A 3 Job taxonomy'])==6
    assert len({n.section_id for n in sections})==len(sections)


def test_opening_owns_parent_heading_but_uses_parent_identity():
    elements,_=build_elements(snapshot([record('1 Results','heading'),record('1.1 Detail','heading',order=1)]))
    sections,_=build_sections(snapshot([record('1 Results','heading'),record('1.1 Detail','heading',order=1)]),elements)
    parent=next(n for n in sections if n.child_ids)
    opening=next(n for n in sections if n.parent_id==parent.section_id and n.heading_block_id is None)
    assert opening.block_ids[0]==parent.heading_block_id
    assert opening.section_id==structure_id(opening.doc_id,'s','section-identity-v2',[opening.source,'synthetic_opening',list(opening.path),parent.section_id])
    assert opening.section_id!=parent.section_id


def test_duplicate_identity_refused_during_construction(monkeypatch):
    import matn_reading.structure.sections as module
    monkeypatch.setattr(module,'structure_id',lambda *args:'forced-collision')
    s=snapshot([record('1 Results','heading'),record('1.1 Detail','heading',order=1)])
    elements,_=build_elements(s)
    with pytest.raises(ValueError,match='DUPLICATE_SECTION_ID'):
        build_sections(s,elements)
