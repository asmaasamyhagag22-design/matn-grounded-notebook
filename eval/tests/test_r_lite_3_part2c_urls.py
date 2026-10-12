"""URL policy-conformance diagnostics; no reading production fixtures."""
import json
from pathlib import Path
from eval.tests.test_r_lite_3_part2c_rules import source
from eval.rag.r_lite_3_part2c_m3_v2 import decisions


def test_wrapped_url_lines_do_not_seed_a_region():
    cfg=json.loads(Path('eval/rag/r_lite_3_part2c_m3_v2_rule.json').read_text())
    data=source([('https://example.org/','Courier',100,10),('project/repository','Courier',100,22)])
    assert decisions(data,cfg)['code_block_ids']==[]


def test_all_other_v1_parameters_are_identical():
    root=Path('eval/rag');a=json.loads((root/'r_lite_3_part2c_m3_rule.json').read_text());b=json.loads((root/'r_lite_3_part2c_m3_v2_rule.json').read_text());b.pop('url_policy');a.pop('name');b.pop('name');assert a==b
    old=(root/'r_lite_3_part2c_m3.py').read_text();new=(root/'r_lite_3_part2c_m3_v2.py').read_text()
    assert old[old.index('        numbers = []'):]==new[new.index('        numbers = []'):]


def test_url_revision_preserves_diff_regions():
    cfg=json.loads(Path('eval/rag/r_lite_3_part2c_m3_v2_rule.json').read_text())
    data=source([('+change','Courier',100,10),('-change','Courier',100,22)])
    assert decisions(data,cfg)['code_block_ids']==['fixture-0','fixture-1']
