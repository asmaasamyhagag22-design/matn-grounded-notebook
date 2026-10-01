from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

import pymupdf as fitz

from matn_summarization.ollama import OllamaClient

from .planner import _citations
from .renderer import render_presentation, validate_rendered_pptx
from .validation import validate_deck_plan


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE_CACHE = PROJECT_ROOT / "output" / "phase04a-live-cache"
PROMPT_VERSION = "phase04a-live-plan-v1"
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


class LiveGenerationError(RuntimeError):
    pass


def _progress(callback: Callable[[str, str], None] | None, stage: str, state: str) -> None:
    if callback:
        callback(stage, state)


def extract_text_claims(pdf_path: Path, pages: list[int], *, max_claims: int = 24) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    with fitz.open(pdf_path) as document:
        if not pages or min(pages) < 1 or max(pages) > document.page_count:
            raise LiveGenerationError("PAGE_RANGE_OUTSIDE_DOCUMENT")
        for pdf_page in pages:
            text = document[pdf_page - 1].get_text("text", sort=True)
            text = re.sub(r"\s+", " ", text).strip()
            if not text:
                raise LiveGenerationError(f"NO_TEXT_ON_PDF_PAGE:{pdf_page}")
            for sentence in SENTENCE_RE.split(text):
                sentence = sentence.strip()
                if len(sentence) < 45:
                    continue
                chunks = [sentence[index:index + 360].strip() for index in range(0, len(sentence), 360)]
                for chunk in chunks:
                    claim_id = f"live-p{pdf_page:03d}-{len(claims) + 1:03d}"
                    claims.append({
                        "claim_id": claim_id,
                        "claim_text": chunk,
                        "topic": "live extracted source sentence",
                        "importance": "core",
                        "evidence": [{
                            "source_chunk_id": claim_id,
                            "short_quote": chunk[:120],
                            "exact_text": chunk,
                            "start_offset": 0,
                            "end_offset": len(chunk),
                            "pdf_page": pdf_page,
                        }],
                        "numbers_and_units": re.findall(r"\b\d+(?:\.\d+)?(?:%|[A-Za-z]+)?\b", chunk),
                        "technical_terms": [],
                        "limitation_or_uncertainty": None,
                        "extraction_method": "deterministic_pdf_text_sentence",
                        "normalization_notes": [],
                        "content_risk_flags": [],
                        "review_status": "unreviewed",
                    })
                    if len(claims) >= max_claims:
                        return claims
    if not claims:
        raise LiveGenerationError("NO_USABLE_TEXT_CLAIMS")
    return claims


def _response_schema() -> dict[str, Any]:
    bullet = {
        "type": "object",
        "additionalProperties": False,
        "required": ["text", "claim_ids"],
        "properties": {
            "text": {"type": "string", "maxLength": 150},
            "claim_ids": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string"}},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary_title", "summary_points", "slides"],
        "properties": {
            "summary_title": {"type": "string", "maxLength": 90},
            "summary_points": {"type": "array", "minItems": 3, "maxItems": 7, "items": bullet},
            "slides": {
                "type": "array",
                "minItems": 4,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "purpose", "layout", "bullets"],
                    "properties": {
                        "title": {"type": "string", "maxLength": 70},
                        "purpose": {"type": "string", "maxLength": 140},
                        "layout": {"enum": ["title_and_bullets", "two_columns", "three_columns", "process", "takeaways"]},
                        "bullets": {"type": "array", "minItems": 3, "maxItems": 5, "items": bullet},
                    },
                },
            },
        },
    }


def _prompt(claims: list[dict[str, Any]]) -> str:
    evidence = [{"claim_id": item["claim_id"], "pdf_page": item["evidence"][0]["pdf_page"], "text": item["claim_text"]} for item in claims]
    return (
        "Create a concise English academic summary and slide structure using only the evidence below. "
        "Every bullet must cite one or more provided claim_ids. Do not introduce facts, numbers, comparisons, "
        "or citations not present in those claims. Preserve qualifiers, negation, units, maximum versus average, "
        "and Accuracy versus Precision. Use 3-5 bullets per slide, normally 8-16 words each. Return JSON only.\n\n"
        + json.dumps(evidence, ensure_ascii=False)
    )


def _validate_model_result(value: dict[str, Any], claim_ids: set[str]) -> None:
    for item in list(value.get("summary_points", [])) + [bullet for slide in value.get("slides", []) for bullet in slide.get("bullets", [])]:
        ids = item.get("claim_ids")
        if not isinstance(ids, list) or not ids or not set(ids).issubset(claim_ids):
            raise LiveGenerationError("MODEL_RETURNED_UNKNOWN_OR_EMPTY_CLAIM_IDS")
        if not isinstance(item.get("text"), str) or not item["text"].strip():
            raise LiveGenerationError("MODEL_RETURNED_EMPTY_TEXT")


def _build_live_plan(
    source_filename: str,
    source_sha256: str,
    pages: list[int],
    claims: list[dict[str, Any]],
    generated: dict[str, Any],
    *,
    cache_status: str,
    model_calls: int,
    model: str,
    endpoint: str,
) -> dict[str, Any]:
    claim_map = {claim["claim_id"]: claim for claim in claims}
    slides: list[dict[str, Any]] = [{
        "slide_id": "s01",
        "slide_number": 1,
        "title": generated["summary_title"],
        "purpose": "Introduce the uploaded source and selected physical PDF pages.",
        "layout": "title",
        "bullets": [],
        "citations": [],
        "visual_asset": None,
        "speaker_notes": None,
        "validation_status": "validated",
    }]
    for number, item in enumerate(generated["slides"], start=2):
        bullets = item["bullets"]
        slides.append({
            "slide_id": f"s{number:02d}",
            "slide_number": number,
            "title": item["title"],
            "purpose": item["purpose"],
            "layout": item["layout"],
            "bullets": bullets,
            "citations": _citations(bullets, claim_map),
            "visual_asset": None,
            "speaker_notes": None,
            "validation_status": "validated",
        })
    source_number = len(slides) + 1
    disclosure_bullets = generated["summary_points"][:3]
    slides.append({
        "slide_id": f"s{source_number:02d}",
        "slide_number": source_number,
        "title": "Key takeaways and source disclosure",
        "purpose": "Summarize the grounded result and disclose its exact source pages.",
        "layout": "sources",
        "bullets": disclosure_bullets,
        "citations": _citations(disclosure_bullets, claim_map),
        "visual_asset": None,
        "speaker_notes": None,
        "validation_status": "validated",
    })
    used = {claim_id for slide in slides for bullet in slide["bullets"] for claim_id in bullet["claim_ids"]}
    omitted = [{"claim_id": claim["claim_id"], "reason": "Omitted by the local model from the bounded presentation plan."} for claim in claims if claim["claim_id"] not in used]
    return {
        "schema_version": 1,
        "deck_id": "deck-live-" + hashlib.sha256((source_sha256 + str(pages) + PROMPT_VERSION).encode()).hexdigest()[:16],
        "deck_title": generated["summary_title"],
        "source_document_id": "sha256-" + source_sha256,
        "source_filename": source_filename,
        "language": "en",
        "generation_mode": "live_local",
        "source_scope": {"section": None, "pdf_pages": pages, "page_numbering": "physical_1_based"},
        "validation_profile": {"accepted_risk_claim_ids": [], "blocked_claim_ids": [], "human_verification_note": "Live text extraction only; no OCR or visual claim verification."},
        "provenance": {
            "cache_status": cache_status,
            "provenance_mode": "live_local_text_claims",
            "model_generation_calls": model_calls,
            "inference_endpoint": endpoint,
            "model": model,
            "cloud_fallback_enabled": False,
        },
        "slides": slides,
        "omitted_claims": omitted,
    }


def generate_live_local(
    pdf_path: Path,
    pages: list[int],
    output_dir: Path,
    *,
    source_filename: str | None = None,
    model: str = "qwen3.5:9b",
    endpoint: str = "http://127.0.0.1:11434",
    client: OllamaClient | None = None,
    progress: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    _progress(progress, "Source", "active")
    source_bytes = pdf_path.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    claims = extract_text_claims(pdf_path, pages)
    _progress(progress, "Source", "completed")
    cache_key = hashlib.sha256((source_sha + json.dumps(pages) + model + endpoint + PROMPT_VERSION).encode()).hexdigest()
    cache_path = LIVE_CACHE / f"{cache_key}.json"
    if cache_path.is_file():
        _progress(progress, "Grounded summary", "cache_hit")
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        generated = cached["generated"]
        model_calls = 0
        cache_status = "hit"
    else:
        _progress(progress, "Grounded summary", "model_call_active")
        local_client = client or OllamaClient(endpoint)
        local_client.show(model)
        raw, metrics = local_client.generate(model, _prompt(claims), _response_schema(), 4096, 1400, 0, False)
        try:
            generated = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LiveGenerationError("MODEL_RETURNED_INVALID_JSON") from exc
        _validate_model_result(generated, {claim["claim_id"] for claim in claims})
        LIVE_CACHE.mkdir(parents=True, exist_ok=True)
        temp_path = cache_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps({"generated": generated, "metrics": metrics}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp_path, cache_path)
        model_calls = 1
        cache_status = "miss"
        _progress(progress, "Grounded summary", "completed")
    _validate_model_result(generated, {claim["claim_id"] for claim in claims})
    _progress(progress, "Deck plan", "active")
    plan = _build_live_plan(source_filename or pdf_path.name, source_sha, pages, claims, generated, cache_status=cache_status, model_calls=model_calls, model=model, endpoint=endpoint)
    validate_deck_plan(plan, claims, project_root=PROJECT_ROOT)
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "deck-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    _progress(progress, "Deck plan", "completed")
    _progress(progress, "PowerPoint", "active")
    pptx_path = output_dir / "matn-live-local.pptx"
    render_presentation(plan, pptx_path, project_root=PROJECT_ROOT)
    validate_rendered_pptx(pptx_path, expected_slides=len(plan["slides"]))
    _progress(progress, "PowerPoint", "completed")
    return {
        "plan": plan,
        "claims": claims,
        "summary_points": generated["summary_points"],
        "plan_path": plan_path,
        "pptx_path": pptx_path,
        "run_details": {
            "cache_status": cache_status,
            "model_generation_calls": model_calls,
            "inference_endpoint": endpoint,
            "contacted_inference_hosts": ["127.0.0.1" if "127.0.0.1" in endpoint else "localhost"],
            "cloud_fallback_enabled": False,
        },
    }
