"""Meaning regressions from the first overnight model-phrasing run."""
from __future__ import annotations

from matn_contracts.enums import SlideType
from matn_deck.demo_phrasing import _prompt
from matn_deck.demo_planner import meaning_problems
from matn_deck.specimen import sample_fact


UNEMPLOYMENT = sample_fact(
    "Unemployment rate, Q1-FY2021/22: 7.5%",
    "Unemployment declined to 7.5 percent by Q1-FY2021/22, compared to 9.6 percent at the COVID-shock.",
    6,
    number=("Unemployment rate, Q1-FY2021/22", "7.5", "%"),
)
BENEFIT = sample_fact(
    "The digital-economy framework would benefit from streamlining and modernization.",
    "The digital-economy framework would benefit from streamlining and modernization.",
    8,
)
ACCURACY = sample_fact(
    "The best post-training recipe reaches 69.4% accuracy.",
    "The best post-training recipe reaches 69.4 percent accuracy.",
    9,
    number=("Post-training accuracy", "69.4", "%"),
)
TRAINING = sample_fact(
    "The best pre-training recipe reaches its target in 19.7 minutes.",
    "The best pre-training recipe reaches its target in 19.7 minutes.",
    10,
    number=("Pre-training time", "19.7", "minutes"),
)


def test_deletion_only_accepts_quote_words_and_rejects_new_content_words():
    assert meaning_problems("Unemployment declined to 7.5 percent", (UNEMPLOYMENT,)) == []
    problems = meaning_problems("Unemployment unexpectedly worsened to 7.5 percent", (UNEMPLOYMENT,))
    assert "CONTENT_NOT_IN_QUOTES:unexpectedly,worsened" in problems


def test_direction_reversal_rose_versus_fell_is_rejected():
    problems = meaning_problems("Unemployment rose to 7.5 percent", (UNEMPLOYMENT,))
    assert "DIRECTION_MISMATCH:decrease->increase" in problems


def test_modality_shift_would_benefit_to_benefits_is_rejected():
    problems = meaning_problems("The digital-economy framework benefits from streamlining", (BENEFIT,))
    assert "MODALITY_DROPPED:would" in problems


def test_negation_and_modality_must_agree_both_ways():
    negated = sample_fact("The system may not improve outcomes.", "The system may not improve outcomes.", 11)
    assert "NEGATION_DROPPED" in meaning_problems("The system may improve outcomes", (negated,))
    assert "MODALITY_DROPPED:may" in meaning_problems("The system improves outcomes", (negated,))
    plain = sample_fact("The system improves outcomes.", "The system improves outcomes.", 12)
    assert "NEGATION_ADDED" in meaning_problems("The system does not improve outcomes", (plain,))
    assert "MODALITY_ADDED:likely" in meaning_problems("The system likely improves outcomes", (plain,))


def test_kpi_model_phrase_must_cite_exactly_one_fact_and_cannot_conflate_metrics():
    title = "Post-training accuracy reaches 69.4 percent with 19.7 minutes pre-training time"
    problems = meaning_problems(title, (ACCURACY, TRAINING), slide_type=SlideType.KPI)
    assert "KPI_FACT_COUNT:2" in problems


def test_small_explicit_connector_list_can_join_quote_fragments():
    title = "Post-training accuracy reaches 69.4 percent while pre-training reaches 19.7 minutes"
    problems = meaning_problems(title, (ACCURACY, TRAINING))
    assert not any(problem.startswith("CONTENT_NOT_IN_QUOTES:while") for problem in problems)


def test_model_prompt_exposes_the_evidence_words_that_the_guard_allows():
    class Doc:
        @staticmethod
        def fact(_fact_id):
            return UNEMPLOYMENT

    _, user = _prompt(Doc(), {"kind": "item", "fact_ids": [UNEMPLOYMENT.fact_id]})
    assert UNEMPLOYMENT.evidence[0].quote in user
    assert UNEMPLOYMENT.statement not in user
