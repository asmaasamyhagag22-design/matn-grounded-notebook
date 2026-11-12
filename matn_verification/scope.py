"""Opt-in preserved-scope verifier. Scope uncertainty is a veto on every path.

The bounded English grammar proves condition direction, not general semantic
paraphrase equivalence. Unknown equivalences abstain; L4 cannot supply this proof.
"""
import json
import re
from typing import Literal

from .prose import sentence_spans, surface, literals, unresolved_opening, literal_in_source
from . import meaning, rules
from .contracts import Receipt, Request, Citation

VERSION = 'preserved-scope-binding-v5.1'
MARKER = re.compile(r'\b(only if|only when|unless|except when|except if|provided that|as long as|if|when|until|except|without)\b', re.I)
QUALIFIER = re.compile(r'^\s*(?:however|except|unless|provided that|this (?:rule|requirement|restriction)|the exception)\b', re.I)
STOP = set('a an the is are was were be been to of in on for and or it this that must should may can not if only unless when'.split())
# A manual's leading option is a real source scope, not a document-title hint.
OPTION_PREFIX = re.compile(r'^\s*((?:--[\w-]+|-[A-Za-z0-9])(?:[,\s]+(?:--[\w-]+|-[A-Za-z0-9]))*)')


def option_scope(text, entries):
    obligations = []
    for _, e, _, _ in entries:
        match = OPTION_PREFIX.match(e.block.text)
        if not match: continue
        aliases = re.findall(r'--[\w-]+|-[A-Za-z0-9]', match.group())
        obligations.append('source_option: '+' / '.join(aliases))
        # Punctuation never proves aliases. Retain every option in source order.
        used = re.findall(r'--[\w-]+|-[A-Za-z0-9]', text)
        if not any(used[i:i+len(aliases)] == aliases for i in range(len(used))):
            return False, obligations
    return True, obligations



class ScopeReceipt(Receipt):
    verifier_version: Literal['preserved-scope-binding-v5.1'] = VERSION
    normalizer_version: Literal['literal-and-option-scope-v5.1'] = 'literal-and-option-scope-v5.1'
    scope_obligations: tuple[str, ...] = ()


def canon(text):
    text = meaning.normalized(text).casefold()
    for pattern, replacement in (
        (r'\bonly when\b', 'only if'),
        (r'\bexcept (?:when|if)\b', 'unless'),
        (r'\bis required to\b', 'must'),
        (r'\bis permitted to\b', 'may'),
        (r'\bis not permitted to\b', 'must not'),
    ):
        text = re.sub(pattern, replacement, text)
    return ' '.join(re.findall(r"--[\w-]+|[\w]+(?:[-'][\w]+)*|[!/=<>+*|&~^]+", text))


def conditions(text):
    """Ordered operator + operand; if and only-if can never collapse together."""
    result = []
    for s in sentence_spans(text):
        sentence = text[s.start:s.end].strip()
        for m in MARKER.finditer(sentence):
            tail = sentence[m.end():].strip()
            if m.start() == 0:
                # An initial condition without a comma has no proved boundary.
                tail = tail.split(',', 1)[0] if ',' in tail else sentence
            else:
                tail = re.split(r'[,;]', tail, maxsplit=1)[0]
            result.append((canon(m.group()), canon(tail)))
    return tuple(result)


def source_units(documents, refs):
    """Whole sentences around citations plus explicitly linked next qualifiers.

    Whitespace at an interval edge never changes obligations. Dependencies may
    be outside the cited span; that makes acceptance harder, never adds evidence.
    """
    units = []
    refs = tuple(refs)
    cited_blocks = {r.block_id for r in refs}
    for d in documents:
        owners = {b:s.section_id for s in d.sections for b in s.block_ids}
        for i, e in enumerate(d.elements):
            if e.block.block_id not in cited_blocks: continue
            spans = sentence_spans(e.block.text)
            for j, s in enumerate(spans):
                a = s.start; z = s.end
                while a < z and e.block.text[a].isspace(): a += 1
                while z > a and e.block.text[z-1].isspace(): z -= 1
                if not any(r.block_id == e.block.block_id and r.start < z and a < r.end for r in refs): continue
                q = e.block.text[a:z]; dependency = ''
                if j+1 < len(spans):
                    nxt = spans[j+1]; candidate = e.block.text[nxt.start:nxt.end]
                    if QUALIFIER.search(candidate): dependency = candidate.strip()
                elif i+1 < len(d.elements):
                    other = d.elements[i+1]
                    if owners.get(e.block.block_id) and owners.get(e.block.block_id) == owners.get(other.block.block_id):
                        ss = sentence_spans(other.block.text)
                        if ss:
                            candidate = other.block.text[ss[0].start:ss[0].end]
                            if QUALIFIER.search(candidate): dependency = candidate.strip()
                # An explicit preceding rule-condition can scope this sentence.
                # Never accept the later exact sentence after deleting that prefix.
                previous = ''
                if j:
                    ps = spans[j-1]; previous = e.block.text[ps.start:ps.end]
                elif i and owners.get(e.block.block_id) and owners.get(e.block.block_id) == owners.get(d.elements[i-1].block.block_id):
                    pe = d.elements[i-1]; pp = sentence_spans(pe.block.text)
                    if pp: previous = pe.block.text[pp[-1].start:pp[-1].end]
                if QUALIFIER.search(previous) and MARKER.search(previous):
                    units.append((q, previous.strip()))
                units.append((q, dependency))
    return tuple(dict.fromkeys(units))


def scope_obligations(text, units):
    obligations = []
    for q, dependency in units:
        main = q.strip()
        marker = MARKER.search(main)
        if marker and marker.start() == 0 and ',' in main:
            main = main.split(',', 1)[1].strip()
        subject = re.split(r'\b(?:is|are|was|were|may|must|should|can|could|might|will|would)\b', main, maxsplit=1, flags=re.I)[0]
        anchors = set(canon(subject).split())-STOP
        aligned = [text[s.start:s.end] for s in sentence_spans(text)
                   if anchors <= set(canon(text[s.start:s.end]).split())]
        aligned_text = ' '.join(aligned)
        have = conditions(aligned_text)
        for op, operand in conditions(q):
            obligations.append(f'{op}: {operand}')
            if (op, operand) not in have: return False, obligations
        if dependency:
            obligations.append('linked: '+canon(dependency))
            if canon(dependency) not in canon(text): return False, obligations
        # Keep explicit modality, polarity and reporting attribution on paraphrase
        # paths too. This is conservative; aliases above are deliberately bounded.
        src = canon(rules._without_calendar_may(q))
        claim = canon(rules._without_calendar_may(aligned_text))
        for pattern in (r'\b(?:must not|should not|may not|must|should|may|might|could|cannot|never|not)\b',
                        r'\baccording to [\w -]+?(?= reports| says| states|$)'):
            for m in re.finditer(pattern, src):
                if m.group() not in claim:
                    obligations.append('force: '+m.group()); return False, obligations
    return True, obligations


def unit_witness(text, entries):
    if unresolved_opening(text): return None
    quoted = literals(text)
    if quoted and not all(any(literal_in_source(value, q) for _, _, _, q in entries) for value in quoted):
        return None
    # A surface proof must cover a complete original sentence, including symbols,
    # conditions and polarity. No token-set equivalence or gap concatenation.
    for d, e, _, _ in entries:
        if e.role == 'table' or rules._value(e.block.block_type) == 'table': continue
        refs = [r for dd, ee, r, _ in entries if dd.doc_id == d.doc_id and ee.block.block_id == e.block.block_id]
        for s in sentence_spans(e.block.text):
            q = e.block.text[s.start:s.end]
            ref = Citation(block_id=e.block.block_id, start=s.start, end=s.end)
            if (surface(q) == surface(text) and q.rstrip().rstrip(')').endswith(('.', '!', '?'))
                    and rules.interval_covered(ref, refs) and not meaning.UNRESOLVED.search(q.strip())):
                return [(d, e, ref, q)]
    proof = meaning.witness(text, entries)
    if proof: return proof
    if meaning.UNRESOLVED.search(text.strip()): return None
    # Complete consecutive sentences from ONE original block, not disjoint union.
    for d, e, _, _ in entries:
        if e.role == 'table' or rules._value(e.block.block_type) == 'table': continue
        spans = sentence_spans(e.block.text)
        refs = [r for dd, ee, r, _ in entries if dd.doc_id == d.doc_id and ee.block.block_id == e.block.block_id]
        for i, left in enumerate(spans):
            for right in spans[i:i+3]:
                q = e.block.text[left.start:right.end]
                ref = Citation(block_id=e.block.block_id, start=left.start, end=right.end)
                if (meaning.normalized(q) == meaning.normalized(text) and q.rstrip().rstrip(')').endswith(('.', '!', '?'))
                        and rules.interval_covered(ref, refs)):
                    return [(d, e, ref, q)]
    from .binding import syntactic_witness
    return syntactic_witness(text, entries)


def _surface_l2(text, entries, target):
    if unit_witness(text, entries):
        return rules._check(target, 'L2')
    return rules._l2(text, entries, target)


def verify_scope(documents, request, entailment=None):
    docs = tuple(documents)
    result = meaning.verify_meaning(docs, request, entailment, witness_fn=unit_witness, l2=_surface_l2)
    obligations = []; checks = list(result.checks)
    try:
        req = Request.model_validate_json(json.dumps(request))
        targets = [(f'claim:{i}', c.text, c.citations) for i, c in enumerate(req.claims)]
        targets.append(('sentence', req.sentence, tuple(r for c in req.claims for r in c.citations)))
        for target, text, refs in targets:
            by = {e.block.block_id: (d, e) for d in docs for e in d.elements}
            entries = [(by[r.block_id][0], by[r.block_id][1], r,
                        by[r.block_id][1].block.text[r.start:r.end]) for r in refs]
            units = source_units(docs, refs)
            # Even exact sentences must keep explicitly linked adjacent qualifiers.
            if unit_witness(text, entries):
                found = ['complete_source_surface' if any(surface(text) == surface(q)
                         for _, _, _, q in unit_witness(text, entries)) else 'bounded_source_grammar']
                ok = all(not dep or canon(dep) in canon(text) for _, dep in units)
            else:
                ok, found = scope_obligations(text, units)
            # Literal accuracy is independent of semantic entailment, even if L4
            # assigns a high score to a nearly identical but altered string.
            if any(not any(literal_in_source(value, q) for _, _, _, q in entries) for value in literals(text)):
                ok = False
                found.append('literal_mismatch')
            if unresolved_opening(text):
                ok = False
                found.append('unresolved_source_antecedent')
            # An option label does not prove the actor of a command. A bounded
            # source form is required for option rules, independent of L4 scores.
            if any(OPTION_PREFIX.match(e.block.text) for _, e, _, _ in entries) and not unit_witness(text, entries):
                ok = False
                found.append('option_action_unproved')
            mode_ok, modes = option_scope(text, entries)
            ok = ok and mode_ok
            obligations.extend(found + modes)
            if not ok: checks.append(rules._check(target, 'L3', 'unknown', ('scope_unknown',)))
    except (ValueError, KeyError, TypeError):
        checks.append(rules._check('sentence', 'L3', 'unknown', ('scope_unknown',)))
    return ScopeReceipt(**{**result.model_dump(exclude={'verifier_version','normalizer_version'}),
        'checks':tuple(checks), 'status':rules.aggregate(checks), 'scope_obligations':tuple(dict.fromkeys(obligations))})
