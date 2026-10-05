"""Consensus between reader 1 (RapidOCR) and reader 2 (GLM-OCR): exact agreement after normalization, else flagged."""
from __future__ import annotations

from eval.reading.metrics import _READER_NUMBER, normalize_for_numbers as metric_normalize
from matn_reading.ocr.consensus import compare_line
from matn_reading.ocr.numbers import NUMBER_PATTERN, normalize, number_tokens


def test_number_tokens_are_exactly_the_frozen_metric_tokens():
    assert NUMBER_PATTERN.pattern == _READER_NUMBER.pattern
    for text in ("vs48.0% and −3.2", "1,240 units in 2020.", "Table 3.8 ­– 12"):
        assert normalize(text) == metric_normalize(text)


def _words(*items):
    return [{"text": text, "score": score} for text, score in items]


def test_identical_numbers_are_accepted():
    result = compare_line(_words(("Revenue", 0.99), ("1,240", 0.97), ("in", 0.99), ("2020", 0.99)),
                          "Revenue 1,240 in 2020")
    assert [(t.token, t.status) for t in result.tokens] == [("1,240", "agreed"), ("2020", "agreed")]
    assert result.extra_in_reader2 == []


def test_any_difference_flags_the_number_with_both_readings():
    result = compare_line(_words(("Revenue", 0.99), ("1,248", 0.91)), "Revenue 1,240")
    token = result.tokens[0]
    assert (token.token, token.status, token.reader2) == ("1,248", "uncertain_number", "1,240")


def test_formatting_differences_count_as_disagreement():
    # "1,240" vs "1240" and "3.2" vs "3.20" are different tokens (docs/reading_eval_rules.md section 2).
    assert compare_line(_words(("1,240", 0.99)), "1240").tokens[0].status == "uncertain_number"
    assert compare_line(_words(("3.2", 0.99)), "3.20").tokens[0].status == "uncertain_number"


def test_minus_and_dash_variants_agree_after_normalization():
    assert compare_line(_words(("-3.2", 0.99)), "−3.2").tokens[0].status == "agreed"


def test_a_number_only_reader_2_sees_is_reported_as_a_possible_drop():
    result = compare_line(_words(("Units", 0.99), ("sold", 0.99)), "Units 45 sold")
    assert result.tokens == [] and result.extra_in_reader2 == ["45"]


def test_order_is_respected_so_a_swap_is_not_agreement():
    result = compare_line(_words(("12", 0.99), ("34", 0.99)), "34 12")
    assert [t.status for t in result.tokens].count("agreed") == 1


def test_a_failed_second_read_flags_every_number_on_the_line():
    result = compare_line(_words(("12", 0.99), ("34", 0.99)), None)
    assert [t.status for t in result.tokens] == ["uncertain_number", "uncertain_number"]
    assert all(t.reader2 is None for t in result.tokens)


def test_tokens_keep_their_word_index_and_confidence():
    result = compare_line(_words(("Total", 0.99), ("vs48.0%", 0.62)), "Total vs48.0%")
    token = result.tokens[0]
    assert (token.word_index, token.score, token.token) == (1, 0.62, "48.0")
    assert number_tokens("vs48.0%") == ["48.0"]
