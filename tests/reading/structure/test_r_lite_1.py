from .conftest import record,snapshot
from matn_reading.structure.elements import build_elements
from matn_reading.structure.sections import build_sections


def test_a1_inline_bold_and_toc_address_do_not_anchor():
    a=record('Bold','heading');a['block']['style']['is_bold']=True
    b=record('continues this body sentence.',order=1);b['block']['bbox']=[50.,10.,210.,25.]
    b['lines'][0]['words'][0]['bbox']=[50.,10.,210.,25.]
    from matn_contracts.domain import Block
    b['block']=Block.create(**{k:v for k,v in b['block'].items() if k not in ('schema_version','block_id')}).model_dump(mode='json')
    s=snapshot([a,b,record('Chapter 1 ........ 12','heading',order=2),record('1818 H Street NW, Washington DC 20433',order=3)])
    es,_=build_elements(s);secs,issues=build_sections(s,es)
    assert not any(sec.heading_block_id for sec in secs)
    assert any(i.reason=='heading_demoted' and i.block_id==es[0].block.block_id for i in issues)


def test_a2_opening_leaf_uses_parent_title_and_flag():
    s=snapshot([record('1 Results','heading'),record('1.1 Details','heading',order=1)])
    es,_=build_elements(s);secs,_=build_sections(s,es)
    opening=[sec for sec in secs if any(i.reason=='synthetic_opening' for i in sec.issues)]
    assert opening and opening[0].title=='1 Results'
    assert all(sec.title!='Introduction' for sec in secs)


def numeric_table(text,values):
    r=record(text,'table');r['lines']=[{'words':[{'text':t,'bbox':[10.+j*30,10.+i*20,30.+j*30,25.+i*20],'size':11.,'bold':False} for j,t in enumerate(row)]} for i,row in enumerate(values)]
    return snapshot([r])


def test_a3_duplicate_ordinal_links_across_rows():
    es,_=build_elements(numeric_table('12 | 12\n12 | 12',[['12','12'],['12','12']]))
    nums=es[0].number_tokens
    assert len(nums)==4 and all(n.status=='digital' for n in nums)
    assert [n.bbox.coordinates for n in nums]==[(10.,10.,30.,25.),(40.,10.,60.,25.),(10.,30.,30.,45.),(40.,30.,60.,45.)]


def test_a3_count_mismatch_stays_unlinked():
    es,_=build_elements(numeric_table('12 | 12',[['12','12','12']]))
    assert all(n.status=='digital-unlinked' for n in es[0].number_tokens)


def test_a1_demoted_heading_becomes_structure_body_without_editing_reader_block():
    from matn_reading.structure.document import assemble
    s=snapshot([record('Chapter 1 ....... 12','heading')])
    d=assemble(s)
    assert d.elements[0].role=='text'
    assert d.elements[0].block.block_type.value=='heading'
    assert 'heading_demoted' in d.elements[0].flags
