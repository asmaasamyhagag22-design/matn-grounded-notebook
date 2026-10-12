"""RAG contracts, independent of DocumentStructure and database storage."""
from typing import Literal, TypedDict, NotRequired

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
    coverage_shortfall: NotRequired[int]


def canonical(value):
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


class Source(TypedDict):
    source_id: str
    doc_id: str
    source_type: Literal['pdf']
    structure_fingerprint: str
    tokenizer_version: str
    index_version: str
    digest: str


class Hit(TypedDict):
    chunk_id: str
    source_id: str
    doc_id: str
    text: str
    context_prefix: str
    kind: str
    section_path: list[str]
    evidence: list[Locator]
    numeric_tokens: list[dict]
    unavailable_tables: list[dict]
    coverage_flags: list[str]
    bm25_rank: int | None
    bm25_score: float | None
    vector_rank: int | None
    vector_score: float | None
    rrf_rank: int | None
    rrf_score: float
    coverage_slot: bool
    per_source_rank: int | None
    matched_lexical_terms: list[str]


class SearchResult(TypedDict):
    mode: Literal['focused', 'survey']
    ablation: Literal['hybrid', 'bm25', 'vector', 'no-prefix']
    hits: list[Hit]
    summary: list[QuerySummary]
    context: list[dict]
