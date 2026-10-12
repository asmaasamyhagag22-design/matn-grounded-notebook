"""Independent identity recipe checks; no reading mechanism fixtures."""
import pytest
from matn_contracts.ids import make_block_id
from eval.rag.r_lite_3_identity import recompute_block, inventory


def test_decimal_rounding_and_exact_text():
    b={'doc_id':'sha256-'+'a'*64,'page_index':2,'bbox':[0.05,-0.04,20.15,30.25],'text':'A  B\nC'}
    assert recompute_block(b)==make_block_id(**b)
    assert recompute_block({**b,'text':'A B C'})!=recompute_block(b)


def test_roles_and_verdicts_do_not_enter_hash():
    b={'doc_id':'sha256-'+'a'*64,'page_index':2,'bbox':[1,2,3,4],'text':'17'}
    assert recompute_block({**b,'block_type':'footnote','reader1':'17','reader2':'7'})==recompute_block({**b,'block_type':'text','reader1':'7'})


def test_inventory_refuses_mismatch():
    b={'doc_id':'sha256-'+'a'*64,'page_index':2,'bbox':[1,2,3,4],'text':'17','block_id':'wrong'}
    with pytest.raises(ValueError,match='BLOCK_ID_MISMATCH'):
        inventory({'sample':[b]})
