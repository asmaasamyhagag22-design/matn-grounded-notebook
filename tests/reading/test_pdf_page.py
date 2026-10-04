"""PDF adapters on a generated PDF: words, render modes, signals and the three baseline edge-case counts."""
from __future__ import annotations

from matn_reading.pdf_page import OpenPdf

from .pdf_fixtures import EDGE_CASES, write_pdf


def test_edge_case_counts_on_a_generated_page(tmp_path):
    path = write_pdf(tmp_path / "edge.pdf", EDGE_CASES, cropbox=(0, 0, 612, 700))
    with OpenPdf(path) as pdf:
        page = pdf.page(0)
    assert page.edge_cases == {"mode3_without_image": len("Invisible222"),
                               "outside_cropbox": len("OutsideCrop333") + len("OffPage555"),
                               "near_zero_font": len("TinyFont444")}
    modes = {o.text: o.render_mode for o in page.text_objects}
    assert modes["Invisible 222"] == 3 and modes["Visible 111"] == 0
    assert page.cropbox == (0.0, 92.0, 612.0, 792.0)


def test_words_carry_size_and_bold(tmp_path):
    content = b"BT /F2 18 Tf 72 700 Td (Heading) Tj ET\nBT /F1 10 Tf 72 680 Td (body 3.2% in 2021) Tj ET\n"
    path = write_pdf(tmp_path / "words.pdf", content)
    with OpenPdf(path) as pdf:
        page = pdf.page(0)
    by_text = {w.text: w for w in page.words}
    assert by_text["Heading"].bold and by_text["Heading"].size == 18
    assert not by_text["3.2%"].bold and by_text["3.2%"].size == 10
    assert page.signals.chars == len("Heading" "body3.2%in2021")
    assert page.signals.agreement == 1.0 and page.signals.invisible_chars == 0
