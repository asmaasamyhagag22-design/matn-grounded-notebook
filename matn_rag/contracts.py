"""RAG contracts, independent of DocumentStructure and database storage."""
from typing import Literal, TypedDict

INDEX_VERSION = 'rag-index-v1'


class Locator(TypedDict):
    kind: Literal['pdf_block_span', 'json_path']
    payload: dict


class QuerySummary(TypedDict):
    source_id: str
    citable_count: int
    hits: int
    no_lexical_match: bool
    no_citable_content: bool


def canonical(value):
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
