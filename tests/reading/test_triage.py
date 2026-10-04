"""Step 4b triage: one route per page, always with recorded reasons."""
from __future__ import annotations

from matn_reading.triage import PageSignals, Route, decide_route, glyph_issues, text_agreement


def _signals(**overrides) -> PageSignals:
    values = dict(chars=2400, visible_chars=2400, invisible_chars=0, broken_glyphs=0, text_coverage=0.25,
                  image_coverage=0.0, agreement=1.0)
    values.update(overrides)
    return PageSignals(**values)


def test_glyph_issues_counts_replacement_private_use_and_cid():
    counts = glyph_issues("10:30�11:00  (cid:42) ok")
    assert counts == {"replacement_char": 1, "private_use": 1, "cid": 1}
    assert glyph_issues("plain text 3.2%") == {"replacement_char": 0, "private_use": 0, "cid": 0}


def test_text_agreement_ignores_whitespace_and_order_noise():
    assert text_agreement("GDP grew 3.2%\nin 2021", "GDP  grew 3.2% in 2021") == 1.0
    assert text_agreement("abc", "xyz") < 0.5
    assert text_agreement("", "") == 1.0


def test_healthy_digital_page():
    route, reasons = decide_route(_signals())
    assert route is Route.DIGITAL_HEALTHY
    assert reasons and all(isinstance(r, str) for r in reasons)


def test_broken_glyphs_route_to_digital_broken():
    route, reasons = decide_route(_signals(broken_glyphs=12))
    assert route is Route.DIGITAL_BROKEN
    assert any("broken_glyphs" in r for r in reasons)


def test_extractor_disagreement_routes_to_digital_broken():
    route, reasons = decide_route(_signals(agreement=0.80))
    assert route is Route.DIGITAL_BROKEN
    assert any("agreement" in r for r in reasons)


def test_image_page_with_little_text_is_scanned():
    route, reasons = decide_route(_signals(chars=0, visible_chars=0, text_coverage=0.0, image_coverage=0.98))
    assert route is Route.SCANNED
    assert any("image_coverage" in r for r in reasons)


def test_invisible_text_over_a_page_image_is_an_ocr_layer_not_hidden_text():
    route, reasons = decide_route(_signals(visible_chars=0, invisible_chars=2400, image_coverage=0.99))
    assert route is Route.SCANNED_WITH_OCR_LAYER
    assert any("render_mode_3" in r for r in reasons)


def test_invisible_text_without_a_page_image_is_not_called_an_ocr_layer():
    route, _ = decide_route(_signals(visible_chars=2000, invisible_chars=400, image_coverage=0.0))
    assert route is not Route.SCANNED_WITH_OCR_LAYER


def test_digital_text_plus_a_large_image_is_mixed():
    route, reasons = decide_route(_signals(image_coverage=0.45))
    assert route is Route.MIXED
    assert any("image_coverage" in r for r in reasons)


def test_blank_page_is_scanned_route_so_it_is_never_passed_as_clean_text():
    route, reasons = decide_route(_signals(chars=0, visible_chars=0, text_coverage=0.0, image_coverage=0.0))
    assert route is Route.SCANNED
    assert any("no_text" in r for r in reasons)
