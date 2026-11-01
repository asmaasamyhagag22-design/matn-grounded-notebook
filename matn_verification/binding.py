"""Bounded grammatical identities, with source-addressed manual attribution.

A manual NAME record identifies a program, but never proves that the program
is the actor of an imperative. No imperative-to-declarative rewrite is allowed.
All lexical content, conditions, options and quantities remain identical.
"""
import re
from . import rules
from .contracts import Citation
from .prose import sentence_spans, surface

NAME = re.compile(r'^NAME\s+([a-z][a-z0-9_-]*)\s+[-–—]\s+\S')


def grammar(text):
    # Literal-bearing text has no grammar rewrites or interior normalization.
    from .prose import literals
    if literals(text): return text.strip()
    # Apply the existing prefix normalization before conditional rewrites.
    text = surface(text)
    # Discourse connective and article/relational syntax, not content synonyms.
    text = re.sub(r'^Therefore,\s*', '', text, flags=re.I)
    text = re.sub(r'\bfor (?:a|an) ([a-z]+) table entry\b',
                  r'for an entry in the \1 table', text)
    text = re.sub(r'\bcorresponding ([a-z]+) table entry\b',
                  r'corresponding entry in the \1 table', text)
    text = re.sub(r'\bfor (?:a|an) entry in the\b', 'for an entry in the', text)
    text = re.sub(r'^(if\b[^,]+),\s*then\s+', r'\1, ', text, flags=re.I)
    return surface(text)


def manual_context(documents, block_ids):
    """Explicit retrieval expansion; caller journals the returned source spans."""
    result = []
    for d in documents:
        if not any(e.block.block_id in block_ids and
                   re.match(r'^\s*--?[A-Za-z]', e.block.text) for e in d.elements):
            continue
        names = [e for e in d.elements if NAME.match(e.block.text)]
        if len(names) != 1: continue  # conflicting/unscoped NAME records abstain
        e = names[0]
        if rules.eligibility(d, e): continue
        result.append(dict(block_id=e.block.block_id, start=0, end=len(e.block.text), quote=e.block.text))
    return result


def syntactic_witness(text, entries):
    """One whole source block or complete sentence, after bounded rewrites.

    Only discourse/article syntax is transformed. NAME cannot bind an action.
    """
    for d, e, _, _ in entries:
        if e.role == 'table' or rules._value(e.block.block_type) == 'table': continue
        refs = [r for dd, ee, r, _ in entries if dd.doc_id == d.doc_id and ee.block.block_id == e.block.block_id]
        spans = sentence_spans(e.block.text)
        candidates = [(s.start, s.end) for s in spans]
        if spans: candidates.append((spans[0].start, spans[-1].end))
        for a, z in candidates:
            q = e.block.text[a:z]
            ref = Citation(block_id=e.block.block_id, start=a, end=z)
            if not q.rstrip().endswith(('.', '!', '?')) or not rules.interval_covered(ref, refs): continue
            proof = [(d, e, ref, q)]
            if grammar(q) == grammar(text): return proof
    return None
