"""Source-type label rule: transparent domain/metadata heuristic, display only."""
import pytest

from matn_research.source_type import classify, page_metadata, text


@pytest.mark.parametrize('url,label', [
    ('https://www.mcit.gov.eg/en/page', 'government'),
    ('https://digital.gov/guides', 'government'),
    ('https://www.gov.uk/service-manual', 'government'),
    ('https://www.data.gouv.fr/x', 'government'),
    ('https://www.who.int/news', 'international organization'),
    ('https://documents.worldbank.org/report', 'international organization'),
    ('https://www.oecd.org/gov/digital', 'international organization'),
    ('https://www.mdpi.com/2076-3417/1/1', 'academic'),
    ('https://cs.stanford.edu/paper', 'academic'),
    ('https://www.ox.ac.uk/research', 'academic'),
    ('https://en.wikipedia.org/wiki/Dashboard', 'encyclopedia'),
    ('https://www.reuters.com/world', 'news'),
    ('https://egyptnews.example.org/a', 'news'),
    ('https://www.vendor.io/blog/post', 'commercial-vendor'),
    ('https://www.some-firm.com/insights', 'commercial-vendor'),
    ('https://www.association.org/brief', 'other'),
])
def test_domain_rule(url, label):
    assert classify(url)['label'] == label


def test_metadata_rules_and_publisher_text():
    raw = ('<meta name="citation_title" content="A study"><meta property="og:site_name" content="Journal Hub">'
           '<script type="application/ld+json">{"@type":"ScholarlyArticle"}</script>')
    info = classify('https://blog.example.com/a', page_metadata(raw))
    assert info['label'] == 'academic' and text(info) == 'academic · Journal Hub (blog.example.com)'
    news = classify('https://example.org/a', page_metadata('<script type="application/ld+json">{"@graph":[{"@type":"NewsArticle"}]}</script>'))
    assert news['label'] == 'news'
    assert text(classify('https://www.vendor.io/x')) == 'commercial-vendor · vendor.io'
