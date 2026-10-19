"""Document-level Egypt cannot override an explicit span subject or pronoun gap."""
from tests.verification.test_rules import doc,request,result,layers,reasons

WB='sha256-2f6f619c81527ec7a4770fba3d7162381e9ce7cb3efea2f0e889aa5ed1ba419a'


def wb(*texts):return doc(*texts).model_copy(update={'doc_id':WB})


def test_registered_subject_cannot_borrow_an_explicit_foreign_country_number():
    d=wb('France revenue increased to 12 percent.')
    r=result(d,request(d,'Egypt revenue increased to 12 percent.'))
    assert layers(r)['L3']['verdict']=='reject'
    assert 'number_not_in_evidence' in reasons(r)


def test_explicit_egypt_clause_keeps_own_binding_despite_document_subject():
    d=wb('Egypt revenue increased to 12 percent. France revenue increased to 15 percent.')
    assert 'number_not_in_evidence' in reasons(result(d,request(d,'Egypt revenue increased to 15 percent.')))
    assert layers(result(d,request(d,'Egypt revenue increased to 12 percent.')))['L1']['verdict']=='pass'


def test_registered_subject_does_not_resolve_external_source_pronoun():
    d=wb('It increased to 12 percent.')
    assert layers(result(d,request(d,'Egypt increased to 12 percent.')))['L3']['verdict']=='unknown'


def test_implicit_document_subject_still_binds_without_foreign_or_pronoun_signal():
    d=wb('Revenue increased to 12 percent.')
    assert layers(result(d,request(d,'Egypt revenue increased to 12 percent.')))['L3']['verdict']=='pass'
