"""Language binding gains no permission to invent actors, quantities or scope."""
from matn_app.prose_verification import verify_prose
from matn_verification.scope import verify_scope
from matn_verification.contracts import Check
from tests.verification.test_rules import doc,request


class Native:
    def __init__(self,verdict='pass'):self.verdict=verdict
    def check(self,text,evidence,target):return Check(target=target,layer='L4',verdict=self.verdict,reasons=() if self.verdict=='pass' else ('entailment_failed',))


def test_present_tense_actor_binding_and_discourse_do_not_require_whole_sentence_copy():
    d=doc('Model Alpha achieves the best performance through parameter tuning, but saturates early.')
    req=request(d,'Model Alpha performs best through parameter tuning but reaches saturation early.')
    assert verify_scope((d,),req,Native()).status!='verified'
    value=verify_prose((d,),req,Native())
    assert value.status=='verified' and value.verifier_version=='app-grounded-scope-v1'
    assert verify_prose((d,),req,Native('reject')).status!='verified'
    d=doc('However, the method does not improve maximum reward.')
    req=request(d,'The method does not improve the maximum reward.')
    assert verify_prose((d,),req,Native()).status=='verified'


def test_new_normalizer_preserves_entity_number_negation_modality_and_condition_vetoes():
    pairs=[
        ('Agency Alpha should inspect equipment.','Agency Beta should inspect equipment.'),
        ('Revenue was 12 percent in 2021.','Revenue was 99 percent in 2021.'),
        ('The method does not improve maximum reward.','The method improves maximum reward.'),
        ('Agencies may review records.','Agencies must review records.'),
        ('Agencies may proceed only if approval is granted.','Agencies may proceed if approval is granted.'),
    ]
    for source,claim in pairs:
        d=doc(source)
        assert verify_prose((d,),request(d,claim),Native()).status!='verified',(source,claim)
