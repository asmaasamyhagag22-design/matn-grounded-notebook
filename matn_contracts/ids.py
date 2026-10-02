from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, Sequence


DOC_ID_RE = re.compile(r"^sha256-[0-9a-f]{64}$")
_TENTH = Decimal("0.1")


def validate_doc_id(doc_id: str) -> str:
    if not DOC_ID_RE.fullmatch(doc_id):
        raise ValueError("doc_id must be sha256- followed by 64 lowercase hex characters")
    return doc_id


def validate_bbox(bbox: Sequence[float]) -> tuple[float, float, float, float]:
    if len(bbox) != 4:
        raise ValueError("bbox must contain exactly four coordinates")
    value = tuple(float(item) for item in bbox)
    if not all(math.isfinite(item) for item in value):
        raise ValueError("bbox coordinates must be finite")
    x0, y0, x1, y1 = value
    if x0 >= x1 or y0 >= y1:
        raise ValueError("bbox must satisfy x0 < x1 and y0 < y1")
    return x0, y0, x1, y1


def quantized_bbox(bbox: Sequence[float]) -> tuple[str, str, str, str]:
    validated = validate_bbox(bbox)
    result: list[str] = []
    for coordinate in validated:
        try:
            rounded = Decimal(str(coordinate)).quantize(_TENTH, rounding=ROUND_HALF_UP)
        except InvalidOperation as exc:
            raise ValueError("bbox coordinates must be finite decimal values") from exc
        if rounded == 0:
            rounded = Decimal("0.0")
        result.append(format(rounded, ".1f"))
    return tuple(result)  # type: ignore[return-value]


def canonical_material(parts: Iterable[object]) -> str:
    return json.dumps(list(parts), ensure_ascii=False, separators=(",", ":"))


def short_hash(parts: Iterable[object]) -> str:
    return hashlib.sha256(canonical_material(parts).encode("utf-8")).hexdigest()[:16]


def make_block_id(
    doc_id: str,
    page_index: int,
    bbox: Sequence[float],
    text: str,
) -> str:
    validate_doc_id(doc_id)
    if page_index < 0:
        raise ValueError("page_index must be at least zero")
    digest = short_hash((doc_id, page_index, list(quantized_bbox(bbox)), text))
    return f"{doc_id}:p{page_index:04d}:{digest}"


def make_table_id(doc_id: str, page_index: int, bbox: Sequence[float]) -> str:
    validate_doc_id(doc_id)
    if page_index < 0:
        raise ValueError("page_index must be at least zero")
    digest = short_hash((doc_id, page_index, list(quantized_bbox(bbox))))
    return f"{doc_id}:p{page_index:04d}:table:{digest}"


def make_section_id(
    doc_id: str,
    heading_path: Sequence[str],
    first_block_id: str,
) -> str:
    validate_doc_id(doc_id)
    digest = short_hash((doc_id, list(heading_path), first_block_id))
    return f"{doc_id}:section:{digest}"


def normalized_statement(statement: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", statement).split()).casefold()


def make_fact_id(first_block_id: str, statement: str) -> str:
    return f"fact:{short_hash((first_block_id, normalized_statement(statement)))}"
