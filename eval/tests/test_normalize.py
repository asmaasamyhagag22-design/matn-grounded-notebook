"""Normalization used to verify that a gold quote exists on its page and that a value appears in its quote."""
import pytest

from normalize import normalize_text, quote_on_page, value_in_quote

# ---------- cases that MUST match ----------
MUST_PASS = [
    ("NFKC ligature", "eﬃcient ﬁne-tuning", "efficient fine-tuning"),
    ("collapsed whitespace", "the   model\n\twas  trained", "the model was trained"),
    ("hyphenated line break rejoined", "the trans-\nformer layer", "the transformer layer"),
    ("hyphen kept for real compounds", "a state-of-the-\nart model", "a state-of-the-art model"),
    ("soft hyphen removed", "pre­training data", "pretraining data"),
    ("curly double quotes", "called “AI Scientist” here", 'called "AI Scientist" here'),
    ("curly single quote", "the model’s output", "the model's output"),
    ("en/em dash and minus", "pages 3–5 — a drop of −3.5", "pages 3-5 - a drop of -3.5"),
    ("non-breaking space", "10 kg of data", "10 kg of data"),
]


@pytest.mark.parametrize("name,page,quote", MUST_PASS, ids=[c[0] for c in MUST_PASS])
def test_quote_found_after_normalization(name, page, quote):
    assert quote_on_page(quote, page), name


# ---------- cases that MUST NOT match ----------
MUST_FAIL = [
    ("different word", "the model was trained on GPUs", "the model was tested on GPUs"),
    ("different number", "accuracy rose to 45% overall", "accuracy rose to 54% overall"),
    ("partial word at start", "the transformer with 12 layers", "former with 12 layers"),
    ("partial word at end", "the transformer with 12 layers", "the transformer with 1"),
    ("missing word", "we report the average reward", "we report the reward"),
]


@pytest.mark.parametrize("name,page,quote", MUST_FAIL, ids=[c[0] for c in MUST_FAIL])
def test_quote_rejected(name, page, quote):
    assert not quote_on_page(quote, page), name


def test_cross_page_quote_is_rejected():
    page_3_end = "the final section discusses the"
    page_4_start = "limitations of the pilot study."
    quote = "discusses the limitations of the pilot"
    assert not quote_on_page(quote, page_3_end)
    assert not quote_on_page(quote, page_4_start)


# ---------- value_as_written inside the quote ----------
@pytest.mark.parametrize("value,quote", [
    ("1,024", "We used 1,024 GPUs."),
    ("45%", "accuracy reached 45% on the test set"),
    ("-3.5", "a change of -3.5 points"),
    ("2023", "published in 2023."),
    ("− 3.5", "a change of − 3.5 points"),
    ("10⁶", "trained on 10⁶ tokens"),
])
def test_value_in_quote_passes(value, quote):
    assert value_in_quote(value, quote)


@pytest.mark.parametrize("name,value,quote", [
    ("value absent", "4096", "We used 1,024 GPUs."),
    ("value is part of a larger number", "45", "accuracy reached 145 points"),
    ("value would only match after NFKC (10^6 vs 106)", "106", "trained on 10⁶ tokens"),
    ("comma-less form of a grouped number", "1024", "We used 1,024 GPUs."),
])
def test_value_in_quote_fails(name, value, quote):
    assert not value_in_quote(value, quote), name


def test_normalize_text_is_idempotent():
    once = normalize_text("the trans-\nformer “model” — eﬃcient")
    assert normalize_text(once) == once
