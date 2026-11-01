"""v2 admission screen: general promotion/consent/template patterns, positives and negatives."""
import pytest

from matn_research.view_rank import promotion, cross_page_boilerplate, brand_tokens


@pytest.mark.parametrize('text', [
    'Translate behavioral data into board-ready risk language with reporting from Adaptive Security.',
])
def test_sentence_naming_its_own_vendor_is_screened_on_commercial_sources(text):
    assert promotion(text, 'www.adaptivesecurity.com', commercial=True) == 'names_own_vendor'
    assert promotion(text, 'www.adaptivesecurity.com', commercial=False) is None  # only commercial publishers


@pytest.mark.parametrize('text', [
    'Our platform helps agencies cut queues in half.',
    'We offer tailored training for public employees.',
    'Request a free demo to see the dashboard in action.',
    'Start your free trial today and transform your service desk.',
    'Contact our experts to plan your migration.',
    'Subscribe to our newsletter for monthly insights.',
    'We use cookies to improve your experience on this website.',
    'By continuing to use this site you agree to our terms.',
])
def test_promotion_and_consent_lines_are_screened(text):
    assert promotion(text) in ('self_promotion', 'consent_or_newsletter')


@pytest.mark.parametrize('text', [
    'Agencies that published contract data saw more bidders per tender.',
    'Staff can be reallocated to busy counters during peak hours.',
    'The ministry offers training to procurement officers each year.',
    'Citizens may request a copy of their records online.',
    'The report recommends that agencies contact suppliers before awarding contracts.',
    'Open data portals help journalists track public spending.',
])
def test_ordinary_evidence_is_not_screened(text):
    assert promotion(text, 'www.example.gov', commercial=False) is None
    assert promotion(text, 'www.queueco.com', commercial=True) is None


def test_brand_tokens_ignore_generic_labels():
    assert brand_tokens('www.adaptivesecurity.com') == {'adaptivesecurity'}
    assert brand_tokens('data.gov.uk') == set() or 'data' not in brand_tokens('data.gov.uk')


def test_template_sentence_repeated_across_pages_is_screened_but_single_use_is_not():
    rows = [('s1', 'd1', 'a.org', 'Find out more about our programmes and services across the region.'),
            ('s2', 'd2', 'a.org', 'Find out more about our programmes and services across the region.'),
            ('s3', 'd3', 'b.org', 'Waiting times fell after appointments were introduced.'),
            ('s4', 'd4', 'c.org', 'Waiting times fell after appointments were introduced.')]
    out = cross_page_boilerplate(rows)
    assert out == {'s1': 'repeated_across_pages', 's2': 'repeated_across_pages'}


@pytest.mark.parametrize('text, reason', [
    ('Can a supplier challenge a procurement decision made by an AI system?', 'question_not_claim'),
    ('What Is A Paperless Government?', 'question_not_claim'),
    ('Step 2: Evaluate Generative AI Tools ........................................................', 'table_of_contents'),
    ('Establish public trust in GenAI experiments Provide AI literacy training and upskilling opportunities to civil servants '
     'Prevent fragmentation of projects and AI systems Prioritise investments in shared tools, data and secure testing '
     'mechanisms Limit and mitigate risks Invest in experimental AI research', 'flattened_list'),
])
def test_questions_tables_of_contents_and_flattened_lists_are_screened(text, reason):
    assert promotion(text) == reason


@pytest.mark.parametrize('text', [
    'Transparency requirements level the playing field and provide suppliers with the information needed to compete.',
    'Many datasets that are the most complete and up-to-date are frequently found on other government ministry or agency '
    'websites and not on the official open data portals.',
    'The draft revision aims to improve the government procurement system and provide legal support for a unified market.',
])
def test_long_ordinary_sentences_are_not_flattened_lists(text):
    assert promotion(text) is None
