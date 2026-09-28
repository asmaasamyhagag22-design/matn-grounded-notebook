"""Deterministic Phase 02 section-index evaluation (no LLM judge)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from document_store import normalize_text, read_json, select_source


METRIC_NAMES = (
    "heading_detection",
    "heading_level",
    "parent_relation",
    "start_boundary",
    "end_boundary",
    "chunk_inclusion",
    "chunk_exclusion",
    "page_reference_validity",
)


def _metric() -> dict[str, Any]:
    return {"passed_checks": 0, "applicable_checks": 0, "display": "0 / 0", "failures": []}


def _record(metric: dict[str, Any], passed: bool, detail: str) -> None:
    metric["applicable_checks"] += 1
    if passed:
        metric["passed_checks"] += 1
    else:
        metric["failures"].append(detail)


def _finalize(metrics: dict[str, dict[str, Any]]) -> None:
    for metric in metrics.values():
        metric["display"] = f"{metric['passed_checks']} / {metric['applicable_checks']}"


def evaluate_index(store: dict[str, Any], expectations: dict[str, Any]) -> dict[str, Any]:
    if expectations.get("schema_version") != 1:
        raise ValueError("expectations must use schema_version 1")
    metrics = {name: _metric() for name in METRIC_NAMES}
    sections_by_title: dict[str, list[dict[str, Any]]] = {}
    sections_by_id = {item["section_id"]: item for item in store["sections"]}
    chunks_by_id = {item["chunk_id"]: item for item in store["chunks"]}
    for section in store["sections"]:
        sections_by_title.setdefault(section["normalized_title"], []).append(section)

    cases: list[dict[str, Any]] = []
    for expected in expectations["sections"]:
        title = expected["title"]
        normalized = normalize_text(title)
        matches = sections_by_title.get(normalized, [])
        unique = len(matches) == 1
        _record(metrics["heading_detection"], unique, f"{title}: found {len(matches)}")
        case: dict[str, Any] = {"title": title, "matched_section_id": None, "checks": {}}
        if not unique:
            cases.append(case)
            continue
        section = matches[0]
        case["matched_section_id"] = section["section_id"]

        passed = section["level"] == expected["level"]
        _record(metrics["heading_level"], passed, f"{title}: expected {expected['level']}, got {section['level']}")

        expected_parent = expected.get("parent_title")
        actual_parent = sections_by_id.get(section["parent_section_id"] or "")
        actual_parent_title = actual_parent["normalized_title"] if actual_parent else None
        parent_passed = actual_parent_title == (normalize_text(expected_parent) if expected_parent else None)
        _record(metrics["parent_relation"], parent_passed, f"{title}: parent mismatch")

        start_passed = (
            section["first_pdf_page"] == expected["first_pdf_page"]
            and section["start_anchor"]["pdf_page"] == expected["first_pdf_page"]
        )
        _record(metrics["start_boundary"], start_passed, f"{title}: start page mismatch")

        end_title = expected.get("end_before_title")
        end_anchor = section["end_anchor_exclusive"]
        if end_title is None:
            end_title_passed = end_anchor is None
        else:
            end_chunk = chunks_by_id.get(end_anchor["chunk_id"] if end_anchor else "")
            end_title_passed = bool(end_chunk and normalize_text(end_title) in normalize_text(end_chunk["text"]))
        end_passed = end_title_passed and section["last_pdf_page"] == expected["last_pdf_page"]
        _record(metrics["end_boundary"], end_passed, f"{title}: end boundary mismatch")

        selection = select_source(
            store,
            section_ids=[section["section_id"]],
            allow_unconfirmed=True,
        )
        selection_text = "\n".join(item["original_text"] for item in selection["chunks"])
        for snippet in expected.get("required_snippets", []):
            _record(metrics["chunk_inclusion"], snippet in selection_text, f"{title}: missing required snippet {snippet!r}")
        for snippet in expected.get("forbidden_snippets", []):
            _record(metrics["chunk_exclusion"], snippet not in selection_text, f"{title}: included forbidden snippet {snippet!r}")
        valid_pages = set(store["coverage"]["pdf_pages"])
        for citation in selection["citations"]:
            chunk = chunks_by_id.get(citation["chunk_id"])
            valid = bool(
                chunk
                and citation["pdf_page"] == chunk["pdf_page"]
                and citation["pdf_page"] in valid_pages
            )
            _record(metrics["page_reference_validity"], valid, f"{title}: invalid citation {citation}")
        cases.append(case)

    _finalize(metrics)
    return {
        "schema_version": 1,
        "evaluation_status": "completed",
        "document_id": store["document"]["document_id"],
        "method": {
            "llm_judge": False,
            "fuzzy_matching": False,
            "not_applicable_excluded_from_denominator": True,
            "general_accuracy_reported": False,
        },
        "metrics": metrics,
        "cases": cases,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate a Matn Phase 02 index against reviewed ground truth.")
    parser.add_argument("--document-store", required=True, type=Path)
    parser.add_argument("--expectations", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store_path = args.document_store / "document-store.json" if args.document_store.is_dir() else args.document_store
        report = evaluate_index(read_json(store_path), read_json(args.expectations))
        if args.out.exists():
            raise ValueError("output path already exists; refusing to overwrite")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for name, metric in report["metrics"].items():
            print(f"{name}: {metric['display']}")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
