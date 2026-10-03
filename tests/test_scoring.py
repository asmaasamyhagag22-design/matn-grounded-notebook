"""Step 2c primitives on hand-built inputs: layout scores, hard rejections, title typography, number visuals and
chart rules."""
from __future__ import annotations

from decimal import Decimal

from matn_contracts.domain import ChartSpec, NumberFactValue
from matn_contracts.enums import ChartType
from matn_deck.chart_rules import data_shape, decide, load_rules, read_table
from matn_deck.number_visuals import percentage, pictogram, progress_fraction
from matn_deck.scoring import (
    Element,
    Rect,
    SlideContext,
    balance_score,
    collisions,
    density_score,
    fill_ratio,
    fill_score,
    hard_violations,
    hierarchy_score,
    load_scoring,
    score,
    vertical_score,
)
from matn_deck.specimen import sample_fact, sample_table
from matn_deck.typography import balanced_lines, keep_caps

PT = 12700
AREA = Rect(0, 0, 800 * PT, 400 * PT)
SLIDE = Rect(0, -100 * PT, 960 * PT, 540 * PT)
CFG = load_scoring()


def ctx(**kw) -> SlideContext:
    return SlideContext(**{"content_slide": True, "area": AREA, "safe": AREA, "slide": SLIDE, "title_pt": 28, **kw})


def box(x, y, w, h) -> Rect:
    return Rect(x * PT, y * PT, w * PT, h * PT)


def text(name, rect, size=18, role="item", **kw) -> Element:
    return Element(name, kw.pop("kind", "text"), rect, role=role, size_pt=size, **kw)


# ---- soft scores ------------------------------------------------------------------------------------------------

def test_fill_counts_union_of_content_and_scores_the_target_band():
    half = [text("a", box(0, 0, 400, 400)), text("b", box(200, 0, 200, 400))]  # b lies inside a: counted once
    assert abs(fill_ratio(half, AREA) - 0.5) < 0.02
    card = Element("card", "card", box(0, 0, 800, 400), container=True)
    assert fill_ratio([card], AREA) == 0  # containers are not fill
    low, high = CFG["fill"]["band"]
    assert fill_score(0.6, CFG) == 1.0 and fill_score(low, CFG) == 1.0 and fill_score(high, CFG) == 1.0
    assert fill_score(0.15, CFG) < fill_score(0.3, CFG) < 1.0
    assert fill_score(0.98, CFG) < 1.0


def test_balance_is_best_when_the_weight_sits_at_the_center():
    centered = [text("a", box(300, 150, 200, 100))]
    corner = [text("a", box(0, 0, 200, 100))]
    pair = [text("a", box(0, 150, 200, 100)), text("b", box(600, 150, 200, 100))]
    assert balance_score(centered, AREA, CFG) > 0.99
    assert balance_score(pair, AREA, CFG) > 0.99
    assert balance_score(corner, AREA, CFG) < 0.2


def test_vertical_distribution_wants_content_in_the_lower_part_unless_a_centered_hero():
    top_only = [text("a", box(0, 0, 800, 120))]
    full = [text("a", box(0, 0, 800, 120)), text("b", box(0, 300, 800, 90))]
    assert vertical_score(top_only, ctx(), CFG) == 0
    assert vertical_score(full, ctx(), CFG) == 1
    assert vertical_score(top_only, ctx(centered_hero=True), CFG) == 1


def test_collision_ignores_containers_and_touching_edges():
    a, b = text("a", box(0, 0, 100, 50)), text("b", box(100, 0, 100, 50))
    c = text("c", box(50, 25, 100, 50))
    card = Element("card", "card", box(0, 0, 400, 100), container=True)
    assert collisions([a, b, card]) == []
    assert collisions([a, b, c]) == [("a", "c"), ("b", "c")]


def test_hierarchy_needs_title_body_and_kpi_value_label_ratios():
    good = [text("item", box(0, 0, 10, 10), size=18), text("v", box(0, 0, 10, 10), size=60, role="kpi_value"),
            text("l", box(0, 0, 10, 10), size=18, role="kpi_label")]
    assert hierarchy_score(good, ctx(title_pt=28), CFG) == 1.0
    flat = [text("item", box(0, 0, 10, 10), size=24), text("v", box(0, 0, 10, 10), size=36, role="kpi_value"),
            text("l", box(0, 0, 10, 10), size=24, role="kpi_label")]
    assert hierarchy_score(flat, ctx(title_pt=28), CFG) < 0.6


def test_density_penalizes_sparse_and_cluttered_slides():
    spread = [text(f"t{i}", box(i * 200 + 10, j * 100 + 10, 180, 80)) for i in range(4) for j in range(4)]
    sparse = [text("a", box(0, 0, 150, 80))]
    clutter = [text(f"t{i}", box(5 * i, 5 * i, 12, 12)) for i in range(12)]
    assert density_score(spread, AREA, CFG) > 0.95
    assert density_score(sparse, AREA, CFG) < 0.5
    assert density_score(clutter, AREA, CFG) < density_score(sparse, AREA, CFG)


# ---- hard rejections --------------------------------------------------------------------------------------------

def test_hard_constraints_reject_with_reasons():
    visual = Element("card_1", "card", box(0, 0, 400, 400), container=True)
    ok = [visual, text("item_1", box(20, 20, 300, 100))]
    assert hard_violations(ok, ctx()) == []
    cases = {
        "OVERFLOW:item_1": [visual, text("item_1", box(20, 20, 300, 100), overflow=True)],
        "OUT_OF_BOUNDS:item_1": [visual, text("item_1", box(700, 20, 300, 100))],
        "TEXT_TOO_SMALL:item_1:14": [visual, text("item_1", box(20, 20, 300, 100), size=14)],
        "TITLE_TOO_SMALL:title:24": [visual, text("title", box(0, -90, 800, 60), size=24, kind="title")],
        "EMPTY:card_1": [Element("card_1", "card", box(0, 0, 400, 400), container=True, empty=True),
                         text("item_1", box(20, 20, 300, 100))],
        "NO_VISUAL": [text("item_1", box(20, 20, 300, 100))],
        "COLLISION:item_1:item_2": [visual, text("item_1", box(20, 20, 300, 100)),
                                    text("item_2", box(20, 60, 300, 100))],
    }
    for reason, elements in cases.items():
        assert any(v.startswith(reason) for v in hard_violations(elements, ctx())), reason
    low = [visual, text("item_1", box(20, 20, 300, 100), size=16, contrast=3.2)]
    assert hard_violations(low, ctx()) == ["LOW_CONTRAST:item_1:3.20<4.5"]
    large = [visual, text("item_1", box(20, 20, 300, 100), size=24, contrast=3.2)]
    assert hard_violations(large, ctx()) == []  # large text needs 3.0
    assert hard_violations([text("item_1", box(20, 20, 300, 100))], ctx(content_slide=False)) == []


def test_score_combines_weights_and_reports_fill_ratio():
    elements = [Element("card_1", "card", box(0, 0, 800, 400), container=True),
                text("item_1", box(40, 40, 720, 300), size=18)]
    result = score(elements, ctx(), variety=0.0)
    assert result.ok and 0 < result.total < 1
    assert result.soft["variety"] == 0 and result.soft["fill_ratio"] > 0.6
    assert score(elements, ctx(), variety=1.0).total > result.total


# ---- typography -------------------------------------------------------------------------------------------------

def test_balanced_title_breaks_keep_the_text_and_avoid_an_orphan():
    width = len  # one unit per character
    title = "Rural offices adopt the sample service more slowly than urban ones"
    greedy = ["Rural offices adopt the sample service more slowly than urban", "ones"]
    lines = balanced_lines(title, 62, width, greedy)
    assert " ".join(lines) == title and len(lines) == 2
    assert len(lines[-1].split()) > 1
    assert abs(len(lines[0]) - len(lines[1])) <= 8
    assert balanced_lines("Short title", 62, width, ["Short title"]) == ["Short title"]


def test_caps_stay_only_on_short_labels():
    assert keep_caps("Key numbers", True)
    assert not keep_caps("Rural offices adopt the sample service more slowly", True)
    assert not keep_caps("Key numbers", False)


# ---- number visuals ---------------------------------------------------------------------------------------------

def value(written, unit=None) -> NumberFactValue:
    return NumberFactValue(label="Sample", value_as_written=written, unit=unit, page_label=None)


def test_progress_bars_only_for_percentages_between_0_and_100():
    assert progress_fraction(value("72", "%")) == Decimal("0.72")
    assert progress_fraction(value("100", "%")) == Decimal("1")
    for written, unit in (("140", "%"), ("72", None), ("1,240", None), ("4.5", "days"), ("about 70", "%")):
        assert progress_fraction(value(written, unit)) is None, written
    assert percentage(value("18", "%")) == Decimal("18")


def test_pictograms_only_for_small_ratios_and_exact_tens():
    assert pictogram(value("3 in 10")) == (3, 10)
    assert pictogram(value("1 in 4")) == (1, 4)
    assert pictogram(value("40", "%")) == (4, 10)
    assert pictogram(value("40.0", "%")) == (4, 10)
    for written, unit in (("72", "%"), ("1 in 25", None), ("45", "%"), ("4.5", "days"), ("12 in 10", None)):
        assert pictogram(value(written, unit)) is None, written  # never rounded into a pictogram


# ---- chart rules ------------------------------------------------------------------------------------------------

def chart(rows, cited=(), y=(1,)):
    table = sample_table(rows, 9)
    spec = ChartSpec(table_id=table.table_id, x_column=0, y_columns=y, chart_type=ChartType.COLUMN)
    return decide(table, spec, list(cited))


def test_chart_type_comes_from_the_data_shape():
    years = [["Year", "Value"], ["2021", "4"], ["2022", "6"], ["2023", "9"], ["2024", "12"], ["2025", "18"]]
    assert (chart(years).shape, chart(years).kind) == ("time_series", "column")
    longer = years + [["2026", "20"]]
    assert chart(longer).kind == "line"
    parts = [["Part", "Share"], ["A", "50%"], ["B", "30%"], ["C", "20%"]]
    assert (chart(parts).shape, chart(parts).kind) == ("part_to_whole", "stacked_bar")
    regions = [["Region", "Value"], ["A", "3"], ["B", "9"], ["C", "5"]]
    decision = chart(regions)
    assert (decision.shape, decision.kind) == ("categorical", "bar")
    assert decision.categories == ("B", "C", "A") and decision.sorted_rows  # sorted, values move with their rows
    assert [s.texts for s in decision.series] == [("9", "5", "3")]
    many = [["Item", "Value"]] + [[f"Item {i}", str(i)] for i in range(1, 10)]
    assert chart(many).kind == "column" and not chart(many).sorted_rows
    quarters = [["Quarter", "Value"], ["Q3 2024", "1"], ["Q4 2024", "2"], ["Q1 2025", "3"]]
    assert chart(quarters).shape == "time_series"


def test_the_key_point_is_the_cited_number_otherwise_the_maximum():
    years = [["Year", "Value"], ["2023", "9.5"], ["2024", "12.0"], ["2025", "11.0"]]
    assert chart(years).key == (0, 1) and chart(years).key_fact_id is None
    cited = sample_fact("Sample: 9.5 in 2023.", "Sample text: 9.5 in 2023.", 9, number=("Sample 2023", "9.5", None))
    decision = chart(years, cited=[cited])
    assert decision.key == (0, 0) and decision.key_fact_id == cited.fact_id
    table = sample_table(years, 9)
    categories, series, number_format = read_table(
        table, ChartSpec(table_id=table.table_id, x_column=0, y_columns=(1,), chart_type=ChartType.BAR), "S{n}")
    assert number_format == "0.0" and series[0].texts == ("9.5", "12.0", "11.0")
    assert data_shape(categories, series, load_rules()) == "time_series"
