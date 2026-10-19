import pytest
from eval.verification.realistic import payload, render_packet


def test_generation_settings_explicit_and_no_gold_targets_leak():
    q={'question':'What changed?', 'id':'q1', 'split':'check', 'target_text':'SECRET GOLD'}
    p=payload(q,[dict(block_id='b',start=0,end=17,text='Revenue improved.')])
    assert p['model']=='qwen3.5:9b' and p['think'] is False and p['truncate'] is False
    assert p['options']['seed']==20261017 and p['options']['temperature']==0
    assert p['options']['num_ctx']>p['options']['num_predict']
    assert 'SECRET GOLD' not in p['prompt']
    assert 'block_id' in str(p['format']) and p['stream'] is False


def test_packet_preserves_exact_text_empty_labels_and_split_without_support_labels():
    rows=[dict(id='q1',split='check',question='Question?',status='completed', sentences=[dict(
        text='Revenue improved.',claims=[dict(text='Revenue improved.',citations=[dict(block_id='b',start=0,end=17)])])],
        resolved=[dict(block_id='b',start=0,end=17,quote='Revenue improved.')],
        receipt=dict(checks=[dict(target='claim:0',layer='L2',verdict='pass',reasons=[])],status='abstained'))]
    text=render_packet(rows)
    assert 'Revenue improved.' in text and 'check' in text and 'L2' in text
    assert 'Label (supported / unsupported / partial / unclear): ______' in text
    assert 'label: supported' not in text


def test_remote_url_and_redirects_are_refused_without_requests():
    from eval.verification.realistic import LocalGeneration
    with pytest.raises(ValueError): LocalGeneration('https://remote.invalid:11434')


def test_conservative_budget_fits_largest_measured_dev_prompt_before_inference():
    # Metadata-only measured maximum from the unchanged dev5/top10 cache (43,752 UTF-8 bytes).
    # A byte bound is deliberately looser than model tokens; preserve a template reserve too.
    p=payload({'question':'q'},[])
    assert p['options']['num_ctx'] >= 43752 + p['options']['num_predict'] + 2048


def test_short_refs_copy_full_ids_without_changing_text_spans_or_inventing_ids():
    from eval.verification.realistic import resolve_local_refs
    spans=[dict(block_id='sha256-'+'b'*64+':p0000:0123456789abcdef',start=0,end=17,text='Revenue improved.')]
    p=payload({'question':'q'},spans)
    assert spans[0]['block_id'] not in p['prompt']
    assert 'Revenue improved.' in p['prompt']
    g=dict(sentences=[dict(text='Revenue improved.',claims=[dict(text='Revenue improved.',citations=[dict(block_id='b1',start=0,end=17)])])])
    mapped=resolve_local_refs(g,spans)
    assert mapped['sentences'][0]['claims'][0]['citations'][0]['block_id']==spans[0]['block_id']
    assert g['sentences'][0]['claims'][0]['citations'][0]['block_id']=='b1'
