"""M4 diagnostics: literal native space must veto a geometry-eligible join."""
from eval.rag.r_lite_3_part2c_m4 import decisions
import json
from pathlib import Path


def data(space):
    words=[{'text':'A','font_face':'Sans','size':10,'bbox':[0,0,5,10]}, {'text':'B','font_face':'Sans','size':10,'bbox':[6,0,11,10]}]
    chars=[{'object_id':0,'text':'A','bbox':[0,0,5,10]},{'object_id':1,'text':'B','bbox':[6,0,11,10]}]
    if space:chars.append({'object_id':2,'text':' ','bbox':[5,0,6,10]})
    src={'snapshot':{'pages':[{'page_index':0,'ocr':None,'blocks':[{'block':{'block_id':'fixture','route':'text_layer','text':'A B'},'lines':[{'words':words}]}]}]}}
    return src,{'fixture/0':{'chars':chars}}


def test_literal_space_is_retained():
    rule=json.loads(Path('eval/rag/r_lite_3_part2c_m4_rule.json').read_text());src,objects=data(True)
    assert decisions(src,objects,'fixture',rule)['texts']=={}


def test_synthetic_space_remaps_without_glyph_loss():
    rule=json.loads(Path('eval/rag/r_lite_3_part2c_m4_rule.json').read_text());src,objects=data(False);result=decisions(src,objects,'fixture',rule)
    assert result['texts']=={'fixture':'AB'}
    assert result['offset_remaps']['fixture']=={'new_to_old':[0,2],'old_to_new':[0,None,1],'deleted_synthetic_space_offsets':[1]}
