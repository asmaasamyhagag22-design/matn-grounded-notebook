"""Snapshot-backed source prior regression tests; no model or network calls."""
import json
from pathlib import Path

import pytest

from matn_research.fast import source_labels
from matn_research.shortlist import shortlist
from matn_research.source_type import classify, page_metadata


FIXTURE = Path(__file__).parent / 'fixtures' / 'vendor-publisher.json'


def saved_publisher():
    return json.loads(FIXTURE.read_bytes())


def html_metadata(value):
    return page_metadata('<script type="application/ld+json">' + json.dumps(value) + '</script>')


def test_actual_p_publisher_sales_contact_is_vendor_on_noncommercial_tld():
    fixture = saved_publisher()
    info = classify(fixture['url'], html_metadata(fixture['organization']))
    assert info['label'] == 'commercial-vendor'
    assert info['evidence'] == 'same-publisher sales contact metadata'
    assert len(fixture['raw_sha256']) == 64


@pytest.mark.parametrize('url', ['https://publisher.me/post', 'https://publisher.org/post', 'https://publisher.co.za/post'])
def test_publisher_sales_signal_generalizes_beyond_a_tld_or_topic(url):
    organization = dict(**{'@type': 'Organization'}, url=url, contactPoint=dict(contactType='Sales'))
    assert classify(url, html_metadata(organization))['label'] == 'commercial-vendor'


def test_graph_and_subdomain_use_the_same_publisher_sales_cue():
    organization = {'@type': ['Organization'], 'url': 'https://publisher.me',
                    'contactPoint': [{'contactType': 'support'}, {'contactType': 'sales'}]}
    assert classify('https://blog.publisher.me/post', html_metadata({'@graph': [organization]}))['label'] == 'commercial-vendor'


def test_offsite_sales_contact_does_not_classify_the_host_publisher():
    organization = {'@type': 'Organization', 'url': 'https://seller.me', 'contactPoint': {'contactType': 'sales'}}
    assert classify('https://association.org/brief', html_metadata(organization))['label'] == 'other'
    assert classify('https://seller.me.association.org/brief', html_metadata(organization))['label'] == 'other'


def test_generic_organization_business_or_support_does_not_imply_vendor():
    # The saved UNCDF page declares LocalBusiness through its site template.
    business = {'@type': 'LocalBusiness', 'url': 'https://association.org'}
    support = {'@type': 'Organization', 'url': 'https://association.org', 'contactPoint': {'contactType': 'support'}}
    assert classify('https://association.org', html_metadata(business))['label'] == 'other'
    assert classify('https://association.org', html_metadata(support))['label'] == 'other'
    assert classify('https://ordinary.me/blog')['label'] == 'other'


def test_institutional_and_known_news_labels_keep_precedence():
    for url, expected in [('https://agency.gov/brief', 'government'), ('https://university.edu/brief', 'academic'),
                          ('https://www.reuters.com/brief', 'news')]:
        organization = {'@type': 'Organization', 'url': url, 'contactPoint': {'contactType': 'sales'}}
        assert classify(url, html_metadata(organization))['label'] == expected


def test_vendor_article_schema_does_not_turn_sales_publisher_into_news():
    organization = {'@type': 'Organization', 'url': 'https://publisher.me', 'contactPoint': {'contactType': 'sales'}}
    metadata = html_metadata({'@graph': [organization, {'@type': 'NewsArticle'}]})
    assert classify('https://publisher.me/brief', metadata)['label'] == 'commercial-vendor'


def test_fast_source_labels_read_metadata_from_the_final_saved_source(tmp_path):
    fixture = saved_publisher()
    html = '<script type="application/ld+json">' + json.dumps(fixture['organization']) + '</script>'
    (tmp_path / 'original.bin').write_bytes(html.encode())
    record = dict(status='complete', independent=True, doc_id='read-d1', url='https://redirect.gov/brief',
                  final_url=fixture['url'], folder=str(tmp_path), coverage=dict(kind='html'))
    assert source_labels([record]) == {'read-d1': 'commercial-vendor'}
    assert source_labels([dict(record, independent=False), dict(record, status='failed', doc_id='failed')]) == {}


def test_missing_snapshot_uses_the_transparent_url_fallback(tmp_path):
    record = dict(status='complete', independent=True, doc_id='read-d1', url='https://ordinary.me/brief',
                  folder=str(tmp_path), coverage=dict(kind='html'))
    assert source_labels([record]) == {'read-d1': 'other'}


def test_snapshot_labels_feed_existing_government_and_academic_prior(tmp_path):
    fixture = saved_publisher()
    (tmp_path / 'original.bin').write_text('<script type="application/ld+json">' + json.dumps(fixture['organization']) + '</script>')
    reads = [dict(status='complete', independent=True, doc_id='vendor', url=fixture['url'], folder=str(tmp_path), coverage=dict(kind='html')),
             dict(status='complete', independent=True, doc_id='public', url='https://agency.gov', folder=str(tmp_path / 'missing')),
             dict(status='complete', independent=True, doc_id='academic', url='https://university.edu', folder=str(tmp_path / 'missing'))]
    labels = source_labels(reads)
    wire = dict(segments=[dict(id='v-seg', source='vendor', text='The vendor sentence.'),
                          dict(id='g-seg', source='public', text='The government sentence.'),
                          dict(id='a-seg', source='academic', text='The academic sentence.')],
                sources=[dict(handle='v', support_segment='v-seg'), dict(handle='g', support_segment='g-seg'),
                         dict(handle='a', support_segment='a-seg')])
    types = dict(v=labels['vendor'], g=labels['public'], a=labels['academic'])
    ranking = dict(axis=[('v', .0163), ('g', .0162), ('a', .0161)])
    assert shortlist({}, wire, ranking, k=3, source_type=types, dedup=False) == {'axis': ['g', 'a', 'v']}


@pytest.mark.parametrize('raw,label', [
    ('<script type="application/ld+json">{"@type":"GovernmentOrganization"}</script>', 'government'),
    ('<meta name="citation_title" content="A scholarly article">', 'academic'),
])
def test_metadata_institutional_labels_reach_the_same_source_prior(tmp_path, raw, label):
    (tmp_path / 'original.bin').write_text(raw)
    record = dict(status='complete', independent=True, doc_id='institution', url='https://institution.example.org/brief',
                  folder=str(tmp_path), coverage=dict(kind='html'))
    assert source_labels([record]) == {'institution': label}
