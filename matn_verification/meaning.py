"""Opt-in Phase03: exact complete-sentence witnesses, never flattened unions.

The baseline remains available for paraphrases. Additional permissions require
one complete source sentence in original order, with every numeric provenance
check retained. No core rule globals, source snapshots or defaults are mutated.
"""
from typing import Literal
import re
import unicodedata

from matn_reading.structure.sentences import sentence_spans
from . import rules
from .contracts import Citation, Request, Receipt
from .numbers import parse

VERSION = 'evidence-meaning-v1'


class MeaningReceipt(Receipt):
    verifier_version: Literal['evidence-meaning-v1'] = VERSION
    normalizer_version: Literal['english-explicit-identity-v1'] = 'english-explicit-identity-v1'


def meaning_receipt(result):
    return MeaningReceipt(**{**result.model_dump(), 'verifier_version': VERSION,
                             'normalizer_version': 'english-explicit-identity-v1'})
# Explicit syntactic identities, not arbitrary digit-bearing words. Unknown IDs
# and scientific notation still abstain. Masking preserves character offsets.
IDENTIFIER = re.compile(r'\b(?:RFC\s+\d{3,5}|(?:version|TLS|HTTP)\s+\d+(?:\.\d+)+|(?:GPT|Claude|Llama)-\d+(?:\.\d+)*(?:-[A-Za-z]+)?)\b', re.I)
UNRESOLVED = re.compile(r'^(?:it|they|this|these|those|we|our|he|she|their|here|since then|today)(?=\s|[,.!?]|$)', re.I)


def normalized(text):
    text = unicodedata.normalize('NFKC', text).translate(str.maketrans('‘’“”', "''\"\""))
    return ' '.join(text.split()).strip()


def parse_quantities(text):
    chars = list(text)
    for match in IDENTIFIER.finditer(text):
        chars[match.start():match.end()] = ' ' * (match.end()-match.start())
    return parse(''.join(chars))


def continuous(documents, refs):
    """Continuation needs adjacency and shared source section, not page equality."""
    by = {e.block.block_id: (d, i, e) for d in documents for i, e in enumerate(d.elements)}
    owners = {b: s.section_id for d in documents for s in d.sections for b in s.block_ids}
    for left, right in zip(refs, refs[1:]):
        d, i, e = by[left.block_id]; other, j, f = by[right.block_id]
        if left.block_id == right.block_id:
            if left.end != right.start: return False
        elif (d.doc_id != other.doc_id or j != i+1 or left.end != len(e.block.text)
              or right.start != 0 or not owners.get(left.block_id)
              or owners.get(left.block_id) != owners.get(right.block_id)):
            return False
        if any(rules.eligibility(x, y) or y.role not in ('body', 'paragraph', 'text')
               or any('order' in flag for flag in y.flags) for x, y in ((d, e), (other, f))):
            return False
    return True


def witness(text, entries):
    """Return original entries for ONE complete sentence, or no new permission.

    Match against full block sentences, not citation substrings. Therefore a
    caller cannot crop away a condition/negative/antecedent and claim exactness.
    Irrelevant citations are still checked by L0 and retained in receipts.
    """
    if UNRESOLVED.search(text.strip()): return None
    wanted = normalized(text)
    if not wanted: return None
    # A single full source sentence may be covered by several declared spans.
    for d, e, _, _ in entries:
        if e.role == 'table' or rules._value(e.block.block_type) == 'table': continue
        refs = [r for dd, ee, r, q in entries if dd.doc_id == d.doc_id and ee.block.block_id == e.block.block_id]
        for s in sentence_spans(e.block.text):
            q = e.block.text[s.start:s.end]
            ref = Citation(block_id=e.block.block_id, start=s.start, end=s.end)
            if (q.rstrip().endswith(('.', '!', '?', '.”', '."')) and normalized(q) == wanted
                    and not UNRESOLVED.search(q.strip()) and rules.interval_covered(ref, refs)):
                return [(d, e, ref, q)]
    # Multi-block source continuation: no gaps, no reordering, no invented quote.
    docs = tuple({d.doc_id: d for d, _, _, _ in entries}.values())
    for group in rules.evidence_bundles(docs, [r for _, _, r, _ in entries]):
        if len(group) < 2 or not continuous(docs, group): continue
        selected = [entry for ref in group for entry in entries if entry[2] == ref]
        first, last = selected[0], selected[-1]
        if first[2].start not in {s.start for s in sentence_spans(first[1].block.text)}: continue
        q = ' '.join(x[3].strip() for x in selected)
        if (len(sentence_spans(q)) == 1 and q.rstrip().endswith(('.', '!', '?'))
                and normalized(q) == wanted and not UNRESOLVED.search(q.strip())
                and last[2].end in {s.end for s in sentence_spans(last[1].block.text)}):
            return selected
    return None


# Clone only the numeric layer to recognize explicitly marked identities; all
# quantity ledger/status/cell/scope checks use their unchanged implementation.
def _numeric(text, entries, target):
    return rules._l1(text, entries, target, parser=parse_quantities)


def verify_meaning(documents, request, entailment=None, *, witness_fn=None, l2=None):
    witness_fn = witness_fn or witness
    l2 = l2 or rules._l2
    docs = tuple(documents)
    # No witness means the EXACT baseline, including separate L4 edge calls.
    # Lexical gates alone cannot preserve the baseline's semantic vetoes.
    try:
        req = Request.model_validate_json(__import__('json').dumps(request))
        by = {e.block.block_id: (d, e) for d in docs for e in d.elements}
        targets = [(c.text, c.citations) for c in req.claims]
        union = tuple({(r.block_id, r.start, r.end): r for c in req.claims for r in c.citations}.values())
        targets.append((req.sentence, union))
        for text, refs in targets:
            entries = [(by[r.block_id][0], by[r.block_id][1], r,
                        by[r.block_id][1].block.text[r.start:r.end]) for r in refs]
            if not witness_fn(text, entries):
                result = rules.verify(docs, request, entailment)
                # A source-substring citation cannot hide an antecedent,
                # condition or negation outside its declared boundaries.
                cropped = any(r.start not in {s.start for s in sentence_spans(e.block.text)}
                              or r.end not in {s.end for s in sentence_spans(e.block.text)}
                              for d, e, r, q in entries)
                if cropped:
                    checks = result.checks + (rules._check('sentence', 'L3', 'unknown', ('entity_binding_unknown',)),)
                    result = result.model_copy(update={'checks': checks, 'status': rules.aggregate(checks)})
                return meaning_receipt(result)
    except (ValueError, KeyError, TypeError):
        return meaning_receipt(rules.verify(docs, request, entailment))
    layers=[]
    for name in ('_l1', '_l2', '_l3'):
        original = l2 if name=='_l2' else getattr(rules, name)
        def layer(text, entries, target, original=original, name=name):
            proof = witness_fn(text, entries)
            if proof:
                semantic = rules._semantic_entries(proof) if len(proof)>1 else proof
                if name=='_l1':return _numeric(text,semantic,target)
                if name=='_l3':return rules._check(target,'L3')
                return original(text,semantic,target)
            return original(text,entries,target)
        layers.append(layer)
    result=rules.verify(docs,request,entailment,layers=layers,
        bundles=lambda ds,refs:[list(refs)] if refs else [],semantic_entries=lambda entries:entries)
    # Version the opt-in receipt; never serialize it as a baseline receipt.
    return meaning_receipt(result)
