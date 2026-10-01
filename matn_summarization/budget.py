from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Callable

from .io import Phase03Error


@dataclass(frozen=True)
class SourceUnit:
    unit_id: str
    source_chunk_id: str
    text: str
    parent_chunk_id: str | None
    pdf_page: int
    start_offset: int
    end_offset: int


class ContextBudgeter:
    def __init__(self, active_context: int, reserved_output_tokens: int, safety_margin: int, tokens_per_character: float):
        self.active_context = active_context
        self.reserved_output_tokens = reserved_output_tokens
        self.safety_margin = safety_margin
        self.tokens_per_character = max(tokens_per_character, 0.30)

    def estimate(self, text: str) -> int:
        return max(1, int(len(text) * self.tokens_per_character + 0.999))

    def available_source_characters(self, fixed_prompt_without_source: str, schema_text: str) -> int:
        fixed = self.estimate(fixed_prompt_without_source) + self.estimate(schema_text)
        available_tokens = self.active_context - fixed - self.reserved_output_tokens - self.safety_margin
        if available_tokens <= 0:
            raise Phase03Error("CONTEXT_BUDGET_FIXED_OVERHEAD_TOO_LARGE")
        return max(1, int(available_tokens / self.tokens_per_character))

    def assert_fits(self, prompt: str, schema_text: str) -> dict[str, int | float]:
        prompt_tokens = self.estimate(prompt)
        schema_tokens = self.estimate(schema_text)
        total = prompt_tokens + schema_tokens + self.reserved_output_tokens + self.safety_margin
        if total > self.active_context:
            raise Phase03Error("NOT_APPLICABLE_CONTEXT_LIMIT")
        return {
            "estimated_prompt_tokens": prompt_tokens,
            "preflight_prompt_tokens": prompt_tokens,
            "preflight_schema_tokens": schema_tokens,
            "requested_output_reserve": self.reserved_output_tokens,
            "reserved_output_tokens": self.reserved_output_tokens,
            "safety_margin_tokens": self.safety_margin,
            "preflight_total_tokens": total,
            "unused_context_headroom": self.active_context - total,
            "active_context": self.active_context,
            "tokens_per_character": self.tokens_per_character,
        }


def _stable_fragment_id(chunk_id: str, start: int, end: int, text: str) -> str:
    digest = hashlib.sha256(f"{chunk_id}|{start}|{end}|{text}".encode("utf-8")).hexdigest()[:16]
    return f"frg-{digest}"


def fragment_chunk(chunk: dict[str, Any], max_chars: int) -> list[SourceUnit]:
    text = chunk.get("selection_text", "")
    if len(text) <= max_chars:
        return [SourceUnit(chunk["chunk_id"], chunk["chunk_id"], text, None, chunk["pdf_page"], 0, len(text))]
    boundaries = [match.end() for match in re.finditer(r"(?<=[.!?])\s+|\n\n+|\n(?=#{1,6}\s)", text)]
    result: list[SourceUnit] = []
    start = 0
    while start < len(text):
        target = min(len(text), start + max_chars)
        candidates = [point for point in boundaries if start < point <= target]
        end = max(candidates) if candidates else target
        fragment = text[start:end]
        result.append(SourceUnit(_stable_fragment_id(chunk["chunk_id"], start, end, fragment), chunk["chunk_id"], fragment, chunk["chunk_id"], chunk["pdf_page"], start, end))
        start = end
    return result


def partition_units(
    units: list[SourceUnit],
    fits: Callable[[list[SourceUnit]], bool],
    *,
    max_units: int | None = None,
) -> list[list[SourceUnit]]:
    batches: list[list[SourceUnit]] = []
    current: list[SourceUnit] = []
    for unit in units:
        proposed = current + [unit]
        if current and ((max_units is not None and len(proposed) > max_units) or not fits(proposed)):
            batches.append(current)
            current = [unit]
        else:
            current = proposed
        if not fits(current):
            raise Phase03Error("OVERSIZED_SOURCE_FRAGMENT")
    if current:
        batches.append(current)
    return batches
