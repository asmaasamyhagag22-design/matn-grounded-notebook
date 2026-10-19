import pytest
from eval.verification.pilot import tune_only,propose_cutoff,variation


def test_check_split_is_refused_before_inference():
    with pytest.raises(ValueError,match='TUNE'):
        tune_only([{'split':'check'}])
    assert tune_only([{'split':'tune'}])==[{'split':'tune'}]


def test_cutoff_has_zero_silent_accepts_partial_counts_negative():
    rows=[{'label':'supported','score':.9},{'label':'partial','score':.8},
          {'label':'unsupported','score':.5},{'label':'supported','score':None}]
    out=propose_cutoff(rows)
    assert .8<out['cutoff']<=.9
    assert out['silent_accepts']==0 and out['false_blocks']==1
    assert out['negative_denominator']==2 and out['positive_denominator']==2


def test_self_variation_requires_same_inputs_and_detects_batch_drift():
    assert variation({'a':.5},{'a':.5},{'a':.51})==pytest.approx(.01)
    with pytest.raises(ValueError):variation({'a':.5},{},{'a':.5})
