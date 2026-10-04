"""Step 4a: reading metrics. The key metric is silent_errors (a wrong number nobody flagged); its target is 0."""
from __future__ import annotations

import pytest

from eval.reading.metrics import (
    Cell,
    Word,
    aggregate,
    block_type_accuracy,
    cer,
    levenshtein,
    match_blocks,
    reading_order_accuracy,
    score_numbers,
    teds,
    wer,
)


# ---- CER / WER ---------------------------------------------------------------------------------------------------

def test_levenshtein_basic_cases():
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3
    assert levenshtein(["a", "b"], ["a", "b"]) == 0


def test_cer_and_wer():
    assert cer("abcd", "abcd") == 0.0
    assert cer("abcd", "abxd") == pytest.approx(0.25)
    assert wer("the gdp grew 3.2 percent", "the gdp grew 3.7 percent") == pytest.approx(0.2)
    assert wer("a  b\nc", "a b c") == 0.0  # whitespace is normalized before WER
    assert cer("", "") == 0.0
    assert cer("", "x") == 1.0


# ---- numbers -----------------------------------------------------------------------------------------------------

def _w(text, x, flagged=False):
    return Word(text, (x, 0.0, x + 10.0, 10.0), flagged)


def test_all_numbers_read_exactly():
    gt = [_w("GDP", 0), _w("grew", 20), _w("3.2%", 40), _w("in", 60), _w("2021.", 80)]
    report = score_numbers(gt, list(gt))
    assert (report.total, report.correct, report.silent_errors) == (2, 2, 0)
    assert report.accuracy == 1.0


def test_a_wrong_unflagged_number_is_a_silent_error():
    gt = [_w("3.2%", 0), _w("2021", 20)]
    hyp = [_w("3.7%", 0), _w("2021", 20)]
    report = score_numbers(gt, hyp)
    assert (report.correct, report.wrong, report.silent_errors) == (1, 1, 1)
    assert report.details[0]["status"] == "wrong" and report.details[0]["expected"] == "3.2"


def test_a_wrong_but_flagged_number_is_not_silent():
    report = score_numbers([_w("3.2", 0)], [_w("3.7", 0, flagged=True)])
    assert (report.wrong, report.silent_errors, report.flagged_wrong) == (1, 0, 1)


def test_a_missing_number_is_a_silent_drop_not_a_silent_error():
    report = score_numbers([_w("64", 0), _w("x", 20)], [_w("x", 20)])
    assert (report.missing, report.silent_drops, report.silent_errors) == (1, 1, 0)
    assert report.accuracy == 0.0


def test_an_inserted_number_counts_as_a_silent_error():
    # "Il" read as "11": a number that does not exist in the source enters the text unflagged.
    report = score_numbers([_w("Il", 0)], [_w("11", 0)])
    assert (report.total, report.inserted, report.silent_errors) == (0, 1, 1)


def test_numbers_are_matched_by_position_so_a_swap_is_caught():
    gt = [_w("12", 0), _w("21", 20)]
    hyp = [_w("21", 0), _w("12", 20)]
    report = score_numbers(gt, hyp)
    assert report.wrong == 2 and report.silent_errors == 2


def test_without_boxes_numbers_are_aligned_in_sequence():
    gt = [Word("a"), Word("12"), Word("b"), Word("21")]
    hyp = [Word("a"), Word("12"), Word("b"), Word("27")]
    report = score_numbers(gt, hyp)
    assert (report.correct, report.wrong, report.silent_errors) == (1, 1, 1)


def test_one_word_can_hold_several_numbers():
    report = score_numbers([_w("2019-2021", 0)], [_w("2019-2021", 0)])
    assert (report.total, report.correct) == (2, 2)


# ---- tables (TEDS) -----------------------------------------------------------------------------------------------

def test_tree_edit_distance_matches_the_zhang_shasha_textbook_example():
    from eval.reading.metrics import _Node, tree_edit_distance

    def n(tag, *children):
        return _Node(tag, children=list(children))

    a = n("f", n("d", n("a"), n("c", n("b"))), n("e"))
    b = n("f", n("c", n("d", n("a"), n("b"))), n("e"))
    assert tree_edit_distance(a, b) == 2


def test_teds_identical_tables_score_one():
    table = [["Year", "GDP"], ["2020", "3.6"], ["2021", "3.3"]]
    assert teds(table, table) == 1.0


def test_teds_penalizes_cell_content_and_structure():
    gt = [["Year", "GDP"], ["2020", "3.6"], ["2021", "3.3"]]
    content = [["Year", "GDP"], ["2020", "3.6"], ["2021", "3.8"]]
    missing_row = [["Year", "GDP"], ["2020", "3.6"]]
    assert 0.9 < teds(gt, content) < 1.0
    assert teds(gt, missing_row) < teds(gt, content)
    assert teds(gt, content, structure_only=True) == 1.0


def test_teds_counts_spans():
    gt = [[Cell("Total", colspan=2)], ["a", "b"]]
    pred = [["Total", ""], ["a", "b"]]
    assert teds(gt, pred) < 1.0
    assert teds(gt, [[Cell("Total", colspan=2)], ["a", "b"]]) == 1.0


def test_teds_empty_tables():
    assert teds([], []) == 1.0
    assert teds([["a"]], []) == 0.0


# ---- reading order and block types -------------------------------------------------------------------------------

def test_reading_order_accuracy():
    assert reading_order_accuracy(["a", "b", "c", "d"], ["a", "b", "c", "d"]) == 1.0
    assert reading_order_accuracy(["a", "b", "c", "d"], ["a", "c", "b", "d"]) == pytest.approx(0.5)
    assert reading_order_accuracy([], []) == 1.0


def test_match_blocks_and_block_type_accuracy():
    gt = [("g1", (0, 0, 100, 20), "heading"), ("g2", (0, 30, 100, 90), "text"), ("g3", (0, 100, 100, 120), "footer")]
    pred = [("p1", (1, 1, 99, 21), "heading"), ("p2", (0, 31, 100, 88), "list_item")]
    pairs = match_blocks([(i, b) for i, b, _ in gt], [(i, b) for i, b, _ in pred])
    assert pairs == {"p1": "g1", "p2": "g2"}
    gt_types = {i: t for i, _, t in gt}
    pred_types = {i: t for i, _, t in pred}
    accuracy, matched, total = block_type_accuracy(gt_types, pred_types, pairs)
    assert (matched, total) == (1, 3)
    assert accuracy == pytest.approx(1 / 3)


# ---- aggregation per page type -----------------------------------------------------------------------------------

def test_aggregate_reports_each_page_type_separately():
    rows = [
        {"page_type": "digital", "char_edits": 0, "chars": 100, "word_edits": 0, "words": 20,
         "numbers": 5, "numbers_correct": 5, "silent_errors": 0, "silent_drops": 0},
        {"page_type": "synthetic_scan", "char_edits": 10, "chars": 100, "word_edits": 4, "words": 20,
         "numbers": 5, "numbers_correct": 4, "silent_errors": 1, "silent_drops": 0},
        {"page_type": "synthetic_scan", "char_edits": 0, "chars": 100, "word_edits": 0, "words": 20,
         "numbers": 5, "numbers_correct": 5, "silent_errors": 0, "silent_drops": 0},
    ]
    table = aggregate(rows)
    assert table["digital"]["cer"] == 0.0 and table["digital"]["pages"] == 1
    assert table["synthetic_scan"]["cer"] == pytest.approx(0.05)  # micro average: 10 / 200
    assert table["synthetic_scan"]["number_accuracy"] == pytest.approx(0.9)
    assert table["synthetic_scan"]["silent_errors"] == 1
