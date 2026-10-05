"""Hand-built PDF regressions for every Step 4b.2 reader fix."""
from __future__ import annotations

from eval.reading.metrics import Word as MetricWord, score_numbers
from matn_contracts.enums import HiddenReason, Visibility
from matn_reading.pdf_page import OpenPdf
from matn_reading.read import read_document, words_out

from .pdf_fixtures import write_pdf


IMAGE = (b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 "
         b"/Length 1 >>\nstream\n\x80\nendstream")


def test_geometry_builds_tex_words_tracking_and_font_change_and_glued_numbers(tmp_path):
    content = b"""BT /F1 10 Tf 72 700 Td (TeX) Tj ET
BT /F1 10 Tf 88 700 Td (word) Tj ET
BT /F1 10 Tf 72 670 Td (rate 6 . 2 vs48.0%) Tj ET
BT /F1 10 Tf 72 640 Td (4) Tj ET
BT /F2 10 Tf 77.6 640 Td (5 cases) Tj ET
"""
    path = write_pdf(tmp_path / "segments.pdf", content)
    with OpenPdf(path) as pdf:
        words = pdf.page(0).words
    texts = [word.text for word in words]
    assert "TeXword" in texts                 # geometric gap, no space char
    assert "6.2" in texts                     # tracked numeric label
    assert "vs48.0%" in texts                 # number glued to letters stays one source word
    assert "45" in texts                      # font change does not split a word
    report = score_numbers([MetricWord("vs48.0%")], [MetricWord("vs48.0%")])
    assert report.total == report.correct == 1


def test_dot_leader_is_not_glued_to_its_page_number(tmp_path):
    content = b"BT /F1 10 Tf 72 700 Td (Figure 1.2................13) Tj ET\n"
    path = write_pdf(tmp_path / "dot-leader.pdf", content)
    with OpenPdf(path) as pdf:
        texts = [word.text for word in pdf.page(0).words]
    assert "13" in texts
    assert all(not text.endswith("...13") for text in texts)


def test_close_text_lines_do_not_single_link_into_one_row(tmp_path):
    content = b"""BT /F1 6 Tf 72 700 Td (Intelligence, Final) Tj ET
BT /F1 6 Tf 72 693 Td (GAO-21-519SP) Tj ET
"""
    path = write_pdf(tmp_path / "close-lines.pdf", content)
    with OpenPdf(path) as pdf:
        texts = [word.text for word in pdf.page(0).words]
    assert "Intelligence," in texts
    assert "GAO-21-519SP" in texts


def test_giant_display_number_does_not_bridge_two_heading_rows(tmp_path):
    content = b"""BT /F1 170 Tf 300 200 Td (3.) Tj ET
BT /F2 23 Tf 72 190 Td (FRAMEWORK) Tj ET
BT /F2 23 Tf 72 162 Td (PRINCIPLE) Tj ET
"""
    path = write_pdf(tmp_path / "display-number.pdf", content)
    with OpenPdf(path) as pdf:
        texts = [word.text for word in pdf.page(0).words]
    assert "3." in texts
    assert "FRAMEWORK" in texts
    assert "PRINCIPLE" in texts


def test_superscript_marker_is_linked_and_excluded_from_prose_numbers(tmp_path):
    content = b"""BT /F1 10 Tf 72 700 Td (Evidence supports the reported result.) Tj ET
BT /F2 7 Tf 252 700.7 Td (1) Tj ET
BT /F1 7 Tf 72 80 Td (1 Staff estimate.) Tj ET
"""
    reading = read_document(write_pdf(tmp_path / "footnote.pdf", content))
    page = reading.pages[0]
    assert page.footnote_markers[0]["text"] == "1"
    assert page.footnote_markers[0]["linked_footnote_order"] is not None
    assert all(word.text != "1" for word, _ in words_out(page))


def test_footnote_body_prefix_is_a_linked_marker_not_a_prose_number(tmp_path):
    content = b"""BT /F1 10 Tf 72 700 Td (This body paragraph is deliberately longer than the footnote citation.) Tj ET
BT /F1 7 Tf 72 80 Td (25GAO-14-704G.) Tj ET
"""
    page = read_document(write_pdf(tmp_path / "footnote-prefix.pdf", content)).pages[0]
    assert any(marker["text"] == "25" and marker["linked_footnote_order"] is not None
               for marker in page.footnote_markers)
    output = [word.text for word, _ in words_out(page)]
    assert "25GAO-14-704G." not in output
    assert "GAO-14-704G." in output


def test_code_numbers_are_surfaced_as_non_prose_candidates(tmp_path):
    content = b"""BT /F1 9 Tf 72 700 Td (optimizer = AdamW(lr=0.9)) Tj ET
BT /F1 9 Tf 72 688 Td (# decay after 10 steps) Tj ET
BT /F1 9 Tf 72 676 Td (loss = loss * (1.0 + score)) Tj ET
"""
    page = read_document(write_pdf(tmp_path / "code.pdf", content)).pages[0]
    assert any(flag["kind"] == "code_text" for flag in page.flags)
    numeric_words = [(word.text, flagged) for word, flagged in words_out(page)
                     if any(char.isdigit() for char in word.text)]
    assert numeric_words and all(flagged for _, flagged in numeric_words)


def test_vertical_margin_text_keeps_matrix_order_and_is_marginalia(tmp_path):
    content = b"""BT /F1 10 Tf 0 1 -1 0 20 100 Tm (2026) Tj ET
BT /F1 10 Tf 72 700 Td (Body text remains prose.) Tj ET
"""
    reading = read_document(write_pdf(tmp_path / "vertical.pdf", content))
    vertical = next(block for block in reading.pages[0].blocks if block.layout.vertical)
    assert vertical.layout.text == "2026"
    assert vertical.block_type == "figure"
    assert any(flag["kind"] == "marginalia" for flag in reading.pages[0].flags)
    assert all(word.text != "2026" for word, _ in words_out(reading.pages[0]))


def test_sparse_vector_chart_with_numeric_labels_is_figure_text(tmp_path):
    content = b"""q 0 0 0 RG 100 400 m 100 600 l S 100 400 m 400 400 l S
120 400 30 80 re S 190 400 30 120 re S 260 400 30 150 re S
BT /F1 8 Tf 95 385 Td (0) Tj ET
BT /F1 8 Tf 95 435 Td (10) Tj ET
BT /F1 8 Tf 95 485 Td (20) Tj ET
BT /F1 8 Tf 95 535 Td (30) Tj ET
BT /F1 10 Tf 72 700 Td (Figure 1: Results) Tj ET
"""
    page = read_document(write_pdf(tmp_path / "chart.pdf", content)).pages[0]
    assert page.figure_regions
    assert any(block.block_type == "figure" and any(ch.isdigit() for ch in block.layout.text)
               for block in page.blocks)
    assert any(block.block_type == "caption" for block in page.blocks)


def test_side_heading_within_half_line_leads_its_paragraph(tmp_path):
    content = b"""BT /F2 10 Tf 40 687 Td (Introduction) Tj ET
BT /F1 10 Tf 200 692 Td (The paragraph starts five points higher.) Tj ET
BT /F1 10 Tf 200 680 Td (It continues on the next line.) Tj ET
BT /F2 10 Tf 40 600 Td (Scope) Tj ET
BT /F1 10 Tf 200 600 Td (A second paragraph establishes the gutter.) Tj ET
BT /F1 10 Tf 200 588 Td (It also continues.) Tj ET
"""
    page = read_document(write_pdf(tmp_path / "side-heading.pdf", content)).pages[0]
    texts = [block.layout.text for block in page.blocks]
    assert texts.index("Introduction") < next(i for i, text in enumerate(texts) if text.startswith("The paragraph"))


def test_bold_lead_sentence_stays_in_its_paragraph(tmp_path):
    content = b"""BT /F2 10 Tf 72 700 Td (Key finding.) Tj ET
BT /F1 10 Tf 72 688 Td (The explanation continues in regular type.) Tj ET
"""
    page = read_document(write_pdf(tmp_path / "bold-lead.pdf", content)).pages[0]
    assert any(block.layout.text == "Key finding. The explanation continues in regular type." for block in page.blocks)


def test_visibility_splits_outside_cropbox_and_later_image_from_prose(tmp_path):
    content = b"""BT /F1 10 Tf 72 600 Td (Visible 111) Tj ET
BT /F1 10 Tf 72 750 Td (Outside 222) Tj ET
BT /F1 10 Tf 72 500 Td (Covered 333) Tj ET
q 100 0 0 20 65 495 cm /Im1 Do Q
"""
    path = write_pdf(tmp_path / "visibility.pdf", content, cropbox=(0, 0, 612, 700),
                     extra_resources=b"/XObject << /Im1 7 0 R >> ", extra_objects=(IMAGE,))
    page = read_document(path).pages[0]
    hidden = [block.contract for block in page.blocks if block.contract.visibility is Visibility.HIDDEN]
    reasons = {reason for block in hidden for reason in block.visibility_reasons}
    assert HiddenReason.OUTSIDE_CROPBOX in reasons
    assert HiddenReason.COVERED_BY_IMAGE in reasons
    prose = [word.text for word, _ in words_out(page)]
    assert "111" in prose and "222" not in prose and "333" not in prose
    assert any(flag["kind"] == "hidden_text" and flag["severity"] == "error" for flag in page.flags)
    assert any(flag["kind"] == "outside_cropbox" and flag["severity"] == "warning" for flag in page.flags)
