"""Exact local source context for display, separate from claim evidence.

The structural anaphora gate is a conservative veto, not coreference proof.
It requires an independent noun-phrase candidate in the visible local window
or governing headings. It neither rewrites text nor establishes entailment.
"""
import re

from matn_verification import rules
from matn_verification.prose import sentence_spans

POLICY = 'local-context-display-v1'
MAX_SENTENCES = 3
MAX_CHARACTERS = 1200
REFERENCES = re.compile(r'\b(?:the\s+(?:above|following|former|latter)|this|that|these|those|it|its|they|them|their|such|here|there|said)\b', re.I)
WORDS = re.compile(r"[A-Za-z][A-Za-z0-9'’&-]*")
# Closed grammatical vocabulary for a bounded phrase recognizer, not a topic or
# entity list. Unknown syntax stays unresolved instead of guessing a referent.
PREDICATES = frozenset('''is are was were be been being has have had can could may might must shall should will would
do does did need needs require requires include includes provide provides support supports help helps
reduce reduces increase increases improve improves face faces use uses allow allows enable enables
offer offers serve serves train trains publish publishes identify identifies keep keeps make makes
show shows give gives mean means contain contains affect affects remain remains become becomes
work works build builds track tracks create creates address addresses solve solves'''.split())
FUNCTIONS = frozenset('''a an the some several many multiple each every both no one another other of for to from
in on at by with without and or but as if when while because before after during within than more most
less very often usually also only not all any about into across over under through between among
which who whose what how why where whether'''.split())
TEMPORAL = re.compile(r'^\s+(?:year|month|week|day|quarter|season|morning|afternoon|evening)\b', re.I)
EXPLETIVE = re.compile(r'^\s+(?:is|was|seems?|appears?)\s+(?:(?:very|particularly|also)\s+)?(?:important|necessary|possible|likely|clear|useful|essential|difficult|hard|advisable|recommended|appropriate|unlikely|easy)\b', re.I)


def _kind(element):
    return str(getattr(element.block.block_type, 'value', element.block.block_type))


def _level(element):
    for flag in element.flags:
        if flag.startswith('html_heading_level:'):
            return int(flag.split(':')[1])
    return None


def _citation(document, element, start, end):
    b = element.block
    return dict(doc_id=document.doc_id, block_id=b.block_id, start=start, end=end,
                quote=b.text[start:end], pdf_page_index=b.page_index,
                page_label=b.page_label, bbox=list(element.bbox.coordinates),
                bbox_precision=element.bbox.bbox_precision)


def _headings(document, position):
    """Nearest heading and its governing ancestors, exact and in source order."""
    chain = []; depth = None
    for element in reversed(document.elements[:position]):
        if _kind(element) != 'heading' or not element.block.text.strip():
            continue
        level = _level(element)
        if depth is not None and (level is None or level >= depth):
            continue
        # An ineligible heading is a boundary, never permission to climb past it.
        if rules.eligibility(document, element):
            break
        text = element.block.text
        start = len(text) - len(text.lstrip()); end = len(text.rstrip())
        chain.append(_citation(document, element, start, end))
        if level is None or level == 1:
            break
        depth = level
    return list(reversed(chain))


def build_context(document, support):
    """Bounded immediately preceding sentences in the same structural section.

    A table, excluded block, section boundary or unreasonably large immediately
    preceding sentence stops the walk. No skipped sentence is silently bridged.
    """
    elements = list(document.elements)
    position = next(i for i, e in enumerate(elements) if e.block.block_id == support['block_id'])
    element = elements[position]
    if (rules.eligibility(document, element) or support['quote'] != element.block.text[support['start']:support['end']]
            or support['doc_id'] != document.doc_id):
        raise ValueError('DISPLAY_CONTEXT_SOURCE')
    owner = next((s for s in document.sections if support['block_id'] in s.block_ids), None)
    section_blocks = set(owner.block_ids) if owner else {support['block_id']}
    preceding = []; characters = 0; stopped = None
    for index in range(position, -1, -1):
        prior = elements[index]
        if prior.block.block_id not in section_blocks or _kind(prior) == 'heading':
            break
        if rules.eligibility(document, prior) or prior.role not in ('text', 'list') or _kind(prior) == 'table':
            stopped = 'ineligible_or_nonprose_boundary'; break
        spans = [s for s in sentence_spans(prior.block.text) if index != position or s.end <= support['start']]
        for span in reversed(spans):
            size = span.end - span.start
            if len(preceding) == MAX_SENTENCES or characters + size > MAX_CHARACTERS:
                stopped = 'window_limit'; break
            preceding.append(_citation(document, prior, span.start, span.end)); characters += size
        if stopped:
            break
    headings = _headings(document, position)
    h1 = next((e for e in elements if _kind(e) == 'heading' and _level(e) == 1
               and not rules.eligibility(document, e)), None)
    title = h1.block.text.strip() if h1 is not None else document.title.strip()
    # The generic ingestion identifier is not a source title.
    if re.fullmatch(r'Public (?:HTML|PDF) [0-9a-f]+', title):
        title = 'Source title not recorded'
    result = dict(policy=POLICY, preceding=list(reversed(preceding)), headings=headings,
                  source_title=title, source_title_citation=(
                      _citation(document, h1, 0, len(h1.block.text)) if h1 is not None else None),
                  section_id=owner.section_id if owner else None,
                  limits=dict(previous_sentences=MAX_SENTENCES, context_characters=MAX_CHARACTERS,
                              cross_block=True, same_section=True), boundary=stopped)
    result['anaphora'] = anaphora_audit(support['quote'], result)
    return result


def references(text):
    """Referential occurrences only; fixed expletive/discourse grammar is exempt."""
    found = []
    for match in REFERENCES.finditer(text):
        word = match.group().lower(); tail = text[match.end():]; before = text[:match.start()]
        previous = WORDS.findall(before)[-1].lower() if WORDS.findall(before) else ''
        after = WORDS.findall(tail); following = after[0].lower() if after else ''
        if word == 'it' and EXPLETIVE.search(tail): continue
        if word == 'there' and re.match(r'^\s+(?:is|are|was|were|has|have|had|exists?)\b', tail, re.I): continue
        if word == 'that' and re.match(r'^\s+is(?:\s*,|\s+to\s+say\b)', tail, re.I): continue
        if word == 'this' and TEMPORAL.search(tail): continue
        if word == 'such' and re.match(r'^\s+as\b', tail, re.I): continue
        # Relative/complement "that" does not point outside its own clause.
        if word == 'that' and (previous in {'ensure','ensures','show','shows','know','knows','say','says','said','means','believe','believes','suggest','suggests'}
                               or previous not in PREDICATES | FUNCTIONS and following in PREDICATES): continue
        if word == 'said' and previous and previous not in {'the', 'a', 'an'}: continue
        head = None
        if word in {'this', 'that', 'these', 'those', 'such', 'said', 'the above', 'the following'} and following not in PREDICATES | FUNCTIONS:
            head = following or None
        found.append(dict(word=word, start=match.start(), end=match.end(), head=head))
    return found


def noun_phrases(text, *, heading=False):
    """Independent bounded phrase candidates; no anaphoric phrase resolves itself."""
    if references(text): return []
    words = list(WORDS.finditer(text)); tokens = [w.group().lower() for w in words]
    if not tokens: return []
    if heading:
        lexical = [w.group() for w in words if w.group().lower() not in FUNCTIONS | PREDICATES]
        return [' '.join(lexical)] if len(lexical) >= 2 or any(re.search(r'[a-z][A-Z]|[A-Za-z]\d', w) for w in lexical) else []
    end = next((i for i, token in enumerate(tokens) if token in PREDICATES), None)
    if end is None or end == 0 or end > 9: return []
    subject = [w.group() for w in words[:end] if w.group().lower() not in FUNCTIONS]
    if not subject or tokens[0] in {'if','when','while','because','unless','without','despite'}: return []
    return [' '.join(subject)]


def anaphora_audit(text, context):
    """A structural veto over exactly the context that will be displayed.

    Candidate presence does not establish that it is the correct referent.
    Semantic displayed-context review is still required for precision labels.
    """
    candidates = []
    for kind in ('preceding', 'headings'):
        for citation in context.get(kind, []):
            for phrase in noun_phrases(citation['quote'], heading=kind == 'headings'):
                candidates.append(dict(phrase=phrase, block_id=citation['block_id'],
                                       start=citation['start'], end=citation['end'], origin=kind))
    needs = references(text); unresolved = []
    for need in needs:
        suitable = candidates
        if need['head']:
            head = need['head'].rstrip('s').lower()
            suitable = [c for c in candidates if head in {w.lower().rstrip('s') for w in WORDS.findall(c['phrase'])}]
        if need['word'] in ('the former', 'the latter') and len({c['phrase'] for c in suitable}) < 2:
            suitable = []
        if not suitable: unresolved.append(need)
    return dict(references=needs, candidates=candidates, unresolved=unresolved,
                resolved=not unresolved, guarantee='structural candidate presence; not coreference proof')


def validate_context(document, support, context):
    if context != build_context(document, support):
        raise ValueError('DISPLAY_CONTEXT_BINDING')
    return context
