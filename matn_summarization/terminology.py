from __future__ import annotations

import re
from typing import Any

from .evidence import canonical_text


def required_glossary_terms(claims: list[dict[str, Any]], glossary: dict[str, Any]) -> list[str]:
    source = canonical_text(" ".join(claim.get("claim_text", "") for claim in claims)).casefold()
    return [term for term in glossary.get("terms", {}) if canonical_text(term).casefold() in source]


def validate_arabic_terminology(
    points: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    glossary: dict[str, Any],
) -> list[str]:
    rendered = canonical_text(" ".join(point.get("point_text", "") for point in points)).casefold()
    missing: list[str] = []
    for term in required_glossary_terms(claims, glossary):
        expected = canonical_text(str(glossary["terms"][term])).casefold()
        if expected in rendered:
            continue
        parenthetical = f"({canonical_text(term).casefold()})"
        preferred = [
            canonical_text(value).casefold()
            for rule in glossary.get("semantic_rules", [])
            if canonical_text(str(rule.get("source_term", ""))).casefold() == canonical_text(term).casefold()
            for value in rule.get("preferred_arabic", [])
        ]
        arabic_label = expected.split("(", 1)[0].strip()
        flexible_label = re.sub(r"^ال", "", arabic_label)
        if parenthetical in rendered and (
            any(value in rendered for value in preferred)
            or (flexible_label and flexible_label in rendered)
        ):
            continue
        missing.append(term)
    return missing
