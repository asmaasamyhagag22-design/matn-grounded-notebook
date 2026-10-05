"""Step 4c measurement helpers: per-token correctness, the ground-truth frame, the report aggregate."""
from __future__ import annotations

from types import SimpleNamespace

from eval.reading.degrade import rotate_bbox
from eval.reading.metrics import Word
from eval.reading.scan import BAR_GRID, ground_truth, token_correct
from eval.reading.scan_report import aggregate
from matn_contracts.enums import Visibility
from matn_reading.layout import Line, LayoutBlock, Word as LayoutWord


def test_a_token_is_correct_only_against_the_word_it_sits_on():
    gt = [Word("1,240", (100, 100, 130, 110)), Word("2020", (200, 100, 225, 110))]
    assert token_correct({"token": "1,240", "bbox": (101, 100, 129, 110)}, gt)
    assert not token_correct({"token": "1,248", "bbox": (101, 100, 129, 110)}, gt)
    assert not token_correct({"token": "2020", "bbox": (101, 100, 129, 110)}, gt)   # right value, wrong place
    assert not token_correct({"token": "7", "bbox": (400, 400, 405, 410)}, gt)       # inserted


def _page(*, hidden: bool = False):
    words = [LayoutWord("Total", 100, 100, 130, 110), LayoutWord("1,240", 135, 100, 160, 110)]
    block = LayoutBlock([Line(words)]).finish()
    contract = SimpleNamespace(visibility=Visibility.HIDDEN if hidden else Visibility.VISIBLE)
    return SimpleNamespace(cropbox=(0.0, 0.0, 612.0, 792.0), blocks=[SimpleNamespace(layout=block, contract=contract)],
                           footnote_markers=[{"text": "3", "bbox": (161, 98, 164, 104)}])


def test_ground_truth_keeps_visible_words_and_markers_and_follows_the_rotation():
    words, lines = ground_truth(_page(), 0.0, (2550, 3300))
    assert [w.text for w in words] == ["Total", "1,240", "3"]
    assert words[1].bbox == (135, 100, 160, 110) and lines[0][1] == "Total 1,240"
    moved, _ = ground_truth(_page(), 1.2, (2550, 3300))
    s = 300 / 72
    expected = rotate_bbox((135 * s, 100 * s, 160 * s, 110 * s), 1.2, (2550, 3300))
    assert all(abs(a - b / s) < 1e-6 for a, b in zip(moved[1].bbox, expected))
    assert ground_truth(_page(hidden=True), 0.0, (2550, 3300))[0] == [Word("3", (161, 98, 164, 104))]


def test_bar_grid_is_the_frozen_grid():
    assert BAR_GRID[0] == 0.5 and BAR_GRID[49] == 0.99 and BAR_GRID[-3:] == [0.995, 0.999, 1.0]


def test_aggregate_rates():
    page = {"numbers": {"total": 10, "correct": 9, "unflagged_correct": 8, "unflagged_total": 8, "silent_errors": 0,
                        "silent_drops": 1},
            "cer": {"char_edits": 5, "chars": 100, "word_edits": 2, "words": 20}, "flagged_tokens": 2,
            "reader1_tokens": 10, "false_alarms": 1, "agreed_tokens": 3, "second_read_tokens": 4,
            "timing": {"without_second_reads": 9.0, "with_second_reads": 20.0}}
    agg = aggregate([page])
    assert (agg["cer"], agg["accuracy"], agg["flag_rate"], agg["false_alarm_rate"], agg["agreement_rate"]) == (
        "0.0500", "0.9000", "0.2000", "0.5000", "0.7500")
    assert (agg["s_without"], agg["s_with"], agg["silent_drops"]) == ("9.0", "20.0", 1)


def test_closeout_calibration_refuses_holdout_and_seen_check():
    import pytest
    from eval.reading.closeout import run
    for subset in ("holdout2", "dev_check", "real"):
        with pytest.raises(ValueError,match="dev-tune ONLY"):
            run(subset,mode="adaptive_candidate")
