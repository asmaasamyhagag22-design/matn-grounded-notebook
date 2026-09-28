from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from evaluate_document_index import evaluate_index


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVALUATION_SCHEMA = PROJECT_ROOT / "schemas" / "index-evaluation.schema.json"


def test_evaluator_reports_separate_fraction_metrics() -> None:
    chunk_1 = {
        "chunk_id": "chk-1",
        "order": 0,
        "pdf_page": 1,
        "source_type": "structured",
        "start_offset": 0,
        "end_offset": 10,
        "text": "# 1. One\nBody one",
        "content_risk_flags": [],
    }
    chunk_2 = chunk_1 | {
        "chunk_id": "chk-2",
        "order": 1,
        "text": "# 2. Two\nBody two",
        "start_offset": 11,
        "end_offset": 22,
    }
    store = {
        "document": {"document_id": "doc"},
        "coverage": {"pdf_pages": [1]},
        "pages": [{"pdf_page": 1}],
        "chunks": [chunk_1, chunk_2],
        "header_footer_candidates": [],
        "sections": [
            {
                "section_id": "sec-1",
                "normalized_title": "1. one",
                "title": "1. One",
                "level": 1,
                "parent_section_id": None,
                "first_pdf_page": 1,
                "last_pdf_page": 1,
                "start_anchor": {"pdf_page": 1, "chunk_id": "chk-1", "offset": 2},
                "end_anchor_exclusive": {"pdf_page": 1, "chunk_id": "chk-2", "offset": 2},
                "included_chunk_ids": ["chk-1"],
                "confirmation_status": "confirmed",
            }
        ],
    }
    expectations = {
        "schema_version": 1,
        "sections": [
            {
                "title": "1. One",
                "level": 1,
                "parent_title": None,
                "first_pdf_page": 1,
                "last_pdf_page": 1,
                "end_before_title": "2. Two",
                "required_snippets": ["Body one"],
                "forbidden_snippets": ["Body two"],
            }
        ],
    }
    report = evaluate_index(store, expectations)
    Draft202012Validator(json.loads(EVALUATION_SCHEMA.read_text(encoding="utf-8"))).validate(report)
    assert "accuracy" not in report
    assert report["method"]["llm_judge"] is False
    for metric in report["metrics"].values():
        assert metric["display"] == f"{metric['passed_checks']} / {metric['applicable_checks']}"
        assert metric["passed_checks"] == metric["applicable_checks"]
