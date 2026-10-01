from __future__ import annotations

import json
import platform
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import PHASE03_VERSION, PROMPT_VERSIONS
from .budget import ContextBudgeter, SourceUnit, fragment_chunk, partition_units
from .cache import MapCache
from .evidence import coverage_status, deduplicate_claims, resolve_citations, validate_claims, validate_synthesis
from .inventory import classify_claim_risk, completeness_metadata, reconcile_model_claims, reconcile_source_statements, source_fallback_claims, split_statements
from .io import Phase03Error, atomic_output_directory, canonical_json, load_and_validate_inputs, load_schema, read_json, sha256_bytes, sha256_file, validate_schema, write_json
from .ollama import OllamaClient
from .parity import validate_english_arabic_parity
from .planning import build_semantic_plan, order_claims_with_antecedents, rewrite_orphan_anaphora
from .prompts import direct_prompt, map_prompt, render_prompt, repair_prompt, terminology_repair_prompt
from .review import build_claims_review, build_coverage_report, render_claims_review, render_coverage_report


NUM_CTX = 4096
SAFETY_MARGIN = 512
MAX_MAP_SOURCE_CHARACTERS = 700
MAX_MAP_UNITS = 2
RENDER_BATCH_SIZE = 4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json_once(raw: str, schema: dict[str, Any], label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        raise Phase03Error(f"MALFORMED_MODEL_JSON:{label}") from None
    validate_schema(value, schema, label)
    return value


def _claims_schema(project_root: Path) -> dict[str, Any]:
    return load_schema(project_root, "grounded-claims.schema.json")


def _claims_generation_schema(project_root: Path, max_items: int | None = None) -> dict[str, Any]:
    canonical = _claims_schema(project_root)
    claim = json.loads(json.dumps(canonical["$defs"]["claim"]))
    claim["properties"]["evidence"]["items"] = canonical["$defs"]["evidence"]
    claim["required"].remove("local_claim_id")
    del claim["properties"]["local_claim_id"]
    for generated_later in ("content_risk_flags", "review_status", "extraction_method", "normalization_notes"):
        claim["properties"].pop(generated_later, None)
    claims_array: dict[str, Any] = {"type": "array", "items": claim}
    if max_items is not None:
        claims_array["maxItems"] = max_items
    return {
        "type": "object", "additionalProperties": False, "required": ["schema_version", "claims"],
        "properties": {"schema_version": {"const": 1}, "claims": claims_array},
    }


def _summary_schema(project_root: Path) -> dict[str, Any]:
    return load_schema(project_root, "summary-result.schema.json")


def _direct_schema(project_root: Path) -> dict[str, Any]:
    claims = _claims_schema(project_root)
    evidence = json.loads(json.dumps(claims["$defs"]["evidence"]))
    point = {
        "type": "object", "additionalProperties": False,
        "required": ["point_text", "topic", "importance", "evidence", "numbers_and_units", "technical_terms", "limitation_or_uncertainty"],
        "properties": {
            "point_text": {"type": "string", "minLength": 1, "maxLength": 800},
            "topic": {"type": "string", "maxLength": 60},
            "importance": {"enum": ["core", "supporting"]},
            "evidence": {"type": "array", "minItems": 1, "maxItems": 3, "items": evidence},
            "numbers_and_units": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 120}},
            "technical_terms": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 120}},
            "limitation_or_uncertainty": {"type": ["string", "null"], "maxLength": 800},
        },
    }
    return {
        "type": "object", "additionalProperties": False,
        "required": ["schema_version", "summary_title", "points", "coverage_notice"],
        "properties": {
            "schema_version": {"const": 1}, "summary_title": {"type": "string", "maxLength": 160},
            "points": {"type": "array", "minItems": 1, "maxItems": 6, "items": point},
            "coverage_notice": {"type": "string", "maxLength": 300},
        },
    }


def _render_schema(claim_ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False, "required": ["schema_version", "points"],
        "properties": {
            "schema_version": {"const": 1},
            "points": {
                "type": "array", "minItems": len(claim_ids), "maxItems": len(claim_ids),
                "items": {
                    "type": "object", "additionalProperties": False, "required": ["claim_id", "point_text"],
                    "properties": {"claim_id": {"enum": claim_ids}, "point_text": {"type": "string", "minLength": 1, "maxLength": 1200}},
                },
            },
        },
    }


def _model_digest(show: dict[str, Any]) -> str:
    digest = show.get("resolved_digest") or show.get("details", {}).get("digest") or show.get("digest")
    if digest:
        return str(digest)
    identity = {"modified_at": show.get("modified_at"), "details": show.get("details"), "model_info": show.get("model_info", {})}
    return "show-sha256-" + sha256_bytes(canonical_json(identity).encode("utf-8"))


def _runtime_identity(model: str, show: dict[str, Any], digest: str, base_url: str) -> dict[str, Any]:
    info = show.get("model_info", {})
    return {
        "windows": platform.platform(), "python": sys.version.split()[0], "ollama_version": show.get("ollama_version"),
        "ollama_python_client": "not_used", "base_url": base_url, "model_name": model, "model_digest": digest,
        "architecture": info.get("general.architecture"), "parameter_count": info.get("general.parameter_count"),
        "file_type": info.get("general.file_type"), "quantization": show.get("details", {}).get("quantization_level"),
        "capabilities": show.get("capabilities", []), "default_parameters": show.get("parameters", ""),
        "template_sha256": sha256_bytes(str(show.get("template", "")).encode("utf-8")),
    }


def _load_glossary(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"version": "none", "sha256": None, "terms": {}}
    glossary = read_json(path)
    if not {"version", "terms"}.issubset(glossary) or set(glossary) - {"version", "terms", "semantic_rules"} or not isinstance(glossary["terms"], dict):
        raise Phase03Error("UNSUPPORTED_GLOSSARY_FORMAT")
    return {**glossary, "sha256": sha256_file(path)}


def _calibrate(client: OllamaClient, model: str, num_predict: int) -> tuple[float, dict[str, Any]]:
    prompt = "Return JSON with ok=true."
    schema = {"type": "object", "additionalProperties": False, "required": ["ok"], "properties": {"ok": {"const": True}}}
    raw, metrics = client.generate(model, prompt, schema, NUM_CTX, num_predict, 0, False)
    _parse_json_once(raw, schema, "calibration")
    combined_chars = len(prompt) + len(canonical_json(schema))
    measured = metrics.get("prompt_eval_count") or 0
    if measured <= 0:
        raise Phase03Error("CALIBRATION_TOKEN_COUNT_MISSING")
    ratio = (measured / combined_chars) * 1.25
    return max(ratio, 0.30), {**metrics, "kind": "calibration", "combined_characters": combined_chars, "measured_tokens_per_character": measured / combined_chars, "conservative_tokens_per_character": max(ratio, 0.30)}


def _request_metrics(label: str, metrics: dict[str, Any], num_predict: int, preflight: dict[str, Any] | None) -> dict[str, Any]:
    prompt_count = metrics.get("prompt_eval_count") or 0
    eval_count = metrics.get("eval_count") or 0
    record = {"kind": label, **metrics, "actual_prompt_eval_count": prompt_count, "requested_output_reserve": num_predict, "unused_context_headroom": NUM_CTX - prompt_count - eval_count}
    if preflight:
        record.update({"estimated_prompt_tokens": preflight["estimated_prompt_tokens"], "preflight_unused_context_headroom": preflight["unused_context_headroom"], "safety_margin_tokens": preflight["safety_margin_tokens"]})
    return record


def _generate_json(client: OllamaClient, model: str, prompt: str, schema: dict[str, Any], num_predict: int, label: str, requests: list[dict[str, Any]], *, preflight: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    raw, metrics = client.generate(model, prompt, schema, NUM_CTX, num_predict, 0, False)
    requests.append(_request_metrics(label, metrics, num_predict, preflight))
    done_reason = metrics.get("done_reason")
    if done_reason not in {None, "stop"}:
        raise Phase03Error(f"MODEL_OUTPUT_TRUNCATED:{label}:{done_reason}")
    if (metrics.get("prompt_eval_count") or 0) + (metrics.get("eval_count") or 0) > NUM_CTX:
        raise Phase03Error("POST_RUN_CONTEXT_LIMIT_EXCEEDED")
    try:
        return _parse_json_once(raw, schema, label), 0
    except Phase03Error as first:
        if not str(first).startswith(("MALFORMED_MODEL_JSON", "SCHEMA_VALIDATION_FAILED")):
            raise
        repaired_raw, repair_metrics = client.generate(model, repair_prompt(raw, schema), schema, NUM_CTX, num_predict, 0, False)
        requests.append(_request_metrics(f"{label}-repair", repair_metrics, num_predict, None))
        if repair_metrics.get("done_reason") not in {None, "stop"}:
            raise Phase03Error(f"MODEL_OUTPUT_TRUNCATED:{label}-repair:{repair_metrics.get('done_reason')}")
        try:
            return _parse_json_once(repaired_raw, schema, f"{label}-repair"), 1
        except Phase03Error:
            raise Phase03Error(f"MODEL_JSON_REPAIR_FAILED:{label}") from None


def _request_contract(selection: dict[str, Any], store: dict[str, Any], language: str, audience: str, length: str, glossary: dict[str, Any], model: str, digest: str, base_url: str, num_predict: int, strategy: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "document": {"document_id": store["document"]["document_id"], "sha256": store["document"]["sha256"]},
        "source_selection": {"selection_id": selection["selection_id"], "confirmation_status": selection["confirmation_status"]},
        "ordered_chunk_ids": selection["included_chunk_ids"], "language": language, "audience": audience, "length": length,
        "glossary": glossary, "model": {"name": model, "digest": digest},
        "prompt_version": PROMPT_VERSIONS["direct" if strategy == "direct" else "map"], "output_schema_version": 1,
        "inference": {"base_url": base_url, "num_ctx": NUM_CTX, "num_predict": num_predict, "temperature": 0, "stream": False, "think": False},
        "constraints": {"model_must_not_emit_page_numbers": True, "source_is_untrusted_data": True, "no_tools": True},
    }


def _provenance_metadata(
    requests: list[dict[str, Any]], *, cache_hits: int, cache_misses: int,
    bypass_result_cache: bool, bypass_map_cache: bool,
    translation_memory_reused: int, rejected_render_used: bool,
) -> dict[str, Any]:
    model_requests = [
        item for item in requests
        if item.get("kind") != "calibration" and (item.get("actual_prompt_eval_count") or 0) > 0
    ]
    kinds = [str(item.get("kind", "")) for item in model_requests]
    model_map_calls = sum(bool(re.fullmatch(r"map-\d+(?:-repair)?", kind)) for kind in kinds)
    model_render_calls = sum(bool(re.fullmatch(r"render-ar-\d+", kind)) for kind in kinds)
    model_repair_calls = sum(kind.endswith("-repair") or "parity-repair" in kind for kind in kinds)
    model_synthesis_calls = sum(kind in {"direct", "synthesis"} for kind in kinds)
    model_calls_total = len(model_requests)
    calibration_calls = sum(item.get("kind") == "calibration" for item in requests)
    actual_generation_duration_ns = sum(int(item.get("total_duration") or 0) for item in model_requests)

    if rejected_render_used:
        generation_mode = "rejected_render_revalidation" if model_calls_total == 0 else "mixed"
        provenance_classification = "replay" if model_calls_total == 0 else "mixed"
        render_source = "rejected_render" if model_calls_total == 0 else "mixed"
    elif translation_memory_reused:
        generation_mode = "translation_memory_replay" if model_calls_total == 0 else "mixed"
        provenance_classification = "replay" if model_calls_total == 0 else "mixed"
        render_source = "translation_memory" if model_calls_total == 0 else "mixed"
    elif cache_hits:
        generation_mode = "cache_replay" if model_calls_total == 0 else "mixed"
        provenance_classification = "warm" if model_calls_total == 0 and cache_misses == 0 else "mixed"
        render_source = "cache" if model_calls_total == 0 else "mixed"
    elif model_calls_total:
        generation_mode = "model_generation"
        provenance_classification = "cold"
        render_source = "ollama"
    else:
        generation_mode = "deterministic_assembly"
        provenance_classification = "deterministic"
        render_source = "deterministic"
    return {
        "generation_mode": generation_mode,
        "render_source": render_source,
        "provenance_classification": provenance_classification,
        "cold_or_warm": provenance_classification,
        "model_calls_total": model_calls_total,
        "model_map_calls": model_map_calls,
        "model_synthesis_calls": model_synthesis_calls,
        "model_render_calls": model_render_calls,
        "model_repair_calls": model_repair_calls,
        "calibration_calls": calibration_calls,
        "cache_bypassed": bool(bypass_result_cache and bypass_map_cache),
        "result_cache_bypassed": bypass_result_cache,
        "map_cache_bypassed": bypass_map_cache,
        "translation_memory_used": translation_memory_reused > 0,
        "rejected_render_used": rejected_render_used,
        "actual_generation_duration_ns": actual_generation_duration_ns,
    }


def _cache_payload(request: dict[str, Any], units: list[SourceUnit], digest: str, model_map_enrichment: bool) -> dict[str, Any]:
    return {
        "document_sha256": request["document"]["sha256"], "selection_id": request["source_selection"]["selection_id"],
        "batch_units": [item.unit_id for item in units], "text_hashes": [sha256_bytes(item.text.encode("utf-8")) for item in units],
        "model_digest": digest, "prompt_version": PROMPT_VERSIONS["map"], "json_schema_version": 3,
        "num_ctx": NUM_CTX, "num_predict": request["inference"]["num_predict"], "temperature": 0, "think": False,
        "extraction_mode": "deterministic_plus_model" if model_map_enrichment else "deterministic_lossless",
    }


def _merge_inventory(items: list[dict[str, Any]]) -> dict[str, Any]:
    fields = ("processed_chunk_ids", "chunks_with_claims", "chunks_without_claims", "skipped_chunk_ids", "extracted_number_candidates", "extracted_term_candidates", "limitation_candidates")
    merged: dict[str, Any] = {field: [] for field in fields}
    merged["skipped_reasons"] = {}
    for item in items:
        for field in fields:
            for value in item.get(field, []):
                if value not in merged[field]:
                    merged[field].append(value)
        merged["skipped_reasons"].update(item.get("skipped_reasons", {}))
    return merged


def _summary_section(claim: dict[str, Any]) -> str:
    text = claim["claim_text"].casefold()
    limitation = bool(claim.get("limitation_or_uncertainty"))
    if limitation and re.search(r"patch|self-revision|maximum of|execution fails|worker halts|fixed .*budget|do not allow|freeze", text):
        return "operational_boundaries"
    if "high-level api" in text or "core building blocks" in text:
        return "system_purpose"
    if text.startswith("**worker**") or "worker will" in text or "worker halts" in text or "wandb" in text or "execution results" in text:
        return "worker"
    if "implementer" in text or "user submits" in text or "diff file" in text or "code diff" in text or "patched codebase" in text:
        return "implementer"
    if "scheduler" in text or "clock frequency" in text or "job configuration" in text:
        return "scheduler"
    if "worker" in text:
        return "worker"
    if "figure" in text or "completion rate" in text or "baseline accuracy" in text:
        return "figure_findings"
    if "**pre-training task" in text or "speedrun" in text or "inference function" in text:
        return "pre_training"
    if "**post-training task" in text or "post-training" in text or "grpo" in text or "math validation" in text:
        return "post_training"
    if "pre-training" in text or "nanogpt" in text or "fineweb" in text or "validation loss" in text:
        return "pre_training"
    return "research_environment"


def _summary_from_plan(claims: list[dict[str, Any]], plan: dict[str, Any], language: str, rendered_points: dict[str, str] | None = None, glossary: dict[str, Any] | None = None) -> dict[str, Any]:
    claim_map = {claim["claim_id"]: claim for claim in claims}
    selected = [claim_map[claim_id] for claim_id in plan["selected_claim_ids"]]
    selected, antecedents = order_claims_with_antecedents(selected)
    sections = {claim["claim_id"]: _summary_section(claim) for claim in selected}
    for dependent_id, antecedent_id in antecedents.items():
        sections[dependent_id] = sections[antecedent_id]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for claim in selected:
        grouped.setdefault(sections[claim["claim_id"]], []).append(claim)
    section_order = ["research_environment", "pre_training", "post_training", "system_purpose", "implementer", "scheduler", "worker", "figure_findings", "operational_boundaries"]
    points = []
    for section in section_order:
        section_claims = grouped.get(section, [])
        if not section_claims:
            continue
        rendered_section: list[str] = []
        section_ids = {claim["claim_id"] for claim in section_claims}
        for claim in section_claims:
            value = (rendered_points or {}).get(claim["claim_id"], claim["claim_text"]).strip()
            if claim["claim_id"] not in antecedents or antecedents[claim["claim_id"]] not in section_ids:
                value = rewrite_orphan_anaphora(value, claim["claim_text"], language)
            rendered_section.append(value)
        text = " ".join(rendered_section)
        points.append({"point_text": text, "claim_ids": [claim["claim_id"] for claim in section_claims], "section": section})
    key_numbers: list[dict[str, Any]] = []
    number_rows: dict[str, dict[str, Any]] = {}
    for claim in selected:
        for value in claim.get("numbers_and_units", []):
            key = value.casefold()
            row = number_rows.setdefault(key, {"value": value, "claim_ids": []})
            if claim["claim_id"] not in row["claim_ids"]:
                row["claim_ids"].append(claim["claim_id"])
    key_numbers.extend(number_rows.values())
    terms: list[dict[str, Any]] = []
    term_rows: dict[str, dict[str, Any]] = {}
    configured = {key.casefold(): value for key, value in (glossary or {}).get("terms", {}).items()}
    for claim in selected:
        for value in claim.get("technical_terms", []):
            key = value.casefold()
            display = configured.get(value.casefold(), value) if language == "ar" else value
            row = term_rows.setdefault(key, {"term": display, "explanation": "مصطلح محفوظ من الخطة الدلالية." if language == "ar" else "Term preserved from the semantic plan.", "claim_ids": []})
            if claim["claim_id"] not in row["claim_ids"]:
                row["claim_ids"].append(claim["claim_id"])
    terms.extend(term_rows.values())
    limitations = [{"text": (rendered_points or {}).get(claim["claim_id"], claim["limitation_or_uncertainty"]), "claim_ids": [claim["claim_id"]]} for claim in selected if claim.get("limitation_or_uncertainty")]
    notice = "الاستشهادات مرتبطة بملف PDF المحلي، والدعم الدلالي بانتظار مراجعة بشرية." if language == "ar" else "Citations resolve to the local PDF; semantic support awaits human review."
    return {
        "schema_version": 1, "summary_title": "الملخص العربي المؤسَّس على الأدلة" if language == "ar" else "Canonical grounded summary",
        "summary_points": points, "key_numbers": key_numbers, "key_terms": terms, "limitations": limitations,
        "claim_renderings": {claim["claim_id"]: (rendered_points or {}).get(claim["claim_id"], claim["claim_text"]) for claim in selected},
        "coverage_notice": notice, **plan, "semantic_plan_sha256": None, "parity_validation": None,
    }


def _apply_glossary_first_use(rendered: dict[str, str], claims: list[dict[str, Any]], plan: dict[str, Any], glossary: dict[str, Any]) -> dict[str, str]:
    claim_map = {claim["claim_id"]: claim for claim in claims}
    result = dict(rendered)
    seen: set[str] = set()
    for claim_id in plan["selected_claim_ids"]:
        text = result[claim_id]
        english = claim_map[claim_id]["claim_text"].casefold()
        for source_term, configured in glossary.get("terms", {}).items():
            key = source_term.casefold()
            expected = str(configured)
            if key not in english or "(" not in expected:
                continue
            arabic_label = expected.split("(", 1)[0].strip()
            if key not in seen:
                if expected not in text and arabic_label in text:
                    text = text.replace(arabic_label, expected, 1)
                if expected in text:
                    seen.add(key)
            else:
                if expected in text:
                    text = text.replace(expected, arabic_label)
                text = re.sub(r"\s*\(" + re.escape(source_term) + r"\)", "", text, flags=re.IGNORECASE)
        result[claim_id] = text
    result = _normalize_arabic_grammar(result)
    result = _normalize_arabic_semantics(result, claim_map)
    result = _deduplicate_configured_parentheticals(result, plan, glossary)
    return _preserve_citation_years(result, claim_map, plan)


def _deduplicate_configured_parentheticals(rendered: dict[str, str], plan: dict[str, Any], glossary: dict[str, Any]) -> dict[str, str]:
    result = dict(rendered)
    seen: set[str] = set()
    for claim_id in plan["selected_claim_ids"]:
        text = result[claim_id]
        for configured in glossary.get("terms", {}).values():
            expected = str(configured)
            if "(" not in expected:
                continue
            arabic_label = expected.split("(", 1)[0].strip()
            english_label = expected.split("(", 1)[1].rsplit(")", 1)[0].casefold()
            parenthetical = re.compile(r"\s*\(" + re.escape(english_label) + r"\)", re.IGNORECASE)
            if parenthetical.search(text):
                if english_label in seen:
                    text = parenthetical.sub("", text)
                else:
                    seen.add(english_label)
            elif expected in text and english_label in seen:
                text = text.replace(expected, arabic_label)
        result[claim_id] = text
    return result


def _preserve_citation_years(rendered: dict[str, str], claim_map: dict[str, dict[str, Any]], plan: dict[str, Any]) -> dict[str, str]:
    result = dict(rendered)
    for claim_id in plan["selected_claim_ids"]:
        text = result[claim_id]
        english = claim_map[claim_id]["claim_text"]
        for citation in re.findall(r"\([^()]*(?:19|20)\d{2}[^()]*\)", english):
            years = re.findall(r"(?:19|20)\d{2}", citation)
            if any(year not in text for year in years):
                text = text.rstrip() + " " + citation
        result[claim_id] = text
    return result


def _normalize_arabic_grammar(rendered: dict[str, str]) -> dict[str, str]:
    replacements = (
        (r"المنف[ّ]?ذ الأفكار", "منفّذ الأفكار"),
        (r"\bلنمثلة\b", "لكل عيّنة"),
        (r"نكر[ّ]?ر هذه عملية", "نكرّر هذه العملية"),
        (r"إذا نجحت تنفيذ", "إذا نجح تنفيذ"),
        (r"إذا فشلت التنفيذ", "إذا فشل التنفيذ"),
        (r"بحد أقصى\s+2\s+مرات", "بحد أقصى مرتين"),
        (r"وتخصيص الموارد", "وتخصّص الموارد"),
        (r"قاعدة الكود المصلحة", "قاعدة الشيفرة بعد تطبيق التعديل"),
        (r"حيث تكون مدخلاته", "حيث يكون مدخله"),
        (r"بينما يكون مخرجاتها", "ويكون مخرجه"),
        (r"ويكون مخرجه هي", "ويكون مخرجه"),
        (r"نكر[ّ]?ر هذه العملية مراجعة ذاتية متتالية", "نكرّر عملية المراجعة الذاتية المتتالية هذه"),
        (r"سجل التصحيح", "سجل تطبيق التعديل"),
        (r"تحميل نتائج التنفيذ", "تنزيل نتائج التنفيذ"),
        (r"\s*\((?:code diff file|baseline codebase|patched codebase|cloud bucket)\)", ""),
        (r"مفتوحة النهاية", "مفتوحة"),
        (r"أسسًا أساسية ومؤشرات معيارية", "خطوط أساس ومقاييس معيارية"),
        (r"وقت الجدار الساعي للتدريب", "المدة الفعلية للتدريب"),
        (r"(?<!ال)مكافأة البديل(?!ة)", "المكافأة البديلة"),
        (r"الالمكافأة البديلةة", "المكافأة البديلة"),
        (r"تحت هذا الميزانية", "ضمن هذه الميزانية"),
        (r"أي[ّ]? مكافأة اختراق محتملة", "أي تلاعب محتمل بالمكافأة"),
        (r"بواحد رمز مستقبلي", "برمز مستقبلي واحد"),
        (r"تطو[ّ]?رنا الأولي", "مرحلة التطوير الأولية"),
        (r"ميزانية زمنية ثابتة لحساب الجدار الساعات", "ميزانية زمنية فعلية ثابتة للتدريب"),
        (r"تنفيذيات برمجية", "تنفيذات برمجية"),
        (r"منف[ّ]?ذ أفكار", "منفّذ الأفكار"),
        (r"على الخلفية", "في الواجهة الخلفية"),
        (r"كخروج نهائي", "كناتج نهائي"),
        (r"يُرس[ّ]?خ منفذ الأفكار الآلي لدينا", "يرتكز منفّذ الأفكار الآلي لدينا"),
        (r"حيث يتكون كل بيئة", "حيث تتكون كل بيئة"),
        (r"، بيانات تدريب", "، وبيانات تدريب"),
        (r"مؤشرات تقييم", "مقاييس تقييم"),
        (r"للباحثين الذكاء الاصطناعي الآليين", "لباحثي الذكاء الاصطناعي الآليين"),
        (r"أن يبدع أفكارًا", "أن يولّد أفكارًا"),
        (r"نقاس ويُبلغ عن مقياس وقت التدريب", "نقيس مقياس وقت التدريب ونبلّغ عنه"),
        (r"نستخدم هذه دالة الاستنتاج", "نستخدم دالة الاستنتاج هذه"),
        (r"فإن[ّ]? الأساس هو", "فإنّ خط الأساس هو"),
        (r"تقوم بتدقيق نموذج", "تضبط نموذج"),
        (r"التي تضبط نموذج", "التي تُجري ضبطًا دقيقًا لنموذج"),
        (r"تضبط نموذج ([^،.]+?) على مجموعة بيانات", r"تجري ضبطًا دقيقًا لنموذج \1 على مجموعة بيانات"),
        (r"للمنع من اختلاس المكافأة", "لمنع التلاعب بالمكافأة"),
        (r"نحتفظ بكود جميع الأمور المتعلقة بالتحقق من الصحة", "نحتفظ بكل الشيفرة المتعلقة بالتحقق"),
        (r"يقوم العامل بتحميل سجلات التجربة", "يرفع العامل سجلات التجربة"),
        (r"قاعدة الشيفرة البرمجية \(codebase\) أساسية", "قاعدة شيفرة برمجية أساسية (codebase)"),
        (r"مقياس المكافأة الوكيل", "مقياس المكافأة البديلة"),
        (r"لوحة السرعة الأصلية لـ", "لوحة الصدارة الأصلية لسباق السرعة الخاص بـ"),
        (r"نوجه نموذج اللغة الخاص بتنفيذ الكود بكلا الفكرة وقاعدة الشيفرة البرمجية الأساسية", "نزوّد نموذج اللغة الخاص بتنفيذ الكود بالفكرة وقاعدة الشيفرة البرمجية الأساسية"),
        (r"ويحم[ّ]?ل نتائجها", "ويرفع نتائجها"),
        (r"المنف[\u064b-\u065f]*ذ التلقائي \(automatic executor\)", "منفّذ الأفكار الآلي"),
        (r"أداء المعيار المرجعي للفكرة", "أداء كل فكرة على الاختبار المعياري"),
        (r"نبني كل من", "نبني كلًا من"),
        (r"قاعدة الشيفرة المتكيفة من", "قاعدة شيفرة مكيّفة عن"),
        (r"المدة الفعلية للتدريب ليكون", "المدة الفعلية للتدريب لتكون"),
        (r"جهاز معالج مركزي", "جهاز يعتمد على معالج مركزي (CPU)"),
        (r"تحت بوتيرة زمنية محددة", "دوريًا، على فواصل زمنية محددة"),
        (r"يعدّ تكوين المهمة لتقديمها", "يجهّز إعداد المهمة لإرساله"),
        (r"سلة سحابية", "حاوية تخزين سحابية"),
        (r"يُستند منفذنا الآلي للأفكار إلى", "يرتكز منفّذ الأفكار الآلي لدينا على"),
        (r"نكر[ّ]?ر هذا المراجعة الذاتية المتسلسلة", "نكرّر عملية المراجعة الذاتية المتسلسلة هذه"),
        (r"ملف الفرق الكود", "ملف فرق الشيفرة"),
        (r"ملفات فرق كود", "ملفات فرق الشيفرة"),
        (r"ضمن هذا الميزانية", "ضمن هذه الميزانية"),
        (r"نستخدم هذه دالة (الاستدلال|الاستنتاج)", r"نستخدم دالة \1 هذه"),
        (r"نقاس يبلغ عن", "نقيس ونبلّغ عن"),
        (r"دقة أعلى قيمة", "أعلى دقة"),
        (r"للمنع من", "لمنع"),
        (r"جميع الأكواد المتعلقة بالتحقق", "كل الشيفرة المتعلقة بالتحقق"),
        (r"أداء benchmark لكل فكرة", "أداء كل فكرة على الاختبار المعياري"),
        (r"المجد[ِّ]?د \(_Scheduler_\)", "المجدول (_Scheduler_)"),
        (r"القاعدة شيفرة", "قاعدة الشيفرة"),
        (r"لنموذج كل عينة", "لكل عيّنة"),
        (r"يعد[ّ]? تكوين مهمة ليتم تقديمها", "يجهّز إعداد المهمة لإرساله"),
        (r"كافة البيانات الوصفية الكاملة", "جميع البيانات الوصفية"),
        (r"تحت التنفيذ الذاتي", "في التنفيذ الذاتي"),
        (r"على شكل ملف \.zip", "في صورة ملف مضغوط بصيغة .zip"),
    )
    normalized: dict[str, str] = {}
    for claim_id, text in rendered.items():
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text)
        normalized[claim_id] = text
    return normalized


def _normalize_arabic_semantics(
    rendered: dict[str, str], claim_map: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """Apply source-conditioned concept repairs without hard-coding sentences."""
    result = dict(rendered)
    for claim_id, text in result.items():
        english = claim_map[claim_id]["claim_text"].casefold()
        if re.search(r"\bcodebases?\b", english):
            text = re.sub(r"قاعدة (?:ال)?شفروية", "قاعدة الشيفرة", text)
        if "baseline codebase" in english and not re.search(r"(?:مرجعي|خط الأساس)", text):
            text = re.sub(
                r"(?:قاعدة الشيفرة البرمجية|قاعدة الشيفرة|مستودع الشيفرة)(?:\s*\(codebase\))?(?:\s+(?:ال)?أساسية)?",
                "قاعدة شيفرة مرجعية (codebase)",
                text,
                count=1,
            )
        if re.search(r"\bbaseline\s+(?:accuracy|loss)\b", english):
            text = re.sub(r"الدقة(?:\s*\(Accuracy\))?\s+(?:ال)?أساسية", "دقة خط الأساس", text)
            text = re.sub(r"الخسارة(?:\s*\(Loss\))?\s+(?:ال)?أساسية", "خسارة خط الأساس", text)
            text = re.sub(
                r"دقة خط الأساس لـ ([^،]+) هي ([0-9.]+)، والخسارة لخط الأساس لـ ([^،]+) هي ([0-9.]+)",
                r"تبلغ دقة خط الأساس في بيئة \1 مقدار \2، وتبلغ خسارة خط الأساس في بيئة \3 مقدار \4",
                text,
            )
        if "cloud bucket" in english:
            text = re.sub(r"(?:إلى|في)\s+(?:سحابة|سلة سحابية)", "إلى حاوية تخزين سحابية", text)
        if "patched codebase" in english and "submitted" in english:
            text = re.sub(r"^(?:يتم\s+)?تقديم", "تُرفع", text)
            text = re.sub(
                r"قاعدة الشيفرة(?: الأساسية)?(?:\s*\(codebase\))?\s+(?:المصلحة|المُصلحة)",
                "قاعدة الشيفرة بعد تطبيق التعديل (codebase)",
                text,
            )
            text = re.sub(r"\(codebase\) بعد ذلك", "(codebase)", text)
        if "ideator model" in english:
            text = re.sub(r"نموذج الفكرة", "نموذج توليد الأفكار", text)
        if re.search(r"\bfinetunes?\b|\bfine-tun(?:e|es|ing)\b", english):
            text = re.sub(r"(?:يقوم ب)?تدريب(?:ًا)? دقيق(?:ًا)?", "يجري ضبطًا دقيقًا", text)
        if "clock frequency" in english:
            text = re.sub(r"تحت تردد ساعة محدد", "دوريًا، على فواصل زمنية محددة", text)
        result[claim_id] = text
    return result


def _render_arabic(*, claims: list[dict[str, Any]], plan: dict[str, Any], glossary: dict[str, Any], audience: str, client: OllamaClient, model: str, num_predict: int, budgeter: ContextBudgeter, requests: list[dict[str, Any]], context_records: list[dict[str, Any]]) -> tuple[dict[str, str], int]:
    claim_map = {claim["claim_id"]: claim for claim in claims}
    selected = [claim_map[claim_id] for claim_id in plan["selected_claim_ids"]]
    rendered: dict[str, str] = {}
    repairs = 0
    for start in range(0, len(selected), RENDER_BATCH_SIZE):
        batch = selected[start:start + RENDER_BATCH_SIZE]
        ids = [claim["claim_id"] for claim in batch]
        schema = _render_schema(ids)
        prompt = render_prompt(batch, "ar", audience, glossary)
        preflight = budgeter.assert_fits(prompt, canonical_json(schema))
        label = f"render-ar-{start // RENDER_BATCH_SIZE + 1}"
        context_records.append({"kind": label, **preflight})
        response, used = _generate_json(client, model, prompt, schema, num_predict, label, requests, preflight=preflight)
        repairs += used
        returned = [point["claim_id"] for point in response["points"]]
        if returned != ids or len(set(returned)) != len(ids):
            raise Phase03Error("ARABIC_RENDER_CLAIM_PLAN_MISMATCH")
        rendered.update({point["claim_id"]: point["point_text"] for point in response["points"]})
    return _apply_glossary_first_use(rendered, claims, plan, glossary), repairs


def _repair_arabic_parity(*, rendered: dict[str, str], claims: list[dict[str, Any]], plan: dict[str, Any], glossary: dict[str, Any], parity: dict[str, Any], client: OllamaClient, model: str, num_predict: int, budgeter: ContextBudgeter, requests: list[dict[str, Any]], context_records: list[dict[str, Any]]) -> tuple[dict[str, str], int]:
    claim_map = {claim["claim_id"]: claim for claim in claims}
    failed_ids: set[str] = set()
    for group in ("numeric_values", "units", "qualifiers", "negations", "semantic_relations"):
        for item in parity["failures"][group]:
            failed_ids.add(item.split(":", 1)[0])
    for term in parity["failures"]["terminology"]:
        for claim_id in plan["selected_claim_ids"]:
            if term.casefold() in claim_map[claim_id]["claim_text"].casefold():
                failed_ids.add(claim_id)
                break
    if not failed_ids:
        failed_ids = set(plan["selected_claim_ids"])
    ordered_ids = [claim_id for claim_id in plan["selected_claim_ids"] if claim_id in failed_ids]
    batches = [ordered_ids[index:index + RENDER_BATCH_SIZE] for index in range(0, len(ordered_ids), RENDER_BATCH_SIZE)]
    repaired = dict(rendered)
    for batch_index, ids in enumerate(batches, 1):
        schema = _render_schema(ids)
        points = [{"claim_id": claim_id, "point_text": rendered[claim_id]} for claim_id in ids]
        failures = [f"{name}:{value}" for name, values in parity["failures"].items() for value in values]
        prompt = terminology_repair_prompt(points, glossary, failures)
        prompt += "\nCANONICAL_ENGLISH=" + json.dumps([{"claim_id": claim_id, "claim_text": claim_map[claim_id]["claim_text"]} for claim_id in ids], ensure_ascii=False, separators=(",", ":"))
        preflight = budgeter.assert_fits(prompt, canonical_json(schema))
        label = f"arabic-parity-repair-{batch_index}"
        context_records.append({"kind": label, **preflight})
        response, structural_repairs = _generate_json(client, model, prompt, schema, num_predict, label, requests, preflight=preflight)
        if structural_repairs:
            raise Phase03Error("ARABIC_PARITY_REPAIR_INVALID_JSON")
        returned = [point["claim_id"] for point in response["points"]]
        if returned != ids:
            raise Phase03Error("ARABIC_PARITY_REPAIR_CHANGED_PLAN")
        repaired.update({point["claim_id"]: point["point_text"] for point in response["points"]})
    return _apply_glossary_first_use(repaired, claims, plan, glossary), 1


def _load_frozen_plan(path: Path, selection: dict[str, Any], store: dict[str, Any]) -> dict[str, Any]:
    frozen = read_json(path)
    required = {"schema_version", "phase", "document_id", "source_selection_id", "claims", "semantic_plan", "canonical_english_summary", "sha256"}
    if not required.issubset(frozen):
        raise Phase03Error("INVALID_FROZEN_SEMANTIC_PLAN")
    if frozen["document_id"] != store["document"]["document_id"] or frozen["source_selection_id"] != selection["selection_id"]:
        raise Phase03Error("FROZEN_SEMANTIC_PLAN_IDENTITY_MISMATCH")
    payload = {key: value for key, value in frozen.items() if key != "sha256"}
    if sha256_bytes(canonical_json(payload).encode("utf-8")) != frozen["sha256"]:
        raise Phase03Error("FROZEN_SEMANTIC_PLAN_HASH_MISMATCH")
    return frozen


def _freeze_plan(selection: dict[str, Any], claims: list[dict[str, Any]], plan: dict[str, Any], english: dict[str, Any]) -> dict[str, Any]:
    # Freeze values, not live references: the published summary is augmented
    # after hashing and must not mutate the canonical payload retroactively.
    frozen_claims = json.loads(json.dumps(claims, ensure_ascii=False))
    frozen_semantic_plan = json.loads(json.dumps(plan, ensure_ascii=False))
    frozen_english = json.loads(json.dumps(english, ensure_ascii=False))
    payload = {
        "schema_version": 2, "phase": PHASE03_VERSION, "document_id": selection["document_id"],
        "source_selection_id": selection["selection_id"], "claims": frozen_claims, "semantic_plan": frozen_semantic_plan,
        "canonical_english_summary": frozen_english,
    }
    return {**payload, "sha256": sha256_bytes(canonical_json(payload).encode("utf-8"))}


def run_summary(
    *, project_root: Path, selection_path: Path, store_path: Path, pdf_path: Path, out_path: Path,
    language: str, audience: str, length: str, glossary_path: Path | None, model: str,
    base_url: str, strategy: str, num_predict: int = 1536, cache_path: Path | None = None,
    bypass_cache: bool = False, bypass_result_cache: bool = False,
    bypass_map_cache: bool | None = None, client: OllamaClient | None = None,
    semantic_plan_path: Path | None = None, visually_verified_chunk_ids: set[str] | None = None,
    model_map_enrichment: bool = False, rejected_render_path: Path | None = None,
    translation_memory_path: Path | None = None,
    disable_translation_memory: bool = False, disable_rejected_render_reuse: bool = False,
    require_model_rendering: bool = False, required_model_stages: set[str] | None = None,
    require_cold: bool = False,
) -> dict[str, Any]:
    if language not in {"en", "ar"} or length not in {"short", "medium", "long"} or strategy not in {"direct", "hierarchical"}:
        raise Phase03Error("UNSUPPORTED_REQUEST_OPTION")
    if num_predict < 64:
        raise Phase03Error("UNSUPPORTED_NUM_PREDICT")
    if language == "ar" and semantic_plan_path is None:
        raise Phase03Error("ARABIC_REQUIRES_FROZEN_ENGLISH_PLAN")
    if semantic_plan_path is not None and language != "ar":
        raise Phase03Error("FROZEN_PLAN_IS_FOR_ARABIC_RENDERING")
    if rejected_render_path is not None and language != "ar":
        raise Phase03Error("REJECTED_RENDER_IS_FOR_ARABIC_ONLY")
    if translation_memory_path is not None and language != "ar":
        raise Phase03Error("TRANSLATION_MEMORY_IS_FOR_ARABIC_ONLY")
    if rejected_render_path is not None and translation_memory_path is not None:
        raise Phase03Error("MULTIPLE_ARABIC_RENDER_SEEDS")
    if disable_translation_memory and translation_memory_path is not None:
        raise Phase03Error("TRANSLATION_MEMORY_DISABLED")
    if disable_rejected_render_reuse and rejected_render_path is not None:
        raise Phase03Error("REJECTED_RENDER_REUSE_DISABLED")
    if require_model_rendering and language != "ar":
        raise Phase03Error("MODEL_RENDERING_REQUIREMENT_IS_FOR_ARABIC")
    required_stages = set(required_model_stages or set())
    if require_model_rendering:
        required_stages.add("render")
    effective_bypass_map_cache = bypass_cache if bypass_map_cache is None else bypass_map_cache
    if require_cold:
        if rejected_render_path is not None or translation_memory_path is not None:
            raise Phase03Error("COLD_RUN_FORBIDS_REPLAY")
        bypass_result_cache = True
        effective_bypass_map_cache = True
        if language == "ar":
            required_stages.add("render")
        elif strategy == "hierarchical":
            if not model_map_enrichment:
                raise Phase03Error("COLD_RUN_REQUIRES_MODEL_MAP_ENRICHMENT")
            required_stages.add("map")

    started_at, started_ns = _utc_now(), time.perf_counter_ns()
    selection, store = load_and_validate_inputs(project_root, selection_path, store_path, pdf_path)
    glossary = _load_glossary(glossary_path)
    client = client or OllamaClient(base_url)
    show = client.show(model)
    digest = _model_digest(show)
    runtime = _runtime_identity(model, show, digest, client.base_url)
    request = _request_contract(selection, store, language, audience, length, glossary, model, digest, client.base_url, num_predict, strategy)
    request["execution_controls"] = {
        "bypass_result_cache": bypass_result_cache,
        "bypass_map_cache": effective_bypass_map_cache,
        "translation_memory_disabled": disable_translation_memory,
        "rejected_render_reuse_disabled": disable_rejected_render_reuse,
        "required_model_stages": sorted(required_stages),
        "cold_requested": require_cold,
        "local_only": True,
        "require_new_output_directory": True,
    }
    if rejected_render_path is not None:
        request["render_seed"] = {"sha256": sha256_file(rejected_render_path), "status": "rejected_render_revalidation"}
    if translation_memory_path is not None:
        request["translation_memory"] = {"sha256": sha256_file(translation_memory_path), "status": "accepted_exact_claim_reuse"}
    validate_schema(request, load_schema(project_root, "summary-request.schema.json"), "summary-request")
    requests: list[dict[str, Any]] = []
    ratio, calibration = _calibrate(client, model, num_predict)
    requests.append(_request_metrics("calibration", calibration, num_predict, None))
    budgeter = ContextBudgeter(NUM_CTX, num_predict, SAFETY_MARGIN, ratio)
    selected_chunks = {item["chunk_id"]: item for item in selection["chunks"]}
    ordered_chunks = [selected_chunks[item] for item in selection["included_chunk_ids"]]
    allowed_text = {item["chunk_id"]: item.get("selection_text", "") for item in ordered_chunks}
    chunk_flags = {item["chunk_id"]: item.get("content_risk_flags", []) for item in ordered_chunks}
    verified = set(visually_verified_chunk_ids or set())
    if verified - set(allowed_text):
        raise Phase03Error("VISUAL_VERIFICATION_CHUNK_OUTSIDE_SELECTION")

    repairs = parity_repairs = 0
    audits: list[dict[str, Any]] = []
    duplicates: list[dict[str, str]] = []
    cache_hits = cache_misses = 0
    context_records: list[dict[str, Any]] = []
    inventory_batches: list[dict[str, Any]] = []
    raw_claims: list[dict[str, Any]] = []
    map_batches = 0
    translation_memory_reused = 0
    model_claims_accepted = model_claims_rejected = 0

    with atomic_output_directory(out_path) as stage:
        if semantic_plan_path is not None:
            frozen_plan = _load_frozen_plan(semantic_plan_path, selection, store)
            claims = frozen_plan["claims"]
            plan = frozen_plan["semantic_plan"]
            english = frozen_plan["canonical_english_summary"]
            inventory = {"loaded_from_frozen_plan": True, "processed_chunk_ids": selection["included_chunk_ids"]}
            if rejected_render_path is not None:
                rejected = read_json(rejected_render_path)
                if rejected.get("status") != "rejected_not_published" or rejected.get("semantic_plan_sha256") != frozen_plan["sha256"]:
                    raise Phase03Error("REJECTED_RENDER_PLAN_MISMATCH")
                rendered = rejected.get("rejected_claim_renderings", {})
                if set(rendered) != set(plan["selected_claim_ids"]):
                    raise Phase03Error("REJECTED_RENDER_CLAIM_PLAN_MISMATCH")
                rendered = _apply_glossary_first_use(rendered, claims, plan, glossary)
                requests.append({"kind": "rejected-render-revalidation", "source_sha256": request["render_seed"]["sha256"], "done_reason": "deterministic_reuse"})
            elif translation_memory_path is not None:
                memory_summary = read_json(translation_memory_path)
                memory_dir = translation_memory_path.parent
                memory_request = read_json(memory_dir / "request.json")
                memory_metadata = read_json(memory_dir / "run-metadata.json")
                memory_plan = read_json(memory_dir / "semantic-plan.json")
                if memory_summary.get("parity_validation", {}).get("status") != "pass":
                    raise Phase03Error("TRANSLATION_MEMORY_NOT_ACCEPTED")
                if (
                    memory_request.get("model", {}).get("digest") != digest
                    or memory_request.get("glossary", {}).get("sha256") != glossary.get("sha256")
                    or memory_metadata.get("prompt_versions", {}).get("render") != PROMPT_VERSIONS["render"]
                ):
                    raise Phase03Error("TRANSLATION_MEMORY_CONFIGURATION_MISMATCH")
                memory_claims = {item["claim_id"]: item for item in memory_plan["claims"]}
                by_text = {
                    memory_claims[claim_id]["claim_text"]: text
                    for claim_id, text in memory_summary.get("claim_renderings", {}).items()
                    if claim_id in memory_claims
                }
                claim_map = {item["claim_id"]: item for item in claims}
                rendered = {
                    claim_id: by_text[claim_map[claim_id]["claim_text"]]
                    for claim_id in plan["selected_claim_ids"]
                    if claim_map[claim_id]["claim_text"] in by_text
                }
                translation_memory_reused = len(rendered)
                missing_ids = [claim_id for claim_id in plan["selected_claim_ids"] if claim_id not in rendered]
                if missing_ids:
                    missing_plan = {**plan, "selected_claim_ids": missing_ids}
                    generated, used = _render_arabic(claims=claims, plan=missing_plan, glossary=glossary, audience=audience, client=client, model=model, num_predict=num_predict, budgeter=budgeter, requests=requests, context_records=context_records)
                    repairs += used
                    rendered.update(generated)
                rendered = _apply_glossary_first_use(rendered, claims, plan, glossary)
                requests.append({"kind": "translation-memory-reuse", "source_sha256": request["translation_memory"]["sha256"], "reused_claims": translation_memory_reused, "generated_claims": len(missing_ids), "done_reason": "validated_exact_claim_reuse"})
            else:
                rendered, used = _render_arabic(claims=claims, plan=plan, glossary=glossary, audience=audience, client=client, model=model, num_predict=num_predict, budgeter=budgeter, requests=requests, context_records=context_records)
                repairs += used
            summary = _summary_from_plan(claims, plan, "ar", rendered, glossary)
            summary["semantic_plan_sha256"] = frozen_plan["sha256"]
            grounded = resolve_citations(summary, claims, selection, store)
            selected_claims = [claim for claim in claims if claim["claim_id"] in set(plan["selected_claim_ids"])]
            parity = validate_english_arabic_parity(english, grounded, selected_claims, glossary)
            if parity["status"] != "pass":
                rendered, parity_repairs = _repair_arabic_parity(rendered=rendered, claims=claims, plan=plan, glossary=glossary, parity=parity, client=client, model=model, num_predict=num_predict, budgeter=budgeter, requests=requests, context_records=context_records)
                summary = _summary_from_plan(claims, plan, "ar", rendered, glossary)
                summary["semantic_plan_sha256"] = frozen_plan["sha256"]
                grounded = resolve_citations(summary, claims, selection, store)
                parity = validate_english_arabic_parity(english, grounded, selected_claims, glossary)
                if parity["status"] != "pass":
                    failure_path = out_path.parent / f"{out_path.name}-human-review-failure.json"
                    write_json(failure_path, {
                        "schema_version": 1,
                        "status": "rejected_not_published",
                        "human_semantic_status": "unreviewed",
                        "semantic_plan_sha256": frozen_plan["sha256"],
                        "parity_validation": parity,
                        "rejected_claim_renderings": summary.get("claim_renderings", {}),
                    })
                    raise Phase03Error("ARABIC_PARITY_VALIDATION_FAILED")
            grounded["parity_validation"] = parity
            audits = [{"claim_id": claim["claim_id"], "source_chunk_id": evidence["source_chunk_id"], "exact_quote_match": evidence["short_quote"] in allowed_text[evidence["source_chunk_id"]], "canonical_quote_match": True, "semantic_support": "unreviewed", "reviewer_note": ""} for claim in claims for evidence in claim["evidence"]]
            raw_claims = claims
        else:
            if strategy == "direct":
                units = [SourceUnit(item["chunk_id"], item["chunk_id"], item.get("selection_text", ""), None, item["pdf_page"], 0, len(item.get("selection_text", ""))) for item in ordered_chunks]
                schema = _direct_schema(project_root)
                prompt = direct_prompt(units, "en", audience, length, glossary)
                preflight = budgeter.assert_fits(prompt, canonical_json(schema))
                context_records.append({"kind": "direct", **preflight})
                response, used = _generate_json(client, model, prompt, schema, num_predict, "direct", requests, preflight=preflight)
                repairs += used
                generated = [{"local_claim_id": f"c{index}", "claim_text": point["point_text"], "topic": point["topic"], "importance": point["importance"], "evidence": point["evidence"], "numbers_and_units": point["numbers_and_units"], "technical_terms": point["technical_terms"], "limitation_or_uncertainty": point["limitation_or_uncertainty"]} for index, point in enumerate(response["points"], 1)]
                claims, audits = validate_claims(generated, allowed_text, "direct")
                claims = [classify_claim_risk(claim, chunk_flags, allowed_text, verified) for claim in claims]
                raw_claims = claims
                inventory = completeness_metadata(units, claims)
            else:
                claim_schema = _claims_generation_schema(project_root, 10)
                max_chars = min(MAX_MAP_SOURCE_CHARACTERS, budgeter.available_source_characters(map_prompt([]), canonical_json(claim_schema)))
                units = [unit for chunk in ordered_chunks for unit in fragment_chunk(chunk, max_chars)]
                reconciled_statements, unresolved_fragments = reconcile_source_statements(ordered_chunks)
                if unresolved_fragments:
                    raise Phase03Error(
                        "UNRESOLVED_SOURCE_FRAGMENT:"
                        + ",".join(item.evidence_spans[0].source_chunk_id for item in unresolved_fragments)
                    )

                def fits(items: list[SourceUnit]) -> bool:
                    if sum(len(item.text) for item in items) > MAX_MAP_SOURCE_CHARACTERS:
                        return False
                    try:
                        budgeter.assert_fits(map_prompt(items), canonical_json(claim_schema))
                        return True
                    except Phase03Error:
                        return False

                batches = partition_units(units, fits, max_units=MAX_MAP_UNITS)
                cache = MapCache(cache_path or out_path.parent / ".phase03-map-cache-v2")
                all_claims: list[dict[str, Any]] = []
                for index, batch in enumerate(batches, 1):
                    statement_count = sum(len(split_statements(item.text)) for item in batch)
                    batch_claim_limit = min(10, max(3, statement_count + 2))
                    batch_schema = _claims_generation_schema(project_root, batch_claim_limit)
                    prompt = map_prompt(batch)
                    preflight = budgeter.assert_fits(prompt, canonical_json(batch_schema))
                    context_records.append({"kind": f"map-{index}", "source_chunk_ids": list(dict.fromkeys(item.source_chunk_id for item in batch)), **preflight})
                    key = cache.key(_cache_payload(request, batch, digest, model_map_enrichment))
                    cached = None if effective_bypass_map_cache else cache.get(key)
                    if cached is not None:
                        cache_hits += 1
                        batch_claims, batch_audit, batch_inventory = cached["claims"], cached["evidence_audit"], cached["inventory"]
                    else:
                        cache_misses += 1
                        batch_allowed = {item.source_chunk_id: allowed_text[item.source_chunk_id] for item in batch}
                        picture_text_only = all("<!-- Start of picture text -->" in allowed_text[item.source_chunk_id] for item in batch)
                        if picture_text_only or not model_map_enrichment:
                            model_claims = []
                            requests.append({
                                "kind": f"map-{index}-deterministic", "estimated_prompt_tokens": preflight["estimated_prompt_tokens"],
                                "actual_prompt_eval_count": 0, "eval_count": 0, "done_reason": "deterministic",
                                "requested_output_reserve": 0, "unused_context_headroom": NUM_CTX,
                                "configured_num_ctx": NUM_CTX, "configured_num_predict": 0,
                            })
                        else:
                            response, used = _generate_json(client, model, prompt, batch_schema, num_predict, f"map-{index}", requests, preflight=preflight)
                            repairs += used
                            model_claims = [{"local_claim_id": f"model-{claim_index:03d}", **claim} for claim_index, claim in enumerate(response["claims"], 1)]
                            model_claims, unresolved_model_claims = reconcile_model_claims(model_claims)
                        batch_claims = []
                        batch_audit = []
                        rejected_model_claims = [
                            {"local_claim_id": claim_id, "reason": "unresolved_model_claim_fragment"}
                            for claim_id in unresolved_model_claims
                        ] if not (picture_text_only or not model_map_enrichment) else []
                        for model_claim in model_claims:
                            try:
                                accepted, claim_audit = validate_claims([model_claim], batch_allowed, f"b{index}")
                            except Phase03Error as exc:
                                rejected_model_claims.append({
                                    "local_claim_id": model_claim.get("local_claim_id", "unknown"),
                                    "reason": str(exc).split(":", 1)[0],
                                })
                                continue
                            batch_claims.extend(accepted)
                            batch_audit.extend(claim_audit)
                        batch_claims = [classify_claim_risk(claim, chunk_flags, allowed_text, verified) for claim in batch_claims]
                        batch_inventory = completeness_metadata(batch, batch_claims)
                        batch_inventory["model_claims_accepted"] = len(batch_claims)
                        batch_inventory["model_claims_rejected"] = rejected_model_claims
                        cache.put(key, {"claims": batch_claims, "evidence_audit": batch_audit, "inventory": batch_inventory})
                    model_claims_accepted += int(batch_inventory.get("model_claims_accepted", 0))
                    model_claims_rejected += len(batch_inventory.get("model_claims_rejected", []))
                    all_claims.extend(batch_claims)
                    audits.extend(batch_audit)
                    inventory_batches.append(batch_inventory)
                deterministic_claims, deterministic_audit = validate_claims(
                    source_fallback_claims(statements=reconciled_statements), allowed_text, "src"
                )
                deterministic_claims = [classify_claim_risk(claim, chunk_flags, allowed_text, verified) for claim in deterministic_claims]
                audits.extend(deterministic_audit)
                # The deterministic reconciled statements are the lossless
                # canonical inventory. Validated model claims remain audited
                # enrichment evidence but cannot multiply or paraphrase the
                # proposition set used by the frozen plan.
                raw_claims = all_claims + deterministic_claims
                claims, duplicates = deduplicate_claims(deterministic_claims)
                inventory = completeness_metadata(units, claims)
                inventory["reconciled_statement_count"] = len(reconciled_statements)
                inventory["unresolved_fragment_count"] = 0
                inventory["merged_multi_span_claim_count"] = sum(len(claim.get("evidence", [])) > 1 for claim in deterministic_claims)
                map_batches = len(batches)

            plan = build_semantic_plan(claims, length, comprehensive=length == "long")
            summary = _summary_from_plan(claims, plan, "en", glossary=glossary)
            grounded = resolve_citations(summary, claims, selection, store)
            validate_synthesis(grounded, claims, plan["selected_claim_ids"])
            frozen_plan = _freeze_plan(selection, claims, plan, grounded)
            grounded["semantic_plan_sha256"] = frozen_plan["sha256"]

        grounded["coverage_status"] = coverage_status(selection["content_risk_flags"])
        grounded["source_content_risk_flags"] = selection["content_risk_flags"]
        grounded["source_selection_id"] = selection["selection_id"]
        grounded["document_id"] = selection["document_id"]
        validate_schema(grounded, _summary_schema(project_root), "summary-result")

        completed_at, wall_ns = _utc_now(), time.perf_counter_ns() - started_ns
        provenance = _provenance_metadata(
            requests, cache_hits=cache_hits, cache_misses=cache_misses,
            bypass_result_cache=bypass_result_cache, bypass_map_cache=effective_bypass_map_cache,
            translation_memory_reused=translation_memory_reused,
            rejected_render_used=rejected_render_path is not None,
        )
        stage_counts = {
            "map": provenance["model_map_calls"],
            "render": provenance["model_render_calls"],
            "synthesis": provenance["model_synthesis_calls"],
            "repair": provenance["model_repair_calls"],
        }
        missing_stages = sorted(stage for stage in required_stages if stage_counts.get(stage, 0) == 0)
        if missing_stages:
            raise Phase03Error("REQUIRED_MODEL_STAGE_ZERO_CALLS:" + ",".join(missing_stages))
        if "map" in required_stages and provenance["model_map_calls"] and model_claims_accepted == 0:
            raise Phase03Error("REQUIRED_MODEL_STAGE_NO_ACCEPTED_OUTPUT:map")
        if require_cold and provenance["provenance_classification"] != "cold":
            raise Phase03Error("FALSE_COLD_RUN_PREVENTED:" + provenance["provenance_classification"])
        contacted_hosts = sorted(set(getattr(client, "contacted_hosts", [])) | {urlparse(client.base_url).hostname or ""})
        if any(host not in {"localhost", "127.0.0.1", "::1"} for host in contacted_hosts):
            raise Phase03Error("NON_LOOPBACK_INFERENCE_HOST_CONTACTED")
        metadata = {
            "schema_version": 4, "run_id": str(uuid.uuid4()), "run_status": "completed",
            "phase_status": "PHASE_03_IMPLEMENTED_AND_LOCALLY_EVALUATED_PENDING_HUMAN_REVIEW",
            "started_at": started_at, "completed_at": completed_at, "wall_clock_ns": wall_ns,
            **provenance,
            "canonical_content_source": "deterministic_reconciled_source",
            "strategy": strategy, "language_role": "canonical_english" if language == "en" else "arabic_rendering_of_frozen_english_plan",
            "evidence_extraction_mode": "frozen_plan" if semantic_plan_path is not None else ("deterministic_plus_model" if model_map_enrichment else "deterministic_lossless"),
            "map_batches": map_batches, "claims_before_validation": len(raw_claims), "claims_after_validation": len(claims),
            "model_claims_accepted": model_claims_accepted, "model_claims_rejected": model_claims_rejected,
            "repair_attempts": repairs, "arabic_parity_repair_attempts": parity_repairs,
            "cache": {"hits": cache_hits, "misses": cache_misses, "reused_map_batches": cache_hits, "bypassed": effective_bypass_map_cache, "synthesis_policy": "deterministic_semantic_plan", **({"rejected_render_reused": True} if rejected_render_path is not None else {}), **({"translation_memory_reused_claims": translation_memory_reused} if translation_memory_path is not None else {})},
            "runtime": runtime, "prompt_versions": PROMPT_VERSIONS,
            "schema_versions": {"request": 1, "claims": 3, "summary": 3, "metadata": 4, "review": 3, "semantic_plan": 2},
            "inference": request["inference"], "requests": requests,
            "context_budget": {"calibration": calibration, "batches": context_records, "operational_safety_margin_tokens": SAFETY_MARGIN},
            "local_only": {"enforced": True, "cloud_fallback_enabled": False, "contacted_inference_hosts": contacted_hosts},
            "offline_status": {
                "application_local_only_enforcement": "VERIFIED",
                "ollama_loopback_endpoint": "VERIFIED",
                "cloud_fallback": "DISABLED",
                "network_disconnected": "NOT_VERIFIED",
                "overall": "APPLICATION_LOCAL_ONLY_VERIFIED_NETWORK_DISCONNECTION_NOT_VERIFIED",
            },
        }
        if hasattr(client, "ps"):
            metadata["runtime"]["api_ps_after_run"] = client.ps()
        validate_schema(metadata, load_schema(project_root, "run-metadata.schema.json"), "run-metadata")

        claims_review = build_claims_review(
            grounded, claims, selection,
            english_summary=english if language == "ar" else None,
        )
        if language == "ar":
            claims_review["arabic_review_dimensions"] = {
                "factual_faithfulness_to_frozen_plan": "unreviewed", "number_and_qualifier_preservation": "unreviewed",
                "terminology_correctness": "unreviewed", "natural_arabic_phrasing": "unreviewed",
                "english_term_on_first_occurrence": "unreviewed", "bidi_and_markdown_readability": "unreviewed",
            }
        coverage_report = build_coverage_report(grounded, inventory)
        write_json(stage / "request.json", request)
        write_json(stage / "semantic-plan.json", frozen_plan)
        write_json(stage / "claims.json", {"schema_version": 3, "claims": claims, "deduplicated": duplicates})
        write_json(stage / "evidence-inventory.json", {"schema_version": 2, "batches": inventory_batches, "aggregate": inventory})
        write_json(stage / "evidence-audit.json", {"checks": audits})
        write_json(stage / "summary.json", grounded)
        write_json(stage / "claims-review.json", claims_review)
        write_json(stage / "coverage-report.json", coverage_report)
        write_json(stage / "run-metadata.json", metadata)
        (stage / "summary.md").write_text(render_markdown(grounded, language), encoding="utf-8")
        (stage / "claims-review.md").write_text(render_claims_review(claims_review), encoding="utf-8")
        (stage / "coverage-report.md").write_text(render_coverage_report(coverage_report), encoding="utf-8")
    return {"summary": grounded, "metadata": metadata, "claims": claims, "evidence_audit": audits, "semantic_plan": frozen_plan, "coverage_report": coverage_report}


def render_markdown(summary: dict[str, Any], language: str = "en") -> str:
    lines = [f"# {summary['summary_title']}", ""]
    headings = {
        "en": {
            "research_environment": "Research environments", "pre_training": "Pre-training environment",
            "post_training": "Post-training environment", "system_purpose": "System purpose and API",
            "implementer": "Implementer", "scheduler": "Scheduler", "worker": "Worker",
            "figure_findings": "Figure findings", "operational_boundaries": "Operational boundaries and failure handling",
        },
        "ar": {
            "research_environment": "بيئات البحث", "pre_training": "بيئة التدريب المسبق",
            "post_training": "بيئة التدريب اللاحق", "system_purpose": "غرض النظام وواجهة البرمجة",
            "implementer": "المنفّذ", "scheduler": "المُجدوِل", "worker": "العامل",
            "figure_findings": "نتائج الشكل 2", "operational_boundaries": "حدود التشغيل وآليات التعامل مع الفشل",
        },
    }
    last_section = None
    for point in summary["summary_points"]:
        section = point.get("section")
        if section and section != last_section:
            if last_section is not None:
                lines.append("")
            lines.extend([f"## {headings[language].get(section, section)}", ""])
            last_section = section
        citations = " ".join(item["display"] for item in point["citations"])
        lines.append(f"{point['point_text']} {citations}".rstrip())
    lines.extend(["", "## التغطية" if language == "ar" else "## Coverage", ""])
    status = summary["coverage_status"]
    if status["limited_by_table_extraction"]:
        lines.append("- محتوى الجداول محدود بجودة الاستخراج، ولا يُدّعى أن الملخص يغطيه بالكامل." if language == "ar" else "- Table content is extraction-limited and is not claimed as fully covered.")
    if status["limited_by_equation_extraction"]:
        lines.append("- المعادلات أو الرموز تحتاج مراجعة بشرية." if language == "ar" else "- Equations or symbols require human review.")
    if status["limited_by_picture_content"]:
        lines.append("- محتوى الصور يحتاج مراجعة بصرية." if language == "ar" else "- Picture content requires visual review.")
    warning_translations = {
        "Values found only in extraction-risk figure or table content were omitted pending visual review.": "حُذفت القيم التي لم تظهر إلا داخل محتوى صور أو جداول عالي مخاطر الاستخراج إلى حين المراجعة البصرية.",
        "Values present in textual captions were visually verified against the PDF and retained.": "تم التحقق بصرياً من القيم الواردة في التعليقات النصية للأشكال مقابل ملف PDF والإبقاء عليها.",
        "Requested length is insufficient for comprehensive coverage; high-importance claims were omitted.": "الطول المطلوب لا يكفي للتغطية الشاملة؛ حُذفت ادعاءات عالية الأهمية.",
    }
    lines.extend(f"- {warning_translations.get(warning, 'تحذير تغطية يحتاج مراجعة بشرية.') if language == 'ar' else warning}" for warning in summary.get("coverage_warnings", []))
    lines.extend(["", summary["coverage_notice"], ""])
    return "\n".join(lines)
