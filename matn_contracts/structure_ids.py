"""Versioned structure identities; legacy reader identities remain untouched."""
import hashlib
import json
from .ids import validate_doc_id


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def structure_id(doc_id, kind, version, inputs):
    validate_doc_id(doc_id)
    if kind not in ('s','t','c'): raise ValueError('invalid structure kind')
    digest=hashlib.sha256(canonical([doc_id,kind,version,inputs]).encode()).hexdigest()[:16]
    return f'{doc_id}:{kind}:{digest}'
