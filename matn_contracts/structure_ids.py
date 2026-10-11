"""Versioned structure identities; legacy reader identities remain untouched."""
import hashlib
import json
from .ids import validate_doc_id

SECTION_IDENTITY_VERSION='section-identity-v2'


def section_material(source,path,heading_block_id,parent_id,page_range):
    """Infer the builder's four structural kinds without changing schema shape.

    A heading can become internal without losing its anchor. Openings are
    unique per parent; the pre-heading root is unique per document. Windows
    are disjoint intervals. No text or sibling ordinal supplies uniqueness.
    """
    if heading_block_id is not None:
        kind='heading';anchor=heading_block_id
    elif source=='page_window':
        kind='page_window';anchor=[parent_id,*page_range]
    elif parent_id is not None:
        kind='synthetic_opening';anchor=parent_id
    else:
        kind='root';anchor='document-root'
    return [source,kind,list(path),anchor]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def structure_id(doc_id, kind, version, inputs):
    validate_doc_id(doc_id)
    if kind not in ('s','t','c'): raise ValueError('invalid structure kind')
    digest=hashlib.sha256(canonical([doc_id,kind,version,inputs]).encode()).hexdigest()[:16]
    return f'{doc_id}:{kind}:{digest}'
