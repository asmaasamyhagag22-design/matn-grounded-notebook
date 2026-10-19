import copy
import socket
import pytest
from tests.verification.test_rules import doc,request
from eval.verification.replay import replay_row


def test_replay_preserves_generation_and_uses_new_rules_without_network(monkeypatch):
    def forbidden(*a,**kw):raise AssertionError('offline replay attempted network')
    monkeypatch.setattr(socket.socket,'connect',forbidden)
    d=doc('France employment was 12 percent.')
    r=request(d);sentence=dict(text=r['sentence'],claims=r['claims'])
    row=dict(id='q',split='check',question='q?',binding='original',status='completed',sentences=[sentence],diagnostics=[{'original':True}])
    before=copy.deepcopy(row)
    b=d.elements[0].block;spans=[dict(block_id=b.block_id,start=0,end=len(b.text),text=b.text)]
    out=replay_row(row,spans,[d])
    assert row==before
    assert {k:v for k,v in out.items() if k!='diagnostics'}=={k:v for k,v in row.items() if k!='diagnostics'}
    assert out['diagnostics'][0]['receipt']['verifier_version']=='verification-rules-v2.1'
    assert out['diagnostics'][0]['receipt']['status']=='abstained'
    assert out['diagnostics'][0]['resolved'][0]['quote']==b.text


def test_deferred_rows_are_preserved_not_regenerated():
    row=dict(id='q',status='deferred',reason='HTTP 500',sentences=[],binding='original')
    assert replay_row(row,[],[])==row
