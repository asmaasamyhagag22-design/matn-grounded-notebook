"""The review generator suggests readings but never writes or preselects human GT."""
import json
from pathlib import Path


def test_review_has_no_selected_answers_and_preserves_template(tmp_path):
    from eval.reading.real.review import render_html, make_proposals
    template={"doc_key":"doc", "page_index":0, "status":"template", "numbers":[]}
    rows=[{"token":"20", "reader2":"28", "word":"Year 20", "bbox":[10,20,30,40], "flagged":True}]
    proposals=make_proposals(rows,[],0,(2550,3300),(0,0,612,792))
    before=json.dumps(template)
    html=render_html([{"key":"doc_p0000","template":template,"proposals":proposals,"image":"page.png"}])
    assert json.dumps(template)==before
    assert all(p["chosen"] is None for p in proposals)
    assert 'Save GT' in html and 'not a number' in html
    assert 'showDirectoryPicker' in html and 'createWritable' in html
    assert 'https://' not in html and '<script src=' not in html
    assert 'value_as_printed' in html and 'verified_by' in html


def test_layer_only_number_is_reviewable_and_not_prefilled():
    from eval.reading.real.review import make_proposals
    p=make_proposals([],[("Total 64",[10,10,60,30])],0,(2550,3300),(0,0,612,792))
    assert len(p)==1 and p[0]["layer"] == "64" and p[0]["chosen"] is None


def test_real_measurement_refuses_incomplete_human_gt(tmp_path):
    from eval.reading.real.review import validated_truth
    path=tmp_path / "gt.json"
    path.write_text(json.dumps({"status":"template","numbers":[]}),encoding="utf-8")
    import pytest
    with pytest.raises(ValueError,match="owner"):
        validated_truth(path)


def test_signed_synthetic_fixture_measures_true_false_alarms_per_page(monkeypatch, tmp_path):
    # Synthetic unit fixture only: never sign or modify a real-scan template.
    from eval.reading.real import measure as m
    here=tmp_path/'synthetic';(here/'gt').mkdir(parents=True)
    out=tmp_path/'outputs';(out/'final/real').mkdir(parents=True)
    key='synthetic_metrics_fixture';pagekey=key+'_p0000'
    (here/'sources.json').write_text(json.dumps({'documents':[{'doc_key':key,'gt_pages':[{'page_index':0}]}]}),encoding='utf-8')
    boxes=[[10,10,20,20],[30,10,40,20],[50,10,60,20]]
    gt={'doc_key':key,'page_index':0,'status':'verified','verified_by':'synthetic unit-test fixture',
        'full_page_reviewed':True,'numbers':[{'value_as_printed':v,'bbox':b,'verified':True} for v,b in zip(['10','20','30'],boxes)]}
    (here/'gt'/f'{pagekey}.json').write_text(json.dumps(gt),encoding='utf-8')
    record={'cropbox':[0,0,100,100],'preprocess':{'size':[417,417],'rotation_deg':0},'wall_seconds':1,
            'tokens':[{'token':v,'bbox':b,'flagged':f} for v,b,f in zip(['10','99','30'],boxes,[True,False,False])],'flags':[]}
    (out/'final/real'/f'{pagekey}.json').write_text(json.dumps(record),encoding='utf-8')
    monkeypatch.setattr(m,'HERE',here);monkeypatch.setattr(m,'OUT',out)
    monkeypatch.setattr(m,'verify_sources',lambda:{key:{'status':'ok'}})
    monkeypatch.setattr(m,'require_verified',lambda key:tmp_path/'synthetic.pdf')
    m.measure()
    row=json.loads((out/'real-human-metrics.json').read_text(encoding='utf-8'))['pages'][0]
    assert row['accuracy']==2/3 and row['silent_errors_raw']==1
    assert row['flag_rate']==1/3
    assert row['false_alarm_share_of_flags']==1  # The sole flag is on a correct read.
    assert row['false_positive_rate_on_correct_reads']==1/2  # One of the two correct reads is flagged.
