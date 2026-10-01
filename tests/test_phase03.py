from __future__ import annotations

import json
from pathlib import Path

import pytest

from matn_summarization.budget import ContextBudgeter, SourceUnit, fragment_chunk, partition_units
from matn_summarization.cache import MapCache
from matn_summarization.evidence import canonical_text, coverage_status, deduplicate_claims, deterministic_projection, resolve_citations, validate_claims, validate_synthesis
from matn_summarization.io import Phase03Error, atomic_output_directory, load_and_validate_inputs, load_schema, sha256_file, validate_schema
from matn_summarization.ollama import validate_loopback_base_url
from matn_summarization.pipeline import _generate_json, run_summary
from matn_summarization.prompts import glossary_instruction
from evaluate_summary import evaluate


def claim(local="c1", chunk="chk-1111111111111111", quote="Alpha  10 kg"):
    return {"local_claim_id": local, "claim_text": "Alpha is 10 kg.", "topic": "alpha", "importance": "core", "evidence": [{"source_chunk_id": chunk, "short_quote": quote}], "numbers_and_units": ["10 kg"], "technical_terms": ["Alpha"], "limitation_or_uncertainty": None}


def summary(claim_id="b1-c1"):
    return {"schema_version": 1, "summary_title": "Alpha", "summary_points": [{"point_text": "Alpha is 10 kg.", "claim_ids": [claim_id]}], "key_numbers": [{"value": "10 kg", "claim_ids": [claim_id]}], "key_terms": [{"term": "Alpha", "explanation": "A term", "claim_ids": [claim_id]}], "limitations": [], "coverage_notice": "Local PDF evidence; semantic support awaits human review."}


def make_inputs(tmp_path: Path, risk_flags=None):
    root = Path(__file__).resolve().parents[1]
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"local-pdf")
    doc_sha = sha256_file(pdf)
    store_dir = tmp_path / "store"
    source_dir = store_dir / "text" / "structured"
    source_dir.mkdir(parents=True)
    text = "Alpha  10 kg\nBeta sentence."
    (source_dir / "page_0001.md").write_text(text, encoding="utf-8")
    chunk_id = "chk-1111111111111111"
    flags = risk_flags or []
    store = {
        "schema_version": 1, "store_status": "completed",
        "document": {"document_id": f"sha256-{doc_sha}", "sha256": doc_sha, "size_bytes": len(b"local-pdf"), "safe_file_name": "paper.pdf", "pdf_page_count": 1},
        "index_run": {}, "coverage": {}, "outline": {},
        "pages": [{"pdf_page": 1, "page_label": "i", "printed_page": "7", "raw_text_path": "", "structured_text_path": "text/structured/page_0001.md", "chunk_ids": [chunk_id], "content_risk_flags": flags, "warnings": []}],
        "chunks": [{"chunk_id": chunk_id, "order": 0, "pdf_page": 1, "source_type": "structured", "source_text_path": "text/structured/page_0001.md", "start_offset": 0, "end_offset": len(text), "block_kind": "layout_block", "text": text, "content_risk_flags": flags, "warnings": []}],
        "heading_candidates": [], "sections": [], "header_footer_candidates": [], "warnings": []
    }
    store_path = store_dir / "document-store.json"
    store_path.write_text(json.dumps(store), encoding="utf-8")
    selection = {
        "schema_version": 1, "selection_id": "sel-1111111111111111", "document_id": f"sha256-{doc_sha}", "selection_scope": "section-scoped", "requested_selector": {}, "resolved_sections": ["sec-test"], "resolved_pdf_pages": [1], "included_chunk_ids": [chunk_id],
        "chunks": [{"chunk_id": chunk_id, "pdf_page": 1, "original_text": text, "selection_text": text, "content_risk_flags": flags}],
        "citations": [{"chunk_id": chunk_id, "pdf_page": 1}], "excluded_boundary_fragments": [], "excluded_repetitive_header_footer": [], "content_risk_flags": flags, "warnings": [], "confirmation_status": "confirmed"
    }
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    return root, pdf, store_path, selection_path, store, selection


class FakeClient:
    base_url = "http://127.0.0.1:11434"

    def __init__(self, malformed_map=False, fail_synthesis=False):
        self.malformed_map = malformed_map
        self.fail_synthesis = fail_synthesis
        self.calls = []

    def show(self, model):
        return {"capabilities": ["completion", "thinking"], "details": {"digest": "digest-1", "quantization_level": "Q4_K_M"}, "model_info": {"general.architecture": "test", "general.parameter_count": 1}, "parameters": "temperature 1", "template": "{{ .Prompt }}"}

    def generate(self, model, prompt, schema, num_ctx, num_predict, temperature=0, think=False):
        self.calls.append(prompt)
        metrics = {"total_duration": 10, "load_duration": 1, "prompt_eval_count": 100, "prompt_eval_cached_count": 0, "prompt_eval_duration": 2, "eval_count": 10, "eval_duration": 3, "done_reason": "stop", "configured_num_ctx": num_ctx, "configured_num_predict": num_predict}
        if "ok=true" in prompt:
            return '{"ok":true}', metrics
        if "Repair only" in prompt:
            return json.dumps({"schema_version": 1, "claims": [claim()]}), metrics
        if "ACCEPTED_CLAIMS=" in prompt:
            if self.fail_synthesis:
                raise Phase03Error("SYNTHESIS_FAILURE")
            return json.dumps(summary()), metrics
        map_claim = {key: value for key, value in claim().items() if key != "local_claim_id"}
        return ("{" if self.malformed_map else json.dumps({"schema_version": 1, "claims": [map_claim]})), metrics


class QueueClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def generate(self, *args, **kwargs):
        raw = self.responses.pop(0)
        return raw, {"prompt_eval_count": 1, "eval_count": 1, "done_reason": "stop"}


def test_valid_structured_response_and_claim_validation():
    accepted, audit = validate_claims([claim()], {"chk-1111111111111111": "Alpha  10 kg"}, "b1")
    assert accepted[0]["claim_id"] == "b1-c1"
    assert audit[0]["exact_quote_match"] is True


def test_malformed_json_allows_one_repair():
    requests = []
    schema = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
    value, repairs = _generate_json(QueueClient(["{", '{"ok":true}']), "m", "p", schema, 64, "x", requests)
    assert value == {"ok": True} and repairs == 1 and len(requests) == 2


def test_repair_failure_is_terminal():
    schema = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
    with pytest.raises(Phase03Error, match="MODEL_JSON_REPAIR_FAILED"):
        _generate_json(QueueClient(["{", "{"]), "m", "p", schema, 64, "x", [])


def test_unknown_chunk_and_outside_selection_rejected():
    with pytest.raises(Phase03Error, match="EVIDENCE_CHUNK_OUTSIDE_SELECTION"):
        validate_claims([claim(chunk="chk-2222222222222222")], {"chk-1111111111111111": "Alpha"}, "b1")


def test_claim_without_evidence_fails_schema():
    root = Path(__file__).resolve().parents[1]
    value = {"schema_version": 1, "claims": [{**claim(), "evidence": []}]}
    with pytest.raises(Phase03Error, match="SCHEMA_VALIDATION_FAILED"):
        validate_schema(value, load_schema(root, "grounded-claims.schema.json"), "claims")


def test_quote_not_found_and_canonical_only_match():
    with pytest.raises(Phase03Error, match="EVIDENCE_QUOTE_NOT_FOUND"):
        validate_claims([claim(quote="wrong")], {"chk-1111111111111111": "Alpha 10 kg"}, "b1")
    accepted, audit = validate_claims([claim(quote="Alpha 10 kg")], {"chk-1111111111111111": "Alpha\n  10 kg"}, "b1")
    assert accepted and audit[0] == {"claim_id": "b1-c1", "source_chunk_id": "chk-1111111111111111", "exact_quote_match": False, "canonical_quote_match": True, "semantic_support": "unreviewed", "reviewer_note": ""}


def test_selection_document_identity_mismatch(tmp_path):
    root, pdf, store_path, selection_path, _, selection = make_inputs(tmp_path)
    selection["document_id"] = "sha256-" + "0" * 64
    selection_path.write_text(json.dumps(selection), encoding="utf-8")
    with pytest.raises(Phase03Error, match="SELECTION_DOCUMENT_IDENTITY_MISMATCH"):
        load_and_validate_inputs(root, selection_path, store_path, pdf)


def test_context_partitioning_and_oversized_fragmentation():
    chunk = {"chunk_id": "chk-1111111111111111", "selection_text": "One sentence. Two sentence. Three sentence.", "pdf_page": 1}
    fragments = fragment_chunk(chunk, 18)
    assert len(fragments) >= 3
    assert all(item.parent_chunk_id == chunk["chunk_id"] and item.pdf_page == 1 for item in fragments)
    assert [item.unit_id for item in fragments] == [item.unit_id for item in fragment_chunk(chunk, 18)]
    batches = partition_units(fragments, lambda values: sum(len(item.text) for item in values) <= 22)
    assert len(batches) >= 2


def test_synthesis_unknown_claim_id():
    claims, _ = validate_claims([claim()], {"chk-1111111111111111": "Alpha  10 kg"}, "b1")
    with pytest.raises(Phase03Error, match="SYNTHESIS_UNKNOWN_CLAIM_ID"):
        validate_synthesis(summary("unknown"), claims)


def test_page_resolution_and_duplicate_page_removal(tmp_path):
    _, _, _, _, store, selection = make_inputs(tmp_path)
    claims, _ = validate_claims([claim("c1"), claim("c2")], {"chk-1111111111111111": "Alpha  10 kg"}, "b1")
    value = summary()
    value["summary_points"][0]["claim_ids"] = ["b1-c1", "b1-c2"]
    resolved = resolve_citations(value, claims, selection, store)
    assert resolved["summary_points"][0]["citations"] == [{"pdf_page": 1, "page_label": "i", "printed_page": "7", "display": "[PDF p. 1; printed p. 7]"}]


def test_deterministic_dedup_exact_and_canonical():
    first, _ = validate_claims([claim("c1")], {"chk-1111111111111111": "Alpha  10 kg"}, "b1")
    second, _ = validate_claims([{**claim("c2"), "claim_text": "Alpha  is 10 kg."}], {"chk-1111111111111111": "Alpha  10 kg"}, "b2")
    kept, removed = deduplicate_claims(first + second)
    assert len(kept) == 1 and removed[0]["kept_claim_id"] == "b1-c1"


def test_cache_hit_and_invalidation(tmp_path):
    cache = MapCache(tmp_path / "cache")
    key = cache.key({"model": "a", "text": "x"})
    cache.put(key, {"claims": []})
    assert cache.get(key)["claims"] == []
    assert cache.key({"model": "b", "text": "x"}) != key
    assert cache.get(cache.key({"model": "b", "text": "x"})) is None


def test_partial_failure_does_not_publish(tmp_path):
    target = tmp_path / "final"
    with pytest.raises(RuntimeError):
        with atomic_output_directory(target) as stage:
            (stage / "partial.json").write_text("{}", encoding="utf-8")
            raise RuntimeError("batch failed")
    assert not target.exists() and not list(tmp_path.glob("*.staging"))


def test_risk_propagation():
    result = coverage_status(["contains_table", "equation_or_symbol_risk", "contains_picture_region"])
    assert result == {"text_supported": True, "limited_by_table_extraction": True, "limited_by_equation_extraction": True, "limited_by_picture_content": True, "human_review_required": True}


def test_arabic_glossary_and_prohibited_confusions_in_prompt():
    prompt = glossary_instruction("ar", {"terms": {"accuracy": "الدقة (Accuracy)"}})
    assert "Accuracy" in prompt and "Precision" in prompt and "pre-training" in prompt and "reinforcement learning" in prompt


@pytest.mark.parametrize("url", ["https://127.0.0.1:11434", "http://example.com:11434", "http://127.0.0.1:11434/api", "http://user@127.0.0.1:11434"])
def test_non_loopback_or_non_base_endpoint_rejected(url):
    with pytest.raises(Phase03Error, match="NON_LOOPBACK_ENDPOINT_REJECTED"):
        validate_loopback_base_url(url)


def test_loopback_endpoint_accepted():
    assert validate_loopback_base_url("http://localhost:11434/") == "http://localhost:11434"


def test_source_change_error_is_sanitized(tmp_path):
    root, pdf, store_path, selection_path, _, _ = make_inputs(tmp_path)
    source = store_path.parent / "text" / "structured" / "page_0001.md"
    source.write_text("private secret changed", encoding="utf-8")
    with pytest.raises(Phase03Error) as failure:
        load_and_validate_inputs(root, selection_path, store_path, pdf)
    assert "private secret" not in str(failure.value)


def test_document_store_source_path_escape_rejected(tmp_path):
    root, pdf, store_path, selection_path, store, _ = make_inputs(tmp_path)
    store["chunks"][0]["source_text_path"] = "../outside.md"
    store_path.write_text(json.dumps(store), encoding="utf-8")
    with pytest.raises(Phase03Error, match="SOURCE_PATH_OUTSIDE_DOCUMENT_STORE"):
        load_and_validate_inputs(root, selection_path, store_path, pdf)


def test_timestamp_and_run_id_excluded_from_deterministic_projection():
    left = {"run_id": "a", "started_at": "x", "value": [1, 2]}
    right = {"run_id": "b", "started_at": "y", "value": [1, 2]}
    assert deterministic_projection(left) == deterministic_projection(right)


def test_pipeline_cache_reuse_and_atomic_publication(tmp_path):
    root, pdf, store_path, selection_path, _, _ = make_inputs(tmp_path)
    cache_path = tmp_path / "cache"
    first_client = FakeClient()
    first = run_summary(project_root=root, selection_path=selection_path, store_path=store_path, pdf_path=pdf, out_path=tmp_path / "run1", language="en", audience="engineer", length="short", glossary_path=None, model="test", base_url=first_client.base_url, strategy="hierarchical", num_predict=128, cache_path=cache_path, client=first_client)
    second_client = FakeClient()
    second = run_summary(project_root=root, selection_path=selection_path, store_path=store_path, pdf_path=pdf, out_path=tmp_path / "run2", language="en", audience="engineer", length="short", glossary_path=None, model="test", base_url=second_client.base_url, strategy="hierarchical", num_predict=128, cache_path=cache_path, client=second_client)
    assert first["metadata"]["cache"] == {"hits": 0, "misses": 1, "reused_map_batches": 0, "bypassed": False, "synthesis_policy": "deterministic_semantic_plan"}
    assert first["metadata"]["schema_version"] == first["metadata"]["schema_versions"]["metadata"] == 4
    assert first["metadata"]["generation_mode"] == "deterministic_assembly"
    assert first["metadata"]["calibration_calls"] == 1 and first["metadata"]["model_calls_total"] == 0
    validate_schema(first["metadata"], load_schema(root, "run-metadata.schema.json"), "run-metadata")
    assert second["metadata"]["cache"]["hits"] == 1
    assert (tmp_path / "run2" / "summary.md").is_file()
    assert (tmp_path / "run2" / "claims-review.md").is_file()
    assert (tmp_path / "run2" / "coverage-report.md").is_file()
    review = json.loads((tmp_path / "run2" / "claims-review.json").read_text(encoding="utf-8"))
    assert review["schema_version"] == second["metadata"]["schema_versions"]["review"] == 3
    evidence = review["points"][0]["evidence"][0]
    assert {"pdf_page", "chunk_id", "exact_short_quote", "context_before", "context_after"}.issubset(evidence)


def test_false_cold_request_is_rejected_before_deterministic_fallback(tmp_path):
    root, pdf, store_path, selection_path, _, _ = make_inputs(tmp_path)
    out = tmp_path / "false-cold"
    client = FakeClient()
    with pytest.raises(Phase03Error, match="COLD_RUN_REQUIRES_MODEL_MAP_ENRICHMENT"):
        run_summary(
            project_root=root, selection_path=selection_path, store_path=store_path,
            pdf_path=pdf, out_path=out, language="en", audience="engineer",
            length="short", glossary_path=None, model="test", base_url=client.base_url,
            strategy="hierarchical", num_predict=128, client=client, require_cold=True,
        )
    assert not out.exists()


def test_required_model_stage_with_zero_calls_fails_atomically(tmp_path):
    root, pdf, store_path, selection_path, _, _ = make_inputs(tmp_path)
    out = tmp_path / "zero-map"
    client = FakeClient()
    with pytest.raises(Phase03Error, match="REQUIRED_MODEL_STAGE_ZERO_CALLS:map"):
        run_summary(
            project_root=root, selection_path=selection_path, store_path=store_path,
            pdf_path=pdf, out_path=out, language="en", audience="engineer",
            length="short", glossary_path=None, model="test", base_url=client.base_url,
            strategy="hierarchical", num_predict=128, cache_path=tmp_path / "zero-cache",
            client=client, required_model_stages={"map"},
        )
    assert not out.exists()


class BadArabicClient(FakeClient):
    def generate(self, model, prompt, schema, num_ctx, num_predict, temperature=0, think=False):
        self.calls.append(prompt)
        metrics = {"total_duration": 10, "load_duration": 1, "prompt_eval_count": 100, "prompt_eval_cached_count": 0, "prompt_eval_duration": 2, "eval_count": 10, "eval_duration": 3, "done_reason": "stop", "configured_num_ctx": num_ctx, "configured_num_predict": num_predict}
        if "ok=true" in prompt:
            return '{"ok":true}', metrics
        ids = schema.get("properties", {}).get("points", {}).get("items", {}).get("properties", {}).get("claim_id", {}).get("enum", [])
        return json.dumps({"schema_version": 1, "points": [{"claim_id": claim_id, "point_text": "صياغة تحذف الأرقام والوحدات."} for claim_id in ids]}, ensure_ascii=False), metrics


def test_arabic_semantic_validation_failure_publishes_no_partial_run(tmp_path):
    root, pdf, store_path, selection_path, _, _ = make_inputs(tmp_path)
    english_dir = tmp_path / "english"
    run_summary(
        project_root=root, selection_path=selection_path, store_path=store_path,
        pdf_path=pdf, out_path=english_dir, language="en", audience="engineer",
        length="short", glossary_path=None, model="test", base_url=FakeClient.base_url,
        strategy="hierarchical", num_predict=128, cache_path=tmp_path / "english-cache",
        client=FakeClient(),
    )
    arabic_dir = tmp_path / "arabic-rejected"
    with pytest.raises(Phase03Error, match="ARABIC_PARITY_VALIDATION_FAILED"):
        run_summary(
            project_root=root, selection_path=selection_path, store_path=store_path,
            pdf_path=pdf, out_path=arabic_dir, language="ar", audience="طالب تقني",
            length="short", glossary_path=None, model="test", base_url=BadArabicClient.base_url,
            strategy="hierarchical", num_predict=128, client=BadArabicClient(),
            semantic_plan_path=english_dir / "semantic-plan.json",
            disable_translation_memory=True, disable_rejected_render_reuse=True,
            require_model_rendering=True,
        )
    assert not arabic_dir.exists()
    failure = tmp_path / "arabic-rejected-human-review-failure.json"
    assert failure.is_file()
    assert json.loads(failure.read_text(encoding="utf-8"))["status"] == "rejected_not_published"


def test_map_truncation_does_not_publish_partial_success(tmp_path):
    root, pdf, store_path, selection_path, _, _ = make_inputs(tmp_path)
    out = tmp_path / "failed"
    client = FakeClient()
    original = client.generate
    def truncated(*args, **kwargs):
        raw, metrics = original(*args, **kwargs)
        if "Build a language-independent evidence inventory" in args[1]:
            metrics["done_reason"] = "length"
        return raw, metrics
    client.generate = truncated
    with pytest.raises(Phase03Error, match="MODEL_OUTPUT_TRUNCATED"):
        run_summary(project_root=root, selection_path=selection_path, store_path=store_path, pdf_path=pdf, out_path=out, language="en", audience="engineer", length="short", glossary_path=None, model="test", base_url="http://127.0.0.1:11434", strategy="hierarchical", num_predict=128, cache_path=tmp_path / "cache", client=client, model_map_enrichment=True)
    assert not out.exists()


def test_evaluator_unwraps_artifact_documents():
    checklist = {"selection_chunk_ids": ["chk-1111111111111111"], "items": []}
    accepted, audit = validate_claims([claim()], {"chk-1111111111111111": "Alpha  10 kg"}, "b1")
    report = evaluate(checklist, {"summary": summary(), "claims": {"claims": accepted}, "evidence_audit": {"checks": audit}})
    assert report["metrics"]["citation_id_validity"]["display"] == "1 / 1"
