import pytest
from .conftest import record,snapshot
from matn_reading.structure.elements import build_elements

def test_exclusions_and_digital_provenance():
    r=[record('Hidden 99.','text','uncertain'),record('Header 99.','header',order=1),record('Growth 12.',order=2)]
    es,issues=build_elements(snapshot(r))
    assert [e.citable for e in es]==[False,False,True]
    assert es[0].exclusion_reasons and es[1].exclusion_reasons
    assert es[2].number_tokens[0].status=='digital'
    assert es[2].number_tokens[0].bbox.bbox_precision=='word'

def test_ocr_unlinked_and_reader_status_are_preserved():
    ocr={'tokens':[{'token':'12','bbox':[10.,10.,200.,25.],'reader2':'13','status':'uncertain_number','flagged':True,'reasons':['readers_disagree']}],'preprocess':{'size':[2550,3300],'rotation_deg':0},'lines':[]}
    es,_=build_elements(snapshot([record('Growth 12 and 14.',ocr=ocr)],ocr))
    assert [t.status for t in es[0].number_tokens]==['flagged','flagged-unlinked']
    assert es[0].number_tokens[0].reader2=='13'
    assert es[0].number_tokens[1].reader_ref is None

def test_digital_number_spans_multiple_source_words():
    r=record('-4.5')
    r['lines'][0]['words']=[{'text':'-','bbox':[10.,10.,15.,25.],'size':11.,'bold':False},{'text':'4.5','bbox':[16.,10.,40.,25.],'size':11.,'bold':False}]
    es,_=build_elements(snapshot([r]))
    n=es[0].number_tokens[0]
    assert n.status=='digital' and n.bbox.bbox_precision=='word'
    assert n.bbox.coordinates==(10.,10.,40.,25.)

def test_unmatched_digital_numeric_fragment_is_never_verified():
    r=record('3','table')
    r['lines'][0]['words'][0]['text']='3.0'
    es,_=build_elements(snapshot([r]))
    n=es[0].number_tokens[0]
    assert n.status=='digital-unlinked' and n.reader_ref is None
    assert n.bbox.bbox_precision=='region' and n.reader1 is None

def test_reordered_duplicate_digital_numbers_are_not_guessed():
    r=record('12 | 12','table')
    r['lines'][0]['words']=[{'text':'12','bbox':[10.,10.,30.,25.],'size':11.,'bold':False},{'text':'12','bbox':[50.,10.,70.,25.],'size':11.,'bold':False}]
    es,_=build_elements(snapshot([r]))
    assert all(n.status=='digital-unlinked' for n in es[0].number_tokens)
