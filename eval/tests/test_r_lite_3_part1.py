"""Focused checks for diagnostic predictions, never production reading fixtures."""
from eval.rag.r_lite_3_part1 import scope_counts, target_class, short_distribution


def test_scope_excludes_cover_not_every_ocr_page():
    rows=[{'pdf_page_index':0,'word_counts':{'match':14},'disposition_moves':{},'every_numeric_token':[]},
          {'pdf_page_index':19,'word_counts':{'match':122},'disposition_moves':{},'every_numeric_token':[]}]
    assert scope_counts(rows)['alignment']['match']==136
    assert scope_counts(rows,exclude_cover=True)['alignment']['match']==122


def test_target_taxonomy_prioritizes_breakage_then_exclusion():
    assert target_class(False,False,False)=='T3'
    assert target_class(True,False,False)=='T2'
    assert target_class(True,True,False)=='T1'
    assert target_class(True,True,True)=='T0'


def test_short_counts_use_strict_less_than():
    result=short_distribution([0,1,2,5,10])
    assert result['below']=={'1':1,'2':2,'5':3,'10':4}


def test_monospace_urls_in_early_footnotes_are_protected():
    from types import SimpleNamespace
    from eval.rag.r_lite_3_part1 import mono_blocks
    def element(bid,page):
        return SimpleNamespace(block=SimpleNamespace(block_id=bid,page_index=page),citable=True,role='footnote')
    doc=SimpleNamespace(doc_id='sha256-ad9f9d0d152930510045d485eebb695ab15b8f775e9bfd63313355c591a675d7',elements=[element('url',0),element('code',23)])
    records=[{'block':{'block_id':bid},'lines':[{'words':[{'font_face':'NFKXMZ+NimbusMonL-Regu'}]}]} for bid in ('url','code')]
    assert mono_blocks({'document':doc,'snapshot':{'pages':[{'blocks':records}]}})=={'code'}


def test_evidence_package_refuses_changed_protected_input(tmp_path):
    import hashlib
    import pytest
    from eval.rag.r_lite_3_package import verify_hashes
    path=tmp_path/'source';path.write_bytes(b'17')
    expected={str(path):hashlib.sha256(b'17').hexdigest()}
    assert verify_hashes(expected)==expected
    path.write_bytes(b'7')
    with pytest.raises(ValueError,match='PROTECTED_INPUT_CHANGED'):
        verify_hashes(expected)
