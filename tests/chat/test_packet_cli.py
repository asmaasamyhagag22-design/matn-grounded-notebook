import json
import subprocess
import sys
from pathlib import Path
from eval.chat.realistic import render_packet, summarize
from tests.chat.test_engine import doc,engine,Generator,answer


def test_packet_includes_failed_and_repaired_candidates_with_empty_labels():
    d=doc('Revenue was 12 percent.');e=engine(d,Generator(answer('Revenue was 99 percent.'),answer()))
    r=e.ask('n',['source1'],'What revenue?')
    rows=[dict(id='q',question='What revenue?',split='tune',cohort='frozen60',response=r,trace=e.trace)]
    packet=render_packet(rows)
    assert packet.count('Label (supported / unsupported / partial / unclear): ______')==2
    assert 'Revenue was 99 percent.' in packet and 'Revenue was 12 percent.' in packet
    assert 'First failure: L1' in packet and 'Redraft' in packet and 'First attempt' in packet
    assert 'L2: pass' not in packet
    summary=summarize(rows)
    assert summary['cohorts']['frozen60']['answer_states']=={'answered':1}
    assert summary['cohorts']['frozen60']['redraft']['rescued_slots']==1


def test_packet_retains_schema_invalid_recognizable_sentences():
    d=doc('Revenue was 12 percent.');e=engine(d,Generator({'sentences':[{'text':'A malformed claim.','handles':[]}]}))
    r=e.ask('n',['source1'],'q')
    text=render_packet([dict(id='q',question='q',split='check',cohort='frozen60',response=r,trace=e.trace)])
    assert 'A malformed claim.' in text and 'schema_invalid' in text
    assert 'Label (supported / unsupported / partial / unclear): ______' in text
    assert r['dropped_sentences']==1


def test_cli_help_and_missing_snapshot_fail_closed(tmp_path):
    help=subprocess.run([sys.executable,'-m','matn_chat','ask','--help'],capture_output=True,text=True)
    assert help.returncode==0 and '--notebook' in help.stdout and '--sources' in help.stdout
    p=tmp_path/'missing.sqlite'
    failed=subprocess.run([sys.executable,'-m','matn_chat','ask','--notebook',str(p),'--sources','all','q'],capture_output=True,text=True)
    out=json.loads(failed.stdout)
    assert out['state']=='error' and out['sentences']==[] and not p.exists()
