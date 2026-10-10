from .conftest import record,snapshot
from matn_reading.structure.elements import build_elements
from matn_reading.structure.sections import build_sections

def test_outline_heading_tree_intro_and_leaf_partition():
    s=snapshot([record('Intro.'),record('1 Results','heading',order=1),record('Growth.',order=2),record('1.1 Detail','heading',order=3),record('More.',order=4)])
    s['outline']=[{'title':'1 Results','page_index':0,'level':0},{'title':'Missing','page_index':0,'level':1}]
    elements,_=build_elements(s);sections,issues=build_sections(s,elements)
    owned=[b for sec in sections for b in sec.block_ids]
    assert sorted(owned)==sorted(e.block.block_id for e in elements)
    assert len(owned)==len(set(owned))
    assert any(sec.source=='outline' for sec in sections)
    assert any(i.reason=='outline_heading_mismatch' for i in issues)
    assert all(not (sec.block_ids and sec.child_ids) for sec in sections)

def test_page_windows_and_fused_heading_findings():
    s=snapshot([record('2.4 Results. '+('word '*50))]);elements,_=build_elements(s)
    sections,issues=build_sections(s,elements)
    assert sections[0].source=='page_window'
    assert any(i.reason=='fused_heading' and i.block_id==elements[0].block.block_id for i in issues)
