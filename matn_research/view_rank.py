"""Generic retrieval hints, never a semantic coverage or eligibility test."""
from collections import Counter
import math
import re

from matn_chat.evidence_selection import terms


def retrieval_terms(text):
    # Small English inflection fold, not a topic vocabulary or synonym claim.
    def fold(t):
        if len(t) > 5 and t.endswith('ies'): return t[:-3] + 'y'
        if len(t) > 5 and t.endswith('ing'): return t[:-3]
        if len(t) > 4 and t.endswith('s') and not t.endswith(('ss','us')): return t[:-1]
        return t
    function_words = set('as at by from with into through during than then their its these those both such all also whether while has have had will would could there here'.split())
    return {fold(t) for t in terms(text) - function_words}


def prose_quality(text):
    """Downrank menu fragments and link lists without excluding their pool IDs."""
    words = re.findall(r'\w+', text)
    fragment = len(words) <= 12 and not re.search(r'[.!?][\s]*$',text)
    link_list = text.count('|') >= 2 or len(re.findall(r'https?://',text)) >= 2
    return 0.1 if fragment or link_list else 1.0


# Generic page-furniture rules (jusText/Trafilatura style: short, link-like,
# call-to-action or truncated blocks). No topic words, sources or IDs.
PHONE = re.compile(r'(?:\+\d{1,3}[\s.-]?)?\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b')
CTA = re.compile(r'^\W*(?:learn more|learn (?:essential|how|about)|click|subscribe|sign (?:up|in)|log ?in|register|download|shop|buy|donate|join (?:us|our|now|the)|follow us|share (?:this|on)|contact us|call (?:us|now|today)|email us|read more|see (?:more|all)|view (?:all|more)|watch|get started|try (?:it|for)|request a|book (?:a|now)|skip to|back to|go to|applying the filters?|not sure where)\b', re.I)
FURNITURE = re.compile(r'\b(?:cookies?|newsletter|all rights reserved|privacy policy|terms of (?:use|service)|sponsored|advertisement)\b', re.I)
FILE_LINK = re.compile(r'\((?:PDF|DOCX?|XLSX?|PPTX?|ZIP)\s*[\d.,]+\s*[kKmMgG]i?[bB]\)')


def boilerplate(text):
    """Reason a support sentence is page furniture, else None. Pool is unchanged."""
    s = text.strip(); words = re.findall(r"[A-Za-z0-9][\w'’-]*", s)
    if PHONE.search(s): return 'phone_number'
    if CTA.search(s) or FURNITURE.search(s): return 'call_to_action_or_navigation'
    if FILE_LINK.search(s) or prose_quality(s) < 1: return 'link_list_or_fragment'
    if re.match(r'^\W*(?:[►▶»→•]|#\d+\b)', s): return 'heading_or_list_marker'
    if s[:1].islower() or len(words) < 4: return 'truncated_fragment'
    if not re.search(r'[.!?]["”’)\]]*$', s):
        capital = sum(w[:1].isupper() for w in words) / max(1, len(words))
        if len(words) <= 25 or capital >= .5: return 'heading_or_title'
    if s.endswith('!') and len(words) <= 12: return 'promotion'
    return None


def point_scores(query, texts, contexts, costs):
    wanted = retrieval_terms(query)
    docs = [retrieval_terms(t) for t in texts]
    df = Counter(t for d in docs for t in d)
    weights = {t: math.log(1 + len(docs)/(1+df[t])) for t in wanted}
    total = sum(weights.values()) or 1
    result = []
    for text, have, context, cost in zip(texts,docs,contexts,costs,strict=True):
        adjacent = retrieval_terms(context) - have
        matched = sum(weights[t] for t in wanted & have)
        matched += 0.25 * sum(weights[t] for t in wanted & adjacent)
        # Complete context cost matters, but is never shortened to improve rank.
        result.append(prose_quality(text) * matched / total / math.sqrt(max(200,cost)/200))
    return result


# Admission screen v2 (general patterns, HTML and PDF alike). Self-promotion: first-person
# offers, demo/trial/quote requests and a sentence that names its own commercial publisher.
PROMOTION = re.compile(r"\b(?:our (?:platform|solution|solutions|product|products|software|tool|tools|service|services|team|experts|"
                       r"customers|clients|app|offering|consultants)|we (?:offer|provide|help|deliver|can help|specialize)|"
                       r"(?:request|schedule|book|get) a (?:free )?(?:demo|quote|consultation|trial)|free trial|"
                       r"contact (?:us|our)|talk to (?:us|our|an expert)|get in touch|sign up (?:for|today|now)|"
                       r"subscribe to (?:our|the)|start (?:your|a) free)\b", re.I)
CONSENT = re.compile(r"\b(?:cookies?|consent|accept all|manage (?:your )?preferences|opt[ -]out|unsubscribe|newsletter|"
                     r"by (?:clicking|continuing|using this (?:site|website)))\b", re.I)


def brand_tokens(host):
    """Publisher name forms from a host: 'www.adaptivesecurity.com' -> {'adaptivesecurity'}."""
    host = (host or '').lower().split(':')[0]
    parts = [p for p in host.split('.') if p not in ('www', 'com', 'org', 'net', 'io', 'ai', 'co', 'gov', 'edu', 'int', 'uk', 'us')]
    return {p for p in parts[-1:] if len(p) >= 5}


def promotion(text, host=None, commercial=False):
    """Reason a sentence is promotion, consent furniture or a question, else None. Never used on the claim text itself."""
    if re.search(r'\?["”’)\]]*\s*$', text.strip()):
        return 'question_not_claim'  # FAQ headings and rhetorical questions state nothing
    if re.search(r'(?:\.\s?){4,}|…{2,}|_{4,}', text):
        return 'table_of_contents'  # dotted leaders
    words = re.findall(r"[A-Za-z][\w'’-]*", text)
    restarts = re.findall(r"\b[a-z][\w'’-]* [A-Z][a-z]+ [a-z]", text)  # '…servants Prevent fragmentation…'
    if len(words) > 25 and not re.search(r'[.;:!?]', text.strip()[:-1]) and len(restarts) >= 3:
        return 'flattened_list'  # headings or table cells run together: clauses restart mid-text without punctuation
    if PROMOTION.search(text):
        return 'self_promotion'
    if CONSENT.search(text):
        return 'consent_or_newsletter'
    if commercial:
        squashed = re.sub(r'[^a-z0-9]', '', text.lower())
        if any(b in squashed for b in brand_tokens(host)):
            return 'names_own_vendor'
    return None


def cross_page_boilerplate(rows, *, same_host=2, any_host=3):
    """Normalized sentences repeated across documents (site templates). rows: (key, doc, host, text)."""
    seen = {}
    for key, doc, host, text in rows:
        norm = ' '.join(re.findall(r'[a-z0-9]+', text.lower()))
        if len(norm) < 20:
            continue
        seen.setdefault(norm, []).append((key, doc, host))
    out = {}
    for hits in seen.values():
        docs = {d for _, d, _ in hits}
        hosts = {}
        for _, d, h in hits:
            hosts.setdefault(h, set()).add(d)
        if len(docs) >= any_host or any(len(v) >= same_host for v in hosts.values()):
            for k, _, _ in hits:
                out[k] = 'repeated_across_pages'
    return out
