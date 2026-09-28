"""Compare Matn raw and structured extractors using reviewable exact checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Sequence

from inspect_pdf import (
    EXIT_INPUT_ERROR,
    EXIT_OK,
    EXIT_UNEXPECTED_ERROR,
    InspectionError,
    PageSelection,
    StagedOutput,
    run_extraction,
    utc_now,
    write_utf8_atomically,
)


CHECK_TYPES = (
    "required_exact_snippets",
    "required_numbers_and_units",
    "forbidden_snippets",
    "expected_order_pairs",
)
RESULT_STATUSES = {"pass", "fail", "not_applicable", "needs_human_review"}


def load_expectations(
    path: Path, selection: PageSelection
) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_text(encoding="utf-8")
        data = json.loads(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InspectionError(
            f"Cannot read expectations ({type(exc).__name__}).", EXIT_INPUT_ERROR
        ) from exc

    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise InspectionError(
            "Expectations must be a schema_version 1 JSON object.", EXIT_INPUT_ERROR
        )
    pages = data.get("pages")
    if not isinstance(pages, list):
        raise InspectionError("Expectations pages must be a list.", EXIT_INPUT_ERROR)

    expected_page_numbers: list[int] = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("pdf_page"), int):
            raise InspectionError(
                "Every expectation page needs an integer pdf_page.", EXIT_INPUT_ERROR
            )
        pdf_page = page["pdf_page"]
        if pdf_page in expected_page_numbers:
            raise InspectionError(
                f"Duplicate expectations for PDF page {pdf_page}.", EXIT_INPUT_ERROR
            )
        expected_page_numbers.append(pdf_page)

        applicable = page.get("applicable_checks")
        checks = page.get("checks")
        if not isinstance(applicable, list) or not isinstance(checks, dict):
            raise InspectionError(
                f"PDF page {pdf_page} needs applicable_checks and checks.",
                EXIT_INPUT_ERROR,
            )
        if len(set(applicable)) != len(applicable) or any(
            check not in CHECK_TYPES for check in applicable
        ):
            raise InspectionError(
                f"PDF page {pdf_page} has invalid applicable_checks.", EXIT_INPUT_ERROR
            )
        for check_type in CHECK_TYPES:
            values = checks.get(check_type, [])
            if not isinstance(values, list):
                raise InspectionError(
                    f"PDF page {pdf_page} check {check_type} must be a list.",
                    EXIT_INPUT_ERROR,
                )
            if check_type in applicable and not values:
                raise InspectionError(
                    f"PDF page {pdf_page} marks {check_type} applicable but has no values.",
                    EXIT_INPUT_ERROR,
                )
            if check_type == "expected_order_pairs":
                valid = all(
                    isinstance(value, list)
                    and len(value) == 2
                    and all(isinstance(item, str) and item for item in value)
                    for value in values
                )
            else:
                valid = all(isinstance(value, str) and value for value in values)
            if not valid:
                raise InspectionError(
                    f"PDF page {pdf_page} has invalid values for {check_type}.",
                    EXIT_INPUT_ERROR,
                )

    if expected_page_numbers != list(selection.pdf_pages):
        raise InspectionError(
            "Expectation page order must exactly match --pages.", EXIT_INPUT_ERROR
        )
    return data, payload


def canonicalize_for_comparison(value: str) -> str:
    """NFKC-normalize and collapse whitespace without changing bidi controls."""
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()


def evaluate_check(
    check_type: str, value: Any, text: str, *, canonical: bool = False
) -> str:
    if canonical:
        text = canonicalize_for_comparison(text)
        if check_type == "expected_order_pairs":
            value = [canonicalize_for_comparison(item) for item in value]
        else:
            value = canonicalize_for_comparison(value)
    if check_type in {"required_exact_snippets", "required_numbers_and_units"}:
        return "pass" if value in text else "fail"
    if check_type == "forbidden_snippets":
        return "pass" if value not in text else "fail"
    if check_type == "expected_order_pairs":
        first, second = value
        first_at = text.find(first)
        second_at = text.find(second)
        if first_at < 0 or second_at < 0:
            return "needs_human_review"
        return "pass" if first_at < second_at else "fail"
    raise RuntimeError(f"Unknown check type: {check_type}")


def evaluate_page(
    text: str, expectation: dict[str, Any], *, canonical: bool = False
) -> dict[str, Any]:
    applicable = set(expectation["applicable_checks"])
    checks: dict[str, Any] = {}
    for check_type in CHECK_TYPES:
        if check_type not in applicable:
            checks[check_type] = {"status": "not_applicable", "items": []}
            continue

        item_results = []
        for value in expectation["checks"].get(check_type, []):
            status = evaluate_check(check_type, value, text, canonical=canonical)
            item_results.append({"expected": value, "status": status})
        statuses = {item["status"] for item in item_results}
        if "fail" in statuses:
            summary_status = "fail"
        elif "needs_human_review" in statuses:
            summary_status = "needs_human_review"
        else:
            summary_status = "pass"
        checks[check_type] = {"status": summary_status, "items": item_results}

    return {
        "pdf_page": expectation["pdf_page"],
        "notes": expectation.get("notes"),
        "checks": checks,
    }


def aggregate_metrics(page_results: list[dict[str, Any]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for check_type in CHECK_TYPES:
        passed = 0
        applicable = 0
        failed = 0
        needs_review = 0
        for page in page_results:
            for item in page["checks"][check_type]["items"]:
                status = item["status"]
                if status == "not_applicable":
                    continue
                applicable += 1
                if status == "pass":
                    passed += 1
                elif status == "fail":
                    failed += 1
                elif status == "needs_human_review":
                    needs_review += 1
        metrics[check_type] = {
            "passed_checks": passed,
            "applicable_checks": applicable,
            "failed_checks": failed,
            "needs_human_review_checks": needs_review,
            "display": f"{passed} / {applicable}",
        }
    return metrics


def read_extracted_pages(output_dir: Path, manifest: dict[str, Any]) -> dict[int, str]:
    extracted: dict[int, str] = {}
    for page in manifest["pages"]:
        text_path = output_dir / page["text_path"]
        extracted[page["pdf_page"]] = text_path.read_text(encoding="utf-8")
    return extracted


def validate_report(report: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "evaluation_run_id",
        "run_status",
        "source",
        "requested_pdf_pages",
        "expectations",
        "timing",
        "method",
        "extractors",
    }
    if set(report) != required or report["schema_version"] != 2:
        raise RuntimeError("Evaluation report does not match schema version 2")
    if report["run_status"] != "completed":
        raise RuntimeError("Evaluation report is not completed")
    def contains_accuracy_key(value: Any) -> bool:
        if isinstance(value, dict):
            return any(
                str(key).casefold() == "accuracy" or contains_accuracy_key(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(contains_accuracy_key(item) for item in value)
        return False

    if contains_accuracy_key(report):
        raise RuntimeError("Evaluation report must not contain a general accuracy metric")
    for result in report["extractors"].values():
        for metric_group in ("metrics", "canonical_metrics"):
            for metric in result[metric_group].values():
                if metric["passed_checks"] > metric["applicable_checks"]:
                    raise RuntimeError("Metric numerator exceeds denominator")
        for page_group in ("pages", "canonical_pages"):
            for page in result[page_group]:
                for check in page["checks"].values():
                    if check["status"] not in RESULT_STATUSES:
                        raise RuntimeError("Unknown evaluation result status")


def render_markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Matn extractor comparison",
        "",
        f"- Source: `{report['source']['file_name']}`",
        f"- SHA-256: `{report['source']['sha256']}`",
        f"- PDF pages: `{report['requested_pdf_pages']['input']}`",
        "- Matching: exact substring checks only; no fuzzy matching or LLM judge.",
        "- A matching snippet does not establish correctness of the rest of a page.",
        "",
        "## Exact-preservation metrics",
        "",
        "| Metric | Raw | Structured |",
        "|---|---:|---:|",
    ]
    for check_type in CHECK_TYPES:
        raw = report["extractors"]["raw"]["metrics"][check_type]["display"]
        structured = report["extractors"]["structured"]["metrics"][check_type][
            "display"
        ]
        lines.append(f"| {check_type} | {raw} | {structured} |")

    lines.extend(
        [
            "",
            "## Canonical-preservation metrics",
            "",
            "Canonical comparison uses Unicode NFKC and collapses repeated whitespace. Bidi controls are retained and no visual reordering is performed.",
            "",
            "| Metric | Raw | Structured |",
            "|---|---:|---:|",
        ]
    )
    for check_type in CHECK_TYPES:
        raw = report["extractors"]["raw"]["canonical_metrics"][check_type][
            "display"
        ]
        structured = report["extractors"]["structured"]["canonical_metrics"][
            check_type
        ]["display"]
        lines.append(f"| {check_type} | {raw} | {structured} |")

    lines.extend(["", "## Page-level results", ""])
    for extractor_name in ("raw", "structured"):
        lines.extend(
            [
                f"### {extractor_name}",
                "",
                "| PDF page | Check | Result | Passed / Applicable |",
                "|---:|---|---|---:|",
            ]
        )
        for page in report["extractors"][extractor_name]["pages"]:
            for check_type in CHECK_TYPES:
                check = page["checks"][check_type]
                passed = sum(item["status"] == "pass" for item in check["items"])
                applicable = len(check["items"])
                lines.append(
                    f"| {page['pdf_page']} | {check_type} | {check['status']} | "
                    f"{passed} / {applicable} |"
                )
        lines.append("")
    return "\n".join(lines) + "\n"


def run_evaluation(
    pdf_path: Path,
    selection: PageSelection,
    expectations_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    expectations, expectations_payload = load_expectations(expectations_path, selection)
    evaluation_run_id = str(uuid.uuid4())
    started_at = utc_now()
    started_ns = time.perf_counter_ns()

    with StagedOutput(output_dir, evaluation_run_id) as staged:
        extractor_results: dict[str, Any] = {}
        for extractor_name in ("raw", "structured"):
            extractor_output = staged.staging_path / extractor_name
            manifest = run_extraction(
                pdf_path,
                selection,
                extractor_output,
                extractor=extractor_name,
            )
            texts = read_extracted_pages(extractor_output, manifest)
            page_results = [
                evaluate_page(texts[page["pdf_page"]], page)
                for page in expectations["pages"]
            ]
            canonical_page_results = [
                evaluate_page(texts[page["pdf_page"]], page, canonical=True)
                for page in expectations["pages"]
            ]
            extractor_results[extractor_name] = {
                "manifest_path": f"{extractor_name}/manifest.json",
                "extractor": manifest["extractor"],
                "metrics": aggregate_metrics(page_results),
                "canonical_metrics": aggregate_metrics(canonical_page_results),
                "pages": page_results,
                "canonical_pages": canonical_page_results,
            }

        raw_manifest = json.loads(
            (staged.staging_path / "raw" / "manifest.json").read_text(encoding="utf-8")
        )
        structured_manifest = json.loads(
            (staged.staging_path / "structured" / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        if raw_manifest["source"] != structured_manifest["source"]:
            raise RuntimeError("Extractor source identities differ")

        report = {
            "schema_version": 2,
            "evaluation_run_id": evaluation_run_id,
            "run_status": "completed",
            "source": raw_manifest["source"],
            "requested_pdf_pages": raw_manifest["requested_pdf_pages"],
            "expectations": {
                "file_name": expectations_path.name,
                "sha256": hashlib.sha256(
                    expectations_payload.encode("utf-8")
                ).hexdigest(),
            },
            "timing": {
                "started_at": started_at,
                "completed_at": utc_now(),
                "elapsed": (time.perf_counter_ns() - started_ns) / 1_000_000_000,
                "unit": "seconds",
                "clock": "time.perf_counter_ns (monotonic wall-clock)",
                "scope": "both extraction runs, exact checks, and staged report writes",
            },
            "method": {
                "judge": "deterministic exact matching",
                "fuzzy_matching": False,
                "llm_judge": False,
                "excludes_not_applicable_from_denominator": True,
                "interpretation_warning": (
                    "A passing snippet check does not prove the rest of a page is correct."
                ),
                "exact_comparison": "unaltered extractor output and expectation strings",
                "canonical_comparison": (
                    "Unicode NFKC plus repeated-whitespace collapse; bidi controls are "
                    "retained and no visual reordering is performed"
                ),
            },
            "extractors": extractor_results,
        }
        validate_report(report)
        write_utf8_atomically(
            staged.staging_path / "expectations.json", expectations_payload
        )
        write_utf8_atomically(
            staged.staging_path / "report.json",
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
        write_utf8_atomically(
            staged.staging_path / "report.md", render_markdown_report(report)
        )
        staged.publish()
        return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--pages", required=True)
    parser.add_argument("--expectations", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        selection = PageSelection.parse(args.pages)
        run_evaluation(args.pdf, selection, args.expectations, args.out)
    except InspectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(
            f"unexpected error: {type(exc).__name__}; no final evaluation was published.",
            file=sys.stderr,
        )
        return EXIT_UNEXPECTED_ERROR
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
