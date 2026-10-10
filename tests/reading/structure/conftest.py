import pytest
from matn_contracts.domain import Block, BlockStyle, ExtractorInfo
from matn_contracts.enums import BlockType, ExtractionRoute, Visibility

DOC='sha256-'+'b'*64

def record(text='Growth 12.',kind='text',visibility='visible',order=0,page=0,ocr=None):
    b=Block.create(doc_id=DOC,page_index=page,page_label=None,bbox=(10.,10.+order*20,200.,25.+order*20),block_type=BlockType(kind),text=text,reading_order=order,style=BlockStyle(font_size_pt=11.,is_bold=False),extractor=ExtractorInfo(name='fixture',version='1'),route=ExtractionRoute.OCR if ocr else ExtractionRoute.TEXT_LAYER,visibility=Visibility(visibility),visibility_reasons=('partial_ink',) if visibility!='visible' else ())
    return {'block':b.model_dump(mode='json'),'flagged':False,'lines':[{'words':[{'text':text,'bbox':list(b.bbox),'size':11.,'bold':False}]}]}

def snapshot(records,ocr=None):
    return {'schema_version':1,'doc_id':DOC,'title':'Fixture','core_fingerprint':'f'*64,'cache_key':'k','pages':[{'page_index':0,'page_label':None,'width':612.,'height':792.,'cropbox':[0.,0.,612.,792.],'route':'scanned' if ocr else 'digital_healthy','reasons':[],'blocks':records,'flags':[],'tables':[],'ocr':ocr}],'outline':[]}

@pytest.fixture
def snap(): return snapshot([record()])
