"""V2 import must bind labels to immutable claim bytes, never packet position."""
import pytest
from eval.verification.v2 import match_labels


def test_labels_match_identity_and_never_relabel():
    claims=[{'question_id':'q','atomic_claim':'1.1','claim_sha256':'a','split':'tune'}]
    labels=[{**claims[0],'label':'partial'}]
    assert match_labels(claims, labels)==labels
    with pytest.raises(ValueError,match='unmatched'):
        match_labels(claims,[{**labels[0],'claim_sha256':'b'}])
    with pytest.raises(ValueError,match='duplicate'):
        match_labels(claims,labels*2)
    with pytest.raises(ValueError,match='split'):
        match_labels(claims,[{**labels[0],'split':'check'}])
