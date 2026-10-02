"""Hidden text: spans covered by an image or a vector fill drawn later on the page (invisible when rendered)."""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

import hidden_text

VISIBLE = "This sentence is printed in plain view for every reader."
UNDER_IMAGE = "This sentence sits under an opaque picture block."
UNDER_FILL = "This sentence sits under a white vector rectangle."
OVER_IMAGE = "This caption is printed on top of a background picture."


def opaque_pixmap():
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), 0)
    pix.clear_with(120)
    return pix


def make_hidden_pdf(path: Path) -> Path:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), VISIBLE, fontsize=11)
    page.insert_text((72, 200), UNDER_IMAGE, fontsize=11)
    page.insert_image(pymupdf.Rect(60, 180, 560, 215), pixmap=opaque_pixmap())  # drawn after the text: hides it
    page.insert_text((72, 300), UNDER_FILL, fontsize=11)
    page.draw_rect(pymupdf.Rect(60, 280, 560, 315), color=None, fill=(1, 1, 1))  # vector fill drawn after the text
    page.insert_image(pymupdf.Rect(60, 380, 560, 415), pixmap=opaque_pixmap())
    page.insert_text((72, 400), OVER_IMAGE, fontsize=11)  # drawn after the image: visible
    doc.save(path)
    return path


@pytest.fixture(scope="module")
def hidden_pdf(tmp_path_factory) -> Path:
    return make_hidden_pdf(tmp_path_factory.mktemp("hidden") / "hidden.pdf")


def test_text_under_a_later_image_is_hidden_by_image(hidden_pdf):
    found = hidden_text.hidden_text(hidden_pdf)[0]
    assert UNDER_IMAGE in found["image"]
    assert UNDER_IMAGE not in found["vector"]


def test_text_under_a_later_vector_fill_is_hidden_by_vector(hidden_pdf):
    found = hidden_text.hidden_text(hidden_pdf)[0]
    assert UNDER_FILL in found["vector"]
    assert UNDER_FILL not in found["image"]


def test_visible_text_and_text_drawn_over_an_image_are_not_hidden(hidden_pdf):
    found = hidden_text.hidden_text(hidden_pdf)[0]
    for text in (VISIBLE, OVER_IMAGE):
        assert text not in found["image"] and text not in found["vector"]


def test_pages_without_hidden_text_report_empty_strings(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), VISIBLE, fontsize=11)
    doc.save(tmp_path / "plain.pdf")
    assert hidden_text.hidden_text(tmp_path / "plain.pdf") == {0: {"image": "", "vector": ""}}


def test_only_requested_pages_are_examined(hidden_pdf):
    assert hidden_text.hidden_text(hidden_pdf, pages={0}).keys() == {0}
    assert hidden_text.hidden_text(hidden_pdf, pages=set()) == {}
