"""Approved Part 1 tokenizer fixtures; no retrieval or model calls."""
import pytest
from matn_rag.tokenizer import tokenize, VERSION

CASES = [
 ('11.2', [('11.2', ())]),
 ('1,240', [('1,240', ('1240',))]),
 ('FY2020/21', [('fy2020/21', ())]),
 ('US$18.4', [('us$18.4', ('18.4',))]),
 ('24%', [('24%', ('24',))]),
 ('-0.5965', [('-0.5965', ('0.5965',))]),
 ('COVID-19', [('covid-19', ('covid','19'))]),
 ('2025–2030', [('2025–2030', ('2025','2030'))]),
 ('2025-2030', [('2025-2030', ('2025','2030'))]),
 ('state-of-the-art', [('state-of-the-art', ('state','of','the','art'))]),
 ('A/B', [('a/b', ())]),
 ('$1,240.50', [('$1,240.50', ('1240.50','1,240.50'))]),
 ('+24%', [('+24%', ('24',))]),
 ('€18.4', [('€18.4', ('18.4',))]),
 ('£5', [('£5', ('5',))]),
 ('−0.5', [('−0.5', ('0.5',))]),
 ('1,24', [('1',()),('24',())]),
 ('.5', [('.5',('0.5',))]),
 ('11.', [('11',())]),
 ("don't", [('don',()),('t',())]),
 ('１２４０', [('1240',())]),
 ('of THE and', [('of',()),('the',()),('and',())]),
 ('AI-2 AI/ML', [('ai-2',('ai','2')),('ai/ml',())]),
 ('25%–30%', [('25%–30%',('25','30'))]),
 ('18.4–20.0', [('18.4–20.0',('18.4','20.0'))]),
 ('7/12', [('7/12',())]),
 ('foo_bar', [('foo',()),('bar',())]),
 ('', []),
]

@pytest.mark.parametrize('text,expected', CASES)
def test_base_and_alias_table(text,expected):
 tokens=tokenize(text)
 assert [(t.base,t.aliases) for t in tokens]==expected
 assert [t.position for t in tokens]==list(range(len(tokens)))
 assert [t.terms for t in tokens]==[tuple(dict.fromkeys((b,*a))) for b,a in expected]


def test_aliases_do_not_add_positions_or_length():
 tokens=tokenize('COVID-19 US$18.4 1,240')
 assert len(tokens)==3
 expected_by_text = dict(CASES)
 selected = [expected_by_text[text] for text in ('COVID-19','US$18.4','1,240')]
 expected_postings = sum(len(set((base, *aliases))) for case in selected for base, aliases in case)
 assert len([term for t in tokens for term in t.terms]) == expected_postings
 assert len(tokens) == sum(len(case) for case in selected)
 assert tokenize('COVID-19 US$18.4 1,240')==tokens
 assert VERSION=='rag-tokenizer-v1'
