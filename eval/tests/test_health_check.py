"""Text-layer health check per page: flags pages that look scanned or garbled. Metrics only, never text."""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest

import cross_check
import health_check as hc

BODY = ("The pilot tested an evidence-first review workflow with eight volunteers. "
        "Reviewers checked every claim against its source page and recorded the result. "
        "Notes without a source page were returned to their authors, and the team met weekly to compare findings.")


def clean(**overrides) -> dict:
    metrics = {"chars": 900, "alpha_ratio": 0.8, "bad_chars": 0, "image_coverage": 0.0, "tokens": 120,
               "second_tokens": 118, "overlap": 0.97}
    metrics.update(overrides)
    return metrics


@pytest.mark.parametrize("name,overrides,flags", [
    ("normal page", {}, []),
    ("no text at all", {"chars": 0, "alpha_ratio": 0.0, "tokens": 0, "overlap": None}, ["NO_TEXT"]),
    ("full-page image, little text", {"chars": 142, "image_coverage": 1.0, "tokens": 6, "overlap": None},
     ["LOOKS_SCANNED", "LOW_TEXT"]),
    ("short page without images", {"chars": 120, "tokens": 15, "overlap": None}, ["LOW_TEXT"]),
    ("image with plenty of text (a figure page)", {"image_coverage": 0.9}, []),
    ("replacement / private-use / cid glyphs", {"bad_chars": 30}, ["GARBLED"]),
    ("almost no letters on a long page", {"alpha_ratio": 0.1}, ["GARBLED"]),
    ("extractors disagree", {"overlap": 0.4}, ["EXTRACTORS_DISAGREE"]),
])
def test_classify(name, overrides, flags):
    assert hc.classify(clean(**overrides)) == flags, name


def test_blocking_flags_are_the_ones_that_stop_registration():
    assert hc.BLOCKING == {"NO_TEXT", "LOOKS_SCANNED", "GARBLED", "EXTRACTORS_DISAGREE"}


@pytest.mark.parametrize("text,expected", [("abc �", 1), ("xy", 1), ("(cid:12) and (cid:7)", 2), ("plain", 0)])
def test_bad_chars(text, expected):
    assert hc.bad_chars(text) == expected


def test_overlap_is_symmetric_and_bounded():
    assert hc.token_overlap(BODY, BODY) == 1.0
    assert hc.token_overlap(BODY, "completely unrelated words appear here instead") < 0.2
    assert hc.token_overlap("", "") is None


@pytest.mark.skipif(cross_check.second_extractor() is None, reason="pdftotext not on PATH")
def test_page_metrics_on_real_pdf_pages(tmp_path):
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(72, 72, 540, 400), BODY, fontsize=11)
    image_page = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 16, 16), 0)
    pix.clear_with(200)
    image_page.insert_image(image_page.rect, pixmap=pix)
    image_page.insert_text((72, 72), "Public Disclosure Authorized", fontsize=9)
    doc.new_page()  # blank
    pdf = tmp_path / "doc.pdf"
    doc.save(pdf)
    report = hc.check_pdf(pdf)
    assert [p["flags"] for p in report] == [[], ["LOOKS_SCANNED", "LOW_TEXT"], ["NO_TEXT"]]
    assert report[0]["overlap"] > 0.9 and report[1]["image_coverage"] > 0.99
    assert BODY[:30] not in json.dumps(report)  # numbers only (standing rule 8)
