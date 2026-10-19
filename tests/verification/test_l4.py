"""L4 boundary safety; tiny fake transport, no model downloads or inference."""
import hashlib
import json
import math
from pathlib import Path
import pytest
from matn_verification.l4 import L4Adapter, validate_files
from matn_verification.contracts import Evidence
from matn_verification.rules import verify
from tests.verification.test_rules import doc, request


def ev(text='Evidence.', start=0):
    return Evidence(block_id='b',start=start,end=start+len(text),quote=text,doc_id='d',pdf_page_index=0,page_label=None,bbox=(0.,0.,1.,1.),bbox_precision='block')


def response(score=.7, **kw):
    return dict(protocol=1,status='scored',score=score,tokens=12,seconds=.01,model_id='lytang/MiniCheck-RoBERTa-Large',revision='74c8919647e61ed0f71bc177d94f10930f090068',file_hashes={'config.json':'a'*64},**kw)


@pytest.mark.parametrize('score,verdict',[(.5,'reject'),(.50000001,'pass'),(0.,'reject'),(1.,'pass')])
def test_native_strict_boundary_and_receipt_metadata(score,verdict):
    a=L4Adapter(transport=lambda p:response(score))
    c=a.check('Claim.',(ev(),),'sentence')
    assert c.verdict==verdict and c.l4.raw_score==score and c.l4.cutoff==.5
    assert c.l4.revision and c.l4.file_hashes and c.l4.protocol==1


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1.,1.1,True,'0.9',None])
def test_invalid_output_never_passes(value):
    c=L4Adapter(transport=lambda p:response(value)).check('C',(ev(),),'sentence')
    assert c.verdict=='unknown' and c.reasons==('model_output_invalid',)


@pytest.mark.parametrize('status,reason',[('model_unavailable','model_unavailable'),('hash_mismatch','model_unavailable'),('overflow','model_input_overflow')])
def test_unavailable_and_overflow_abstain(status,reason):
    c=L4Adapter(transport=lambda p:dict(protocol=1,status=status)).check('C',(ev(),),'sentence')
    assert c.verdict=='unknown' and c.reasons==(reason,)


def test_whole_bundle_and_final_sentence_union_no_prefix_or_truncation():
    calls=[]
    def call(p):calls.append(p);return response()
    a=L4Adapter(transport=call)
    d=doc('Revenue increased.','Costs decreased.')
    r=request(d, text='Revenue increased. Costs decreased.',indices=(0,1))
    r['claims']=[{'text':e.block.text,'citations':[r['claims'][0]['citations'][i]]} for i,e in enumerate(d.elements)]
    receipt=verify([d],r,a)
    assert receipt.status=='verified'
    assert calls[-1]['text']==r['sentence']
    assert calls[-1]['evidence']=='Revenue increased.\nCosts decreased.'
    assert all(p['protocol']==1 for p in calls)
    assert all(c.l4 for c in receipt.checks if c.layer=='L4')


def test_earlier_reject_never_calls_or_gets_overridden():
    calls=[]
    a=L4Adapter(transport=lambda p:calls.append(p) or response())
    d=doc('Revenue was 12 percent.')
    assert verify([d],request(d,'Revenue was 99 percent.'),a).status=='rejected'
    assert not calls


def test_missing_hash_and_revision_drift(tmp_path):
    config=tmp_path/'config.json';config.write_text('{}')
    m={'repo':'lytang/MiniCheck-RoBERTa-Large','revision':'74c8919647e61ed0f71bc177d94f10930f090068','files':{'config.json':hashlib.sha256(config.read_bytes()).hexdigest()},'status':'downloaded'}
    validate_files(tmp_path,m)
    config.write_text('changed')
    with pytest.raises(ValueError):validate_files(tmp_path,m)
    m['revision']='new'
    with pytest.raises(ValueError):validate_files(tmp_path,m)


def test_worker_budget_preflight_never_truncates():
    from matn_verification.l4_worker import score_pair
    class IDs:
        shape=(1,513)
    class Tokenizer:
        def __call__(self,*a,**kw):
            assert kw['truncation'] is False
            return {'input_ids':IDs()}
    class Model:
        def __call__(self,**kw):raise AssertionError('overflow reached model')
    assert score_pair(Model(),Tokenizer(),'E','C',False,None)['status']=='overflow'


def test_missing_worker_executable_abstains():
    a=L4Adapter('/nonexistent/matn-python','/nonexistent/model')
    assert a.check('C',(ev(),),'sentence').verdict=='unknown'


def test_unregistered_manifest_identity_is_rejected(tmp_path):
    p=tmp_path/'config.json';p.write_text('{}')
    with pytest.raises(ValueError):
        validate_files(tmp_path,{'files':{'config.json':hashlib.sha256(p.read_bytes()).hexdigest()}})


def test_foundation_offline_ref_must_match_verified_snapshot(tmp_path):
    from matn_verification.l4_files import validate_foundation
    revision='7bcac572ce56db69c1ea7c8af255c5d7c9672fc2'
    config=tmp_path/'snapshots'/revision/'config.json';config.parent.mkdir(parents=True);config.write_text('{}')
    ref=tmp_path/'refs'/'main';ref.parent.mkdir();ref.write_text(revision)
    manifest={'repo':'google/flan-t5-base','revision':revision,'weights_downloaded':False,'files':{'config.json':{'cache_path':str(config),'sha256':hashlib.sha256(config.read_bytes()).hexdigest()}}}
    validate_foundation(manifest)
    ref.write_text('different-revision')
    with pytest.raises(ValueError):validate_foundation(manifest)
