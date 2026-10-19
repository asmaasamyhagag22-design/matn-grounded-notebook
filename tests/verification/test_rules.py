"""Native stored-structure fixtures; no PDFs, gold changes or inference."""
import copy
import json
import subprocess
import sys

import pytest
from matn_reading.structure.document import assemble
from tests.reading.structure.conftest import record, snapshot
from matn_verification.rules import coverage, eligibility, verify


def doc(*texts):
    return assemble(snapshot([record(t, order=i) for i, t in enumerate(texts)]))


def request(d, text=None, indices=(0,), **updates):
    refs = [dict(block_id=d.elements[i].block.block_id, start=0,
                 end=len(d.elements[i].block.text), quote=d.elements[i].block.text) for i in indices]
    text = text or d.elements[indices[0]].block.text
    r = dict(sentence=text, claims=[dict(text=text, citations=refs)], selected_doc_ids=[d.doc_id],
             fingerprints={d.doc_id: fingerprint(d)})
    r.update(updates)
    return r


def fingerprint(d):
    from hashlib import sha256
    from matn_rag.contracts import canonical
    return sha256(canonical(d.model_dump(mode='json'))).hexdigest()


def result(d, r):
    return verify([d], r).model_dump(mode='json')


def layers(r):
    return {row['layer']: row for row in r['checks'] if row['target'] == 'sentence'}


def reasons(r):
    return {reason for row in r['checks'] for reason in row['reasons']}


def test_rules_success_still_abstains_without_l4_and_is_immutable():
    d = doc('Revenue increased to 12 percent in 2021.')
    receipt = verify([d], request(d))
    r = receipt.model_dump(mode='json')
    assert r['schema_version'] == 1 and r['status'] == 'abstained'
    assert all(layers(r)[k]['verdict'] == 'pass' for k in ('L0', 'L1', 'L2', 'L3'))
    assert layers(r)['L4']['verdict'] == 'not_run'
    with pytest.raises(ValueError):
        receipt.status = 'verified'
    assert r['evidence'][0]['quote'] == d.elements[0].block.text
    assert r['request_sha256'] and r['text_sha256'] and r['verifier_version']


@pytest.mark.parametrize('mutation,reason', [
    ('missing', 'invalid_evidence_span'), ('negative', 'invalid_evidence_span'),
    ('oversize', 'invalid_evidence_span'), ('empty', 'invalid_evidence_span'),
    ('substring', 'quote_not_found'), ('space', 'invalid_evidence_span'),
    ('partial', 'invalid_evidence_span'), ('unselected', 'source_not_selected'),
    ('stale', 'stale_source'), ('prefix', 'invalid_evidence_span'),
])
def test_citation_integrity_rejects_forged_or_partial_refs(mutation, reason):
    d = doc('Revenue was 100 GPUs.')
    r = request(d); ref = r['claims'][0]['citations'][0]
    if mutation in ('missing', 'prefix'): ref['block_id'] = 'context_prefix' if mutation == 'prefix' else 'absent'
    if mutation == 'negative': ref['start'] = -1
    if mutation == 'oversize': ref['end'] += 10
    if mutation == 'empty': ref['end'] = 0
    if mutation == 'substring': ref['quote'] = 'Other text'
    if mutation == 'space': ref.update(start=7, end=8, quote=' ')
    if mutation == 'partial': ref.update(start=13, end=15, quote='00')
    if mutation == 'unselected': r['selected_doc_ids'] = []
    if mutation == 'stale': r['fingerprints'][d.doc_id] = 'wrong'
    rr = result(d, r)
    assert reason in reasons(rr) and rr['status'] == 'rejected'


@pytest.mark.parametrize('kind,visibility,flag,reason', [
    ('figure', 'visible', None, 'evidence_in_figure'),
    ('text', 'hidden', None, 'evidence_hidden'),
    ('text', 'uncertain', None, 'evidence_hidden'),
    ('table', 'visible', None, 'unavailable_table_evidence'),
    ('text', 'visible', 'code_text', 'code_text'),
    ('header', 'visible', None, 'evidence_not_citable'),
])
def test_l0_object_vetoes(kind, visibility, flag, reason):
    snap = snapshot([record('Alpha is 12 percent.', kind=kind, visibility=visibility)])
    d = assemble(snap)
    if flag:
        d = d.model_copy(update={'elements': (d.elements[0].model_copy(update={'flags': (flag,)}),)})
    rr = result(d, request(d))
    assert reason in reasons(rr) and rr['status'] == 'rejected'


def test_mixed_ocr_text_and_accepted_numbers_are_both_quarantined():
    d = doc('Revenue was 12 percent.')
    e = d.elements[0]
    e = e.model_copy(update={'block': e.block.model_copy(update={'route': __import__('matn_contracts.enums', fromlist=['ExtractionRoute']).ExtractionRoute.OCR})})
    d = d.model_copy(update={'elements': (e,), 'pages': (d.pages[0].model_copy(update={'route': 'mixed'}),)})
    assert 'mixed_ocr_evidence' in eligibility(d, e)
    assert 'mixed_ocr_evidence' in reasons(result(d, request(d)))


@pytest.mark.parametrize('claim,reason', [
    ('Revenue was 99 percent.', 'number_not_in_evidence'),
    ('Revenue was six-four percent.', 'spelled_number_mismatch'),
    ('Revenue was 64 dollars.', 'scope_mismatch'),
    ('Revenue was 64 percent in 2030.', 'number_not_in_evidence'),
    ('Revenue was 64.', 'scope_mismatch'),
    ('Revenue was 64 percentage points.', 'scope_mismatch'),
])
def test_numbers_and_scope(claim, reason):
    d = doc('Revenue was 64 percent in 2021.')
    assert reason in reasons(result(d, request(d, claim)))


@pytest.mark.parametrize('status', ['flagged', 'flagged-unlinked', 'digital-unlinked'])
def test_unverifiable_numeric_dispositions_never_promoted(status):
    d = doc('Revenue was 12 percent.')
    e = d.elements[0]
    e = e.model_copy(update={'number_tokens': tuple(n.model_copy(update={'status': status}) for n in e.number_tokens)})
    d = d.model_copy(update={'elements': (e,)})
    assert 'number_status_disallowed' in reasons(result(d, request(d)))


def test_missing_numeric_ledger_is_unknown_not_verified():
    d = doc('Revenue was 12 percent.'); e = d.elements[0].model_copy(update={'number_tokens': ()})
    d = d.model_copy(update={'elements': (e,)})
    rr = result(d, request(d))
    assert 'number_unlinked' in reasons(rr) and rr['status'] == 'abstained'


def test_decimal_percent_and_spelled_normalization_preserves_raw_offsets():
    d = doc('Revenue was 7.50 percent.')
    rr = result(d, request(d, 'Revenue was 7.5%.'))
    assert layers(rr)['L1']['verdict'] == 'pass'
    d = doc('Revenue was 24 percent.')
    assert layers(result(d, request(d, 'Revenue was twenty-four percent.')))['L1']['verdict'] == 'pass'


def test_arxiv_kn02_over90_is_not_exact90():
    d = doc('The execution rate was over 90 percent.')
    assert 'quantity_mismatch' in reasons(result(d, request(d, 'The execution rate was 90 percent.')))


@pytest.mark.parametrize('evidence,claim,reason', [
    ('Revenue increased.', 'Revenue fell.', 'direction_mismatch'),
    ('Revenue may improve.', 'Revenue will improve.', 'modality_mismatch'),
    ('Revenue did not improve.', 'Revenue did improve.', 'negation_mismatch'),
    ('Some systems improved.', 'All systems improved.', 'quantity_mismatch'),
    ('Alpha is higher than Beta.', 'Beta is higher than Alpha.', 'comparison_mismatch'),
])
def test_l2_clear_mismatch_vetoes(evidence, claim, reason):
    d = doc(evidence)
    assert reason in reasons(result(d, request(d, claim)))


def test_l2_synonym_without_signal_passes_and_different_entity_is_not_a_veto():
    d = doc('Revenue increased.')
    assert layers(result(d, request(d, 'Revenue expanded.')))['L2']['verdict'] == 'pass'
    d = doc('France revenue increased.', 'Denmark revenue decreased.')
    rr = result(d, request(d, 'France revenue rose.', indices=(0,)))
    assert layers(rr)['L2']['verdict'] == 'pass'


@pytest.mark.parametrize('entity,neighbor', [('France', 'Denmark'), ('Financial Services', 'IT Services')])
def test_same_chunk_neighbor_does_not_bind_entity(entity, neighbor):
    d = doc(f'{entity} employment increased by 12 percent.', f'{neighbor} employment increased by 15 percent.')
    rr = result(d, request(d, f'{entity} employment increased by 15 percent.', indices=(1,)))
    assert 'attribution_mismatch' in reasons(rr)
    rr = result(d, request(d, f'{entity} employment increased by 15 percent.', indices=(0, 1)))
    assert rr['status'] == 'rejected'  # union cannot license borrowing the neighbor's number


def test_same_block_neighbor_number_and_no_entity_declaration_loophole():
    d = doc('France employment increased by 12 percent. Denmark employment increased by 15 percent.')
    rr = result(d, request(d, 'France employment increased by 15 percent.'))
    assert rr['status'] == 'rejected' and 'number_not_in_evidence' in reasons(rr)


def test_final_sentence_gap_is_checked_after_good_atomic_decomposition():
    d = doc('Revenue was 12 percent.')
    r = request(d); r['sentence'] = 'Revenue was 12 percent and costs were 99 percent.'
    rr = result(d, r)
    assert layers(rr)['L1']['verdict'] == 'reject'
    assert rr['status'] == 'rejected'


def test_empty_claims_missing_fingerprints_and_forged_status_fail_closed():
    d = doc('Revenue improved.')
    for change in [dict(claims=[]), dict(fingerprints={}), dict(status='verified')]:
        rr = result(d, request(d, **change))
        assert rr['status'] != 'verified'
        assert any(c['verdict'] in ('unknown', 'reject') for c in rr['checks'])


def test_receipt_roundtrip_cannot_trust_a_forged_cached_verdict():
    from matn_verification.contracts import Receipt
    d = doc('Revenue improved.'); r = result(d, request(d))
    r['status'] = 'verified'
    with pytest.raises(ValueError, match='receipt status disagrees'): Receipt.model_validate_json(json.dumps(r))


def test_pluggable_l4_not_run_is_required_even_for_quotes():
    from matn_verification.contracts import NotRunEntailment
    d = doc('Revenue improved.')
    rr = verify([d], request(d), entailment=NotRunEntailment()).model_dump(mode='json')
    assert rr['status'] == 'abstained' and layers(rr)['L4']['verdict'] == 'not_run'


def test_coverage_denominators_overlap_and_numeric_linkage():
    d = doc('Revenue was 12 percent.', 'Table value 20 percent.')
    e = d.elements[1].model_copy(update={'flags': ('code_text',)})
    d = d.model_copy(update={'elements': (d.elements[0], e)})
    c = coverage(d)
    assert c['citable']['blocks'] == 2 and c['surviving']['blocks'] == 1
    assert c['surviving']['characters'] == len(d.elements[0].block.text)
    assert c['numeric']['all'] == 2 and c['numeric']['eligible'] == 1
    assert c['numeric']['linked_status'] == 2
    assert c['vetoes']['code_text']['blocks'] == 1


def test_essential_numeric_period_and_entity_cannot_be_silently_dropped():
    d = doc('France revenue was 12 percent in 2021.')
    rr = result(d, request(d, 'France revenue was 12 percent.'))
    assert 'scope_unknown' in reasons(rr)
    rr = result(d, request(d, 'Revenue was 12 percent.'))
    assert 'scope_unknown' in reasons(rr)


def test_positive_subject_binding_and_unresolved_coreference():
    d = doc('Revenue expanded.')
    assert layers(result(d, request(d, 'Revenue grew.')))['L3']['verdict'] == 'pass'
    d = doc('Denmark employment improved.')
    rr = result(d, request(d, 'france employment improved.'))
    assert layers(rr)['L3']['verdict'] != 'pass'
    rr = result(d, request(d, 'It improved.'))
    assert 'entity_binding_unknown' in reasons(rr)


def test_l4_exception_and_wrong_target_cannot_fail_open():
    from matn_verification.contracts import Check
    class Broken:
        def check(self, *a): raise RuntimeError('unavailable')
    class Wrong:
        def check(self, *a): return Check(target='other', layer='L4', verdict='pass')
    d = doc('Revenue improved.')
    for adapter in (Broken(), Wrong()):
        rr = verify([d], request(d), entailment=adapter).model_dump(mode='json')
        assert rr['status'] == 'abstained' and 'model_output_invalid' in reasons(rr)


def test_available_cells_are_not_a_figure_override_and_noncell_numbers_reject():
    from matn_contracts.structure import Table
    d = doc('Revenue was 12 percent.')
    e = d.elements[0].model_copy(update={'role':'table'})
    from matn_contracts.structure import TableCell
    cell = TableCell(row=0,col=0,text='Other metric',bbox=e.bbox)
    table = Table.create(doc_id=d.doc_id, pdf_page_index=0,
        bbox=e.bbox, block_ids=(e.block.block_id,), structure='available', cells=(cell,), rows=1, cols=1)
    d = d.model_copy(update={'elements':(e,), 'tables':(table,)})
    assert 'table_cell_required' in reasons(result(d, request(d)))
    e = e.model_copy(update={'flags':('figure_text',)})
    d = d.model_copy(update={'elements':(e,)})
    assert 'evidence_in_figure' in reasons(result(d, request(d)))


def test_repeat_and_separator_use_only_real_primary_block_coordinates():
    d = doc('Revenue improved.', 'Costs fell.')
    r = request(d)
    r['claims'][0]['citations'][0] = dict(block_id=d.chunks[0].chunk_id, start=0, end=2)
    assert 'invalid_evidence_span' in reasons(result(d, r))
    assert result(d, request(d))['status'] == 'abstained'


def test_unsupported_numeric_forms_abstain_and_closed_reason_enum():
    from matn_verification.contracts import Check
    d = doc('Training used 106 tokens.')
    rr = result(d, request(d, 'Training used 10⁶ tokens.'))
    assert 'unsupported_numeric_form' in reasons(rr) and rr['status'] != 'verified'
    with pytest.raises(ValueError): Check(target='sentence', layer='L1', verdict='reject', reasons=('invented',))


def test_existing_source_outside_retrieved_spans_is_rejected():
    d = doc('Revenue improved.', 'Costs declined.')
    r = request(d, indices=(1,))
    first=d.elements[0].block
    r['retrieved_spans']=[dict(block_id=first.block_id,start=0,end=len(first.text))]
    assert 'evidence_not_retrieved' in reasons(result(d,r))


def test_each_citation_must_support_not_just_the_combined_claim():
    d = doc('Revenue was 12 percent.', 'Costs were 15 percent.')
    rr = result(d,request(d,'Revenue was 12 percent.',indices=(0,1)))
    assert any(c['target']=='claim:0:citation:1' and c['layer']=='L1' and c['verdict']=='reject' for c in rr['checks'])


def test_future_entailment_rejection_carries_existing_unsupported_reason():
    from matn_verification.contracts import Check
    class Reject:
        def check(self, text, evidence, target):
            return Check(target=target,layer='L4',verdict='reject',reasons=('unsupported_statement',))
    d = doc('Revenue improved.')
    rr = verify([d],request(d),entailment=Reject()).model_dump(mode='json')
    assert rr['status']=='rejected' and 'unsupported_statement' in reasons(rr)


def test_two_process_receipt_bytes_are_deterministic_without_models(tmp_path):
    d = doc('Revenue was 12 percent.')
    path=tmp_path/'input.json';path.write_text(json.dumps(dict(doc=d.model_dump(mode='json'),request=request(d))))
    code="from pathlib import Path;import json,sys;from matn_contracts.structure import DocumentStructure;from matn_verification.rules import verify;from matn_rag.contracts import canonical;x=json.loads(Path(sys.argv[1]).read_text());print(canonical(verify([DocumentStructure.model_validate(x['doc'])],x['request']).model_dump(mode='json')).decode())"
    assert subprocess.check_output([sys.executable,'-c',code,str(path)])==subprocess.check_output([sys.executable,'-c',code,str(path)])


def test_final_union_does_not_swap_entity_numbers_despite_correct_claims():
    d=doc('France employment was 12 percent.', 'Denmark employment was 15 percent.')
    r=request(d,'France employment was 12 percent.',indices=(0,))
    other=request(d,'Denmark employment was 15 percent.',indices=(1,))['claims'][0]
    r['claims'].append(other)
    r['sentence']='France employment was 15 percent. Denmark employment was 12 percent.'
    rr=result(d,r)
    assert layers(rr)['L1']['verdict']=='reject'


@pytest.mark.parametrize('evidence,claim',[
    ('Revenue was $12.', 'Revenue was 12.'),
    ('Revenue was 12 million dollars.', 'Revenue was 12 million euros.'),
])
def test_currency_scope_is_positive_not_just_matching_digits(evidence,claim):
    d=doc(evidence)
    assert layers(result(d,request(d,claim)))['L1']['verdict']=='reject'


@pytest.mark.parametrize('claim', ['Revenue was 99kg.', 'Revenue was x99.', 'Revenue was 99_000.'])
def test_unparsed_digit_runs_never_pass_numeric_gate(claim):
    d=doc('Revenue was 12 percent.')
    rr=result(d,request(d,claim))
    assert layers(rr)['L1']['verdict']=='unknown'
    assert 'unsupported_numeric_form' in reasons(rr)


@pytest.mark.parametrize('joiner', ['while', 'and', 'whereas', 'but'])
def test_conjoined_final_sentence_cannot_swap_entity_values(joiner):
    d=doc('France employment was 12 percent.', 'Denmark employment was 15 percent.')
    r=request(d,indices=(0,))
    r['claims'].append(request(d,indices=(1,))['claims'][0])
    r['sentence']=f'France employment was 15 percent {joiner} Denmark employment was 12 percent.'
    assert layers(result(d,r))['L1']['verdict']=='reject'


def test_same_block_conjoined_entities_keep_their_own_numbers():
    d=doc('France employment was 12 percent while Denmark employment was 15 percent.')
    assert layers(result(d,request(d)))['L1']['verdict']=='pass'
    r=request(d,'France employment was 15 percent.')
    assert layers(result(d,r))['L1']['verdict']=='reject'
