"""Diagnostic rule contracts; no reading implementation fixtures or models."""
import json
from pathlib import Path
from types import SimpleNamespace

from eval.rag.r_lite_3_part2c_m3 import decisions


def source(lines):
    blocks=[];elements=[]
    for i,(text,face,x,y) in enumerate(lines):
        bid=f'fixture-{i}'
        blocks.append({'block':{'block_id':bid},'lines':[{'words':[{'text':text,'font_face':face,'size':10,'bbox':[x,y,x+40,y+10]}]}]})
        elements.append(SimpleNamespace(block=SimpleNamespace(block_id=bid),citable=True,role='footnote'))
    return {'snapshot':{'pages':[{'page_index':0,'blocks':blocks}]},'document':SimpleNamespace(elements=elements)}


def rule():
    return json.loads(Path('eval/rag/r_lite_3_part2c_m3_rule.json').read_text())


def test_isolated_monospace_and_urls_are_not_regions():
    data=source([('https://example.org/a','Courier',100,10),('https://example.org/b','Courier',100,22),('x=1','Courier',100,100)])
    assert decisions(data,rule())['code_block_ids']==[]


def test_consecutive_region_retains_diff_marker():
    data=source([('+change','Courier',100,10),('-change','Courier',100,22)])
    assert decisions(data,rule())['code_block_ids']==['fixture-0','fixture-1']
    assert decisions(data,rule())['excluded_gutter_block_ids']==[]


def test_missing_font_is_unknown():
    data=source([('1','',100,10)])
    assert decisions(data,rule())['unknown_ids']==['fixture-0']
