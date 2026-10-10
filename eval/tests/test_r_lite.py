from tests.reading.structure.conftest import record,snapshot
from matn_reading.structure.document import assemble
from eval.reading.r_lite import metrics,quote_coverage,overflow_cause


def test_overflow_and_quote_classification_without_gold():
    s=snapshot([record(('word '*351)+'.')]);d=assemble(s);m=metrics(d)
    assert m['overflow_count']==1 and m['overflow_max_words']==352
    assert m['overflow'][0]['cause']=='other'
    assert m['overflow'][0]['chunk_id']==d.chunks[0].chunk_id
    assert m['tables_unavailable_share']==0
    s=snapshot([record('Growth.'),record('The result.',order=1)]);d=assemble(s)
    assert quote_coverage(d,[{'id':'q','page_index':0,'evidence_quote':'Growth. The result.'}])['single_chunk']==1
    assert overflow_cause('x = foo(1);','text',('code_text',))=='code'

def test_size_gate_rejects_unflagged_body_overflow():
    from eval.reading.r_lite import assert_gates
    import pytest
    d=assemble(snapshot([record(('word '*351)+'.')]))
    bad=d.model_copy(update={'chunks':(d.chunks[0].model_copy(update={'flags':()}),)})
    with pytest.raises(ValueError,match='G6'):
        assert_gates(bad)
