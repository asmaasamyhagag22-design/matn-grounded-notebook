"""Storyboard v2: a pure function of catalog + measured fit + controls (ADR-0022)."""
import re
from dataclasses import replace

import pytest

from matn_deck.deck_qa import storyboard_fidelity
from matn_deck.storyboard_v2 import Controls, axis_title, build_storyboard
from tests.deck_v2.catalog_fixture import make_catalog

FITS = lambda text: len(text) <= 100  # noqa: E731  (a deterministic stand-in for the template measurement)


@pytest.fixture
def catalog():
    return make_catalog(with_figure=False)


def test_byte_identical_for_the_same_input(catalog):
    one = build_storyboard(catalog, FITS, Controls(date="2026-10-29"))
    two = build_storyboard(make_catalog(with_figure=False), FITS, Controls(date="2026-10-29"))
    assert one.to_json() == two.to_json()


def test_sequence_and_every_string_traces_to_the_catalog(catalog):
    story = build_storyboard(catalog, FITS, Controls(date="2026-10-29"))
    kinds = [s.kind for s in story.slides]
    assert kinds[:2] == ["title", "agenda"] and kinds[-3:] == ["gaps", "sources", "methods"]
    assert storyboard_fidelity(story, catalog) == []


def test_headline_rule(catalog):
    story = build_storyboard(catalog, FITS, Controls(date="2026-10-29"))
    by_axis = {s.axis: s for s in story.slides if s.kind == "assertion"}
    assert by_axis["a2"].title.kind == "synthesis"  # a shown synthesis sentence whose units are all on the axis
    assert by_axis["a1"].title.kind == "unit" and by_axis["a1"].title.ref == "U1"  # the shortest unit that fits
    assert "U1" not in [b.unit_id for b in by_axis["a1"].bullets]  # never repeated as a bullet
    nothing_fits = build_storyboard(catalog, lambda t: False, Controls(date="2026-10-29"))
    titles = {s.axis: s.title for s in nothing_fits.slides if s.kind == "assertion"}
    assert titles["a1"].kind == "axis" and titles["a1"].text == "Queue practices"


def test_every_bullet_cites_a_source_that_resolves(catalog):
    story = build_storyboard(catalog, FITS, Controls(date="2026-10-29"))
    sources = next(s for s in story.slides if s.kind == "sources")
    numbered = {line.marker for line in sources.lines}
    for slide in story.slides:
        for bullet in slide.bullets:
            assert re.fullmatch(r"\[\d+\]", bullet.text.marker)
            assert bullet.text.marker in numbered


def test_conflicting_facts_always_produce_a_disagreement_slide(catalog):
    story = build_storyboard(catalog, FITS, Controls(date="2026-10-29"))
    (disagree,) = [s for s in story.slides if s.kind == "disagree"]
    assert [b.unit_id for b in disagree.bullets] == ["U6", "U7"]
    assert [t.text for t in disagree.item_titles] == ["Example Ministry states", "Example Agency states"]


def test_no_ellipsis_and_no_new_numbers(catalog):
    story = build_storyboard(catalog, FITS, Controls(date="2026-10-29"))
    unit_text = " ".join(u.text for u in catalog.units)
    for slide in story.slides:
        for text in [slide.title, *[b.text for b in slide.bullets]]:
            assert "…" not in text.text and "..." not in text.text
            for number in re.findall(r"\d+%?", text.text):
                assert number in unit_text or text.kind == "label"


def test_detail_and_target_never_drop_content(catalog):
    standard = build_storyboard(catalog, FITS, Controls(date="2026-10-29"))
    summary = build_storyboard(catalog, FITS, Controls(detail="summary", date="2026-10-29"))
    shown = lambda s: {b.unit_id for x in s.slides for b in x.bullets} | {  # noqa: E731
        x.title.ref for x in s.slides if x.title.kind == "unit"}
    assert shown(summary) == shown(standard) == {u.id for u in catalog.units}
    targeted = build_storyboard(catalog, FITS, Controls(target_slides=6, date="2026-10-29"))
    assert any(d.startswith("TARGET") for d in targeted.decisions)
    assert shown(targeted) == {u.id for u in catalog.units}


def test_audience_control_changes_only_the_title_slide(catalog):
    story = build_storyboard(catalog, FITS, Controls(audience="regional directors", date="2026-10-29"))
    assert story.slides[0].lines[0].text == "regional directors"
    assert story.controls.audience == "regional directors"


def test_axis_title_only_reformats_snake_case():
    assert axis_title("financial_roi_and_payback") == "Financial roi and payback"
    assert axis_title("Operational Efficiency Strategies") == "Operational Efficiency Strategies"
