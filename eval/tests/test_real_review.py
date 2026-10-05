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
