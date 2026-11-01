"""Bounded question-directed catalog selection, never a support verdict.

Rank complete source blocks, keeping their original handle/quote addresses.
Symbol tokens and command options survive normalization. Ranking is heuristic;
source fidelity, relevance and completeness remain separate measurements.
"""
import math
import re
from collections import Counter
from matn_verification.scope import STOP

IGNORE = STOP | set('what how which does do about explain under conditions happens mean always using use used file files'.split())
TOKEN = re.compile(r'--[\w-]+|[!/]\B|[a-z0-9]+(?:-[a-z0-9]+)*|!', re.I)


def terms(text):
    tokens = set(TOKEN.findall(text.casefold()))
    for token in tuple(tokens):
        if '-' in token and not token.startswith('--'):
            tokens.update(token.split('-'))
    return tokens - IGNORE


def score(question, text, corpus=()):
    wanted = terms(question)
    have = terms(text)
    symbols = {t for t in wanted if t == '!' or t.startswith('--')}
    # Symbols are strong query anchors, not semantic truth criteria.
    documents = [terms(x) for x in corpus]
    def weight(t):
        return math.log(1 + len(documents)/sum(t in x for x in documents)) if documents else 1
    def pairs(value):
        words = re.findall(r'[a-z0-9]+', value.casefold())
        return set(zip(words, words[1:]))
    phrases = {p for p in pairs(question) & pairs(text) if any(t not in IGNORE for t in p)}
    return sum(weight(t) for t in wanted & have) + 4 * len(symbols & have) + 3 * len(phrases)


def score_many(question, texts, corpus=()):
    """The same score for a batch, computing corpus frequencies only once.

    No ranking-policy change: repeated corpus entries retain their weight,
    and the token/phrase/symbol rules match score's reference implementation.
    """
    wanted = terms(question)
    documents = [terms(text) for text in corpus]
    frequencies = Counter(t for document in documents for t in document)
    symbols = {t for t in wanted if t == '!' or t.startswith('--')}
    def pairs(value):
        words = re.findall(r'[a-z0-9]+', value.casefold())
        return set(zip(words, words[1:]))
    question_pairs = pairs(question)
    result = []
    for text in texts:
        have = terms(text)
        matched = wanted & have
        weighted = sum(math.log(1 + len(documents)/frequencies[t]) if documents else 1 for t in matched)
        phrases = {p for p in question_pairs & pairs(text) if any(t not in IGNORE for t in p)}
        result.append(weighted + 4 * len(symbols & have) + 3 * len(phrases))
    return result


def select_handles(question, handles, max_characters=4000):
    groups = {}
    for key, h in handles.items():
        group = tuple(sorted({c['block_id'] for c in h['citations']}))
        groups.setdefault(group, []).append((key, h))
    df = Counter(t for rows in groups.values() for t in terms(' '.join(h['text'] for _, h in rows)))
    wanted = terms(question)
    def rank(rows):
        text = ' '.join(h['text'] for _, h in rows)
        matched = wanted & terms(text)
        value = sum(math.log(1 + len(groups)/df[t]) for t in matched)
        value += 4 * sum(t == '!' or t.startswith('--') for t in matched)
        return value
    ranked = sorted(groups.values(), key=lambda rows: -rank(rows))
    chosen = {}; used = 0
    for rows in ranked:
        if rank(rows) <= 0: continue
        size = sum(len(h['text']) for _, h in rows)
        if used + size > max_characters: continue
        chosen.update(rows); used += size
    # Stable original IDs: no renumbering and no deleted prefix within a block.
    return {key: h for key, h in handles.items() if key in chosen}
