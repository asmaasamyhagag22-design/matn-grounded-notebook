from __future__ import annotations

from typing import Any


def _citations(bullets: list[dict[str, Any]], claim_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_page_set: dict[tuple[int, ...], list[str]] = {}
    ordered_ids: list[str] = []
    for bullet in bullets:
        for claim_id in bullet["claim_ids"]:
            if claim_id not in ordered_ids:
                ordered_ids.append(claim_id)
    for claim_id in ordered_ids:
        pages = tuple(sorted({int(item["pdf_page"]) for item in claim_map[claim_id]["evidence"]}))
        by_page_set.setdefault(pages, []).append(claim_id)
    return [{"claim_ids": ids, "pdf_pages": list(pages)} for pages, ids in by_page_set.items()]
