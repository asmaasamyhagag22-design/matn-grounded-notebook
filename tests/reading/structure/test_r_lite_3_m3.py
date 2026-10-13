"""Reader-faithful native mono lines, pure gutters and wrapped URL footnotes."""
import pytest
from .conftest import record,snapshot
from matn_contracts.domain import Block
from matn_reading.structure.document import assemble

def native(text,x,y,order):
 r=record(text,'footnote',order=order);b=r['block'];b['bbox']=[x,y,x+40,y+10]
 r['block']=Block.create(**{k:v for k,v in b.items() if k not in ('schema_version','block_id')}).model_dump(mode='json')
 r['lines']=[{'words':[{'text':text,'bbox':[x,y,x+40,y+10],'size':10.,'bold':False,'font_face':'Courier'}]}]
 return r

@pytest.mark.xfail(strict=True,reason='S5b RED: native consecutive mono lines remain footnotes')
def test_code_gutters_markers_and_wrapped_urls():
 code=[native(t,110,10+i*12,i) for i,t in enumerate(['+change','-change','x=1','return x'])]
 gutter=[native(str(70+i),60,10+i*12,4+i) for i in range(4)]
 urls=[native('https://example.org/',110,200,8),native('project',110,212,9)]
 d=assemble(snapshot(code+gutter+urls));by={e.block.block_id:e for e in d.elements}
 assert all(by[r['block']['block_id']].role=='text' and 'code_text' in by[r['block']['block_id']].flags for r in code)
 assert all(not by[r['block']['block_id']].citable for r in gutter)
 assert all(by[r['block']['block_id']].role=='footnote' and by[r['block']['block_id']].citable for r in urls)
 assert [by[r['block']['block_id']].block.text for r in code]==[r['block']['text'] for r in code]
