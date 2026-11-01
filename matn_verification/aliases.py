"""Explicit parenthetical definitions in eligible source blocks; no initials inference.

Only long-form (SHORT) syntax is supported. Ambiguous definitions in the same
source are withheld. Sources never lend aliases to one another.
"""
import re
from . import rules

DEFINITION = re.compile(r'\b([A-Z][A-Za-z-]*(?:\s+(?:of|the|and|[A-Z][A-Za-z-]*)){1,7})\s*\(([A-Z][A-Z0-9-]{1,9})\)')


def definitions(documents):
    found={}
    for d in documents:
        for e in d.elements:
            if rules.eligibility(d,e) or e.role not in ('body','paragraph','text'):continue
            for m in DEFINITION.finditer(e.block.text):
                record=dict(doc_id=d.doc_id,block_id=e.block.block_id,start=m.start(),end=m.end(),
                    quote=m[0],long=m[1],short=m[2],pdf_page_index=e.block.page_index,
                    page_label=e.block.page_label,bbox=list(e.bbox.coordinates),bbox_precision=e.bbox.bbox_precision)
                found.setdefault((d.doc_id,m[2]),[]).append(record)
    return {key:rows for key,rows in found.items() if len({r['long'].casefold() for r in rows})==1}


def resolve(text,source,doc_id,index):
    """An alias needs an explicit definition AND its long form in this support."""
    witnesses=[];unresolved=[]
    for name in rules.entities(text):
        if rules._contains(source,name):continue
        rows=index.get((doc_id,name),[])
        eligible=[r for r in rows if rules._contains(source,r['long'])]
        if eligible:witnesses.append(eligible[0])
        else:unresolved.append(name)
    return unresolved,witnesses


def resolve_scoped(text, references, index, *, entity_parser=rules.entities):
    """Bind entities only to this text's selected, original source references.

    A context reference cannot license a claim entity. Definition witnesses are
    retained separately so they can accompany exactly the text they support.
    This checks identity only, never predicate entailment or context necessity.
    """
    unresolved = []
    witnesses = []
    for name in dict.fromkeys(entity_parser(text)):
        if any(rules._contains(ref['quote'], name) for ref in references):
            continue
        eligible = [row for ref in references
                    for row in index.get((ref['doc_id'], name), [])
                    if rules._contains(ref['quote'], row['long'])]
        if not eligible or len({row['long'].casefold() for row in eligible}) != 1:
            unresolved.append(name)
            continue
        if eligible[0] not in witnesses:
            witnesses.append(eligible[0])
    return unresolved, witnesses
