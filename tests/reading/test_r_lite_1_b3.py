"""Fixture-first B3: no threshold tuning on dev."""
import pytest
from .pdf_fixtures import write_pdf
from .r_lite_1_fixtures import text,chart_fixture
from matn_reading.read import read_document
from matn_reading.layout import join_hyphenation

def test_b3_preserves_lexical_hyphen_only_when_following_fragment_has_hyphen():
    assert join_hyphenation(['An end-','to-end solution.'],preserve_lexical=True)[0]=='An end-to-end solution.'
    assert join_hyphenation(['govern-','ment'])[0]=='government'
    assert join_hyphenation(['COVID-','19'])[0]=='COVID-19'


def test_b3_digital_pdf_keeps_lexical_hyphen(tmp_path):
    content=text(72,700,'This is an end-')+text(72,686,'to-end solution with evidence.')
    page=read_document(write_pdf(tmp_path/'lexical.pdf',content)).pages[0]
    assert any('end-to-end' in b.layout.text for b in page.blocks)


def test_shared_layout_defaults_preserve_frozen_ocr_joining():
    assert join_hyphenation(['end-','to-end'])[0]=='endto-end'


