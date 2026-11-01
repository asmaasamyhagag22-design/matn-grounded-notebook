"""Chart honesty and disagreement rules (ADR-0023)."""
from dataclasses import replace

from matn_deck.numeric import conflicts, decide_visual, facts_for_unit, measure
from tests.deck_v2.catalog_fixture import make_catalog, unit


def _setup(*units):
    facts = tuple(f for u in units for f in facts_for_unit(u))
    return facts, {u.id: u.source for u in units}, {u.id: u.text for u in units}


def test_numbers_are_copied_and_years_are_periods():
    u = unit("U1", "a", "In 2024, 38% of firms will train staff in Egypt.")
    (fact,) = facts_for_unit(u)
    assert fact.value_as_written == "38%" and u.text[fact.start:fact.end] == "38%"
    assert fact.period == ("2024",) and fact.geography == "Egypt" and fact.population == "firms"


def test_a_unit_with_a_quantity_parse_problem_contributes_no_numbers():
    assert facts_for_unit(unit("U1", "a", "Two-sevenths of agencies replied in 2023.")) == ()


def test_different_measures_never_chart_or_disagree():
    facts, sources, texts = _setup(unit("U1", "a", "30% of firms will train staff in Egypt by 2030."),
                                   unit("U2", "a", "55% of firms will hire staff in Egypt by 2030.", source="S2"))
    assert measure(texts["U1"], 0, 3) != measure(texts["U2"], 0, 3)
    assert conflicts(facts, sources, texts) == []
    assert decide_visual(facts, sources, texts).kind == "table"


def test_incomparable_scope_never_charts_together():
    facts, sources, texts = _setup(unit("U1", "a", "In 2022, 30% of firms will train staff in Egypt."),
                                   unit("U2", "a", "In 2024, 38% of firms will train staff in Morocco."))
    decision = decide_visual(facts, sources, texts)
    assert decision.kind == "table" and "NO_SINGLE_EXPLICIT_DIMENSION" in decision.reason


def test_unknown_scope_never_charts():
    facts, sources, texts = _setup(unit("U1", "a", "Employers foresee that 29 could be upskilled."),
                                   unit("U2", "a", "Employers foresee that 11 could be upskilled."))
    assert decide_visual(facts, sources, texts).kind == "table"


def test_same_measure_across_years_charts_with_explicit_categories_and_copied_values():
    facts, sources, texts = _setup(unit("U2", "a", "In 2024, 38% of firms will train staff in Egypt."),
                                   unit("U1", "a", "In 2022, 30% of firms will train staff in Egypt."))
    decision = decide_visual(facts, sources, texts)
    assert decision.kind == "chart" and decision.dimension == "period"
    assert decision.categories == ("2022", "2024")
    assert [f.value_as_written for f in decision.facts] == ["30%", "38%"]


def test_conflicting_sources_disagree_and_are_never_charted_or_averaged():
    facts, sources, texts = _setup(
        unit("U1", "a", "41% of firms will adopt AI tools in Egypt by 2030."),
        unit("U2", "a", "45% of firms will adopt AI tools in Egypt by 2030.", source="S2"))
    (clash,) = conflicts(facts, sources, texts)
    assert {f.value_as_written for f in clash.facts} == {"41%", "45%"}
    decision = decide_visual(facts, sources, texts)
    assert decision.kind == "table" and "SOURCES_DISAGREE" in decision.reason


def test_same_source_same_value_is_not_a_disagreement():
    facts, sources, texts = _setup(
        unit("U1", "a", "41% of firms will adopt AI tools in Egypt by 2030."),
        unit("U2", "a", "41% of firms will adopt AI tools in Egypt by 2030.", source="S2"))
    assert conflicts(facts, sources, texts) == []


def test_fixture_has_exactly_one_disagreement():
    catalog = make_catalog(with_figure=False)
    sources = {u.id: u.source for u in catalog.units}
    texts = {u.id: u.text for u in catalog.units}
    (clash,) = conflicts(catalog.numbers, sources, texts)
    assert {f.unit_id for f in clash.facts} == {"U6", "U7"}
