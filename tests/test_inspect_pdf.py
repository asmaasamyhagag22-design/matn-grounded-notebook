from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest
import pymupdf
from jsonschema import Draft202012Validator, FormatChecker

import inspect_pdf
from benchmark_structured import extract_batched, extract_per_page, validate_chunks
from evaluate_extractors import (
    canonicalize_for_comparison,
    run_evaluation,
    validate_report,
)
from inspect_pdf import PageExtractionError, PageSelection, run_extraction
from make_sample_pdfs import (
    ARABIC_TEXT,
    KNOWN_PAGE_TEXT,
    SYSTEM_ARABIC_FONT,
    create_password_pdf,
    create_representative_pdf,
    create_samples,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLI = PROJECT_ROOT / "inspect_pdf.py"
EXPECTATIONS = PROJECT_ROOT / "tests" / "expectations" / "representative.json"
MANIFEST_SCHEMA = PROJECT_ROOT / "schemas" / "manifest.schema.json"
EVALUATION_SCHEMA = PROJECT_ROOT / "schemas" / "evaluation-report.schema.json"


@pytest.fixture
def samples(tmp_path: Path) -> dict[str, Path]:
    return create_samples(tmp_path / "samples")


@pytest.fixture
def representative_pdf(tmp_path: Path) -> Path:
    if not SYSTEM_ARABIC_FONT.is_file():
        pytest.skip("Windows Arial font is unavailable for Arabic fixture generation")
    path = tmp_path / "representative.pdf"
    create_representative_pdf(path)
    return path


def run_cli(
    pdf: Path, pages: str, output: Path, extractor: str = "raw"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--pdf",
            str(pdf),
            "--pages",
            pages,
            "--out",
            str(output),
            "--extractor",
            extractor,
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_json(instance: dict, schema_path: Path) -> None:
    schema = read_json(schema_path)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(instance)


def test_raw_extracts_exact_pages_manifest_and_does_not_log_content(
    samples: dict[str, Path], tmp_path: Path
) -> None:
    output = tmp_path / "result"
    result = run_cli(samples["known_text"], "2-3", output)

    assert result.returncode == 0, result.stderr
    assert "SENSOR READING" not in result.stdout
    assert (output / "page_0002.txt").read_text(encoding="utf-8") == (
        KNOWN_PAGE_TEXT[1] + "\n"
    )
    assert (output / "page_0003.txt").read_text(encoding="utf-8") == (
        KNOWN_PAGE_TEXT[2] + "\n"
    )
    assert not (output / "page_0001.txt").exists()

    manifest = read_json(output / "manifest.json")
    validate_json(manifest, MANIFEST_SCHEMA)
    assert manifest["requested_pdf_pages"]["pdf_pages"] == [2, 3]
    assert manifest["requested_pdf_pages"]["page_indices"] == [1, 2]
    assert [page["pdf_page"] for page in manifest["pages"]] == [2, 3]
    assert all(page["printed_page"] is None for page in manifest["pages"])
    assert all(page["error"] is None for page in manifest["pages"])
    assert manifest["source"]["file_name"] == "known_text.pdf"
    assert manifest["source"]["size_bytes"] == samples["known_text"].stat().st_size
    assert manifest["source"]["sha256"] == hashlib.sha256(
        samples["known_text"].read_bytes()
    ).hexdigest()
    assert "path" not in manifest["source"]
    assert manifest["extractor"]["settings"]["ocr"] is False
    assert manifest["timing"]["unit"] == "seconds"
    assert "excludes final directory rename" in manifest["timing"]["scope"]


def test_structured_preserves_noncontiguous_page_mapping(
    samples: dict[str, Path], tmp_path: Path
) -> None:
    output = tmp_path / "structured"
    result = run_cli(samples["known_text"], "1,3", output, extractor="structured")

    assert result.returncode == 0, result.stderr
    manifest = read_json(output / "manifest.json")
    validate_json(manifest, MANIFEST_SCHEMA)
    assert manifest["requested_pdf_pages"]["pdf_pages"] == [1, 3]
    assert manifest["requested_pdf_pages"]["page_indices"] == [0, 2]
    assert [page["text_path"] for page in manifest["pages"]] == [
        "page_0001.md",
        "page_0003.md",
    ]
    assert "INTRODUCTION TOKEN ALPHA" in (output / "page_0001.md").read_text(
        encoding="utf-8"
    )
    assert "CONCLUSION TOKEN CHARLIE" in (output / "page_0003.md").read_text(
        encoding="utf-8"
    )
    assert not (output / "page_0002.md").exists()
    settings = manifest["extractor"]["settings"]
    assert settings["layout_mode"] == "pymupdf_layout"
    assert settings["page_chunks"] is True
    assert settings["use_ocr"] is False
    assert settings["force_ocr"] is False


def test_structured_batched_matches_per_page_and_rejects_bad_mapping(
    samples: dict[str, Path]
) -> None:
    page_indices = [0, 2]
    with pymupdf.open(samples["known_text"]) as document:
        per_page = extract_per_page(document, page_indices)
        batched = extract_batched(document, page_indices)

    assert list(batched) == [1, 3]
    assert batched == per_page
    with pytest.raises(RuntimeError, match="mapping mismatch"):
        validate_chunks(
            [{"metadata": {"page_number": 2}, "text": "wrong page"}], [0]
        )


def test_blank_and_image_only_share_no_text_but_have_distinct_signals(
    samples: dict[str, Path], tmp_path: Path
) -> None:
    blank_output = tmp_path / "blank-result"
    image_output = tmp_path / "image-result"
    assert run_cli(samples["blank"], "1", blank_output).returncode == 0
    assert run_cli(samples["image_only"], "1", image_output).returncode == 0

    blank_page = read_json(blank_output / "manifest.json")["pages"][0]
    image_page = read_json(image_output / "manifest.json")["pages"][0]
    assert blank_page["extraction_status"] == image_page["extraction_status"] == "no_text"
    assert blank_page["signals"]["image_count"] == 0
    assert image_page["signals"]["image_count"] >= 1
    assert any("does not prove" in warning for warning in image_page["warnings"])


@pytest.mark.parametrize("pages", ["0", "3-2", "1-4", "abc", "1,1"])
def test_rejects_invalid_out_of_bounds_or_duplicate_pages(
    samples: dict[str, Path], tmp_path: Path, pages: str
) -> None:
    output = tmp_path / f"bad-{pages.replace(',', '_').replace('-', '_')}"
    result = run_cli(samples["known_text"], pages, output)
    assert result.returncode == 2
    assert not output.exists()


def test_rejects_password_missing_and_corrupt_inputs(tmp_path: Path) -> None:
    protected = tmp_path / "protected.pdf"
    create_password_pdf(protected)
    protected_result = run_cli(protected, "1", tmp_path / "protected-result")
    missing_result = run_cli(
        tmp_path / "missing.pdf", "1", tmp_path / "missing-result"
    )
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"not a PDF")
    corrupt_result = run_cli(corrupt, "1", tmp_path / "corrupt-result")

    assert protected_result.returncode == 3
    assert "requires a password" in protected_result.stderr
    assert missing_result.returncode == 2
    assert corrupt_result.returncode == 3
    assert "not a PDF" not in corrupt_result.stderr
    assert not (tmp_path / "protected-result").exists()
    assert not (tmp_path / "missing-result").exists()
    assert not (tmp_path / "corrupt-result").exists()


def test_refuses_every_existing_output_path(
    samples: dict[str, Path], tmp_path: Path
) -> None:
    output = tmp_path / "existing-result"
    output.mkdir()
    result = run_cli(samples["known_text"], "1", output)
    assert result.returncode == 4
    assert "refusing to overwrite" in result.stderr


def test_middle_page_failure_cleans_owned_staging_and_publishes_nothing(
    samples: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = inspect_pdf.extract_page_text

    def fail_middle(document, page, page_index, extractor):
        if page_index == 1:
            raise RuntimeError("SENSITIVE PDF CONTENT MUST NOT LEAK")
        return original(document, page, page_index, extractor)

    monkeypatch.setattr(inspect_pdf, "extract_page_text", fail_middle)
    output = tmp_path / "must-not-exist"

    with pytest.raises(PageExtractionError) as raised:
        run_extraction(
            samples["known_text"], PageSelection.parse("1-3"), output, extractor="raw"
        )

    assert "SENSITIVE PDF CONTENT" not in str(raised.value)
    assert not output.exists()
    assert not list(tmp_path.glob(f".{output.name}.*.staging"))


def test_source_change_detected_before_publish(
    samples: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    actual_sha256 = inspect_pdf.sha256_file(samples["known_text"])
    call_count = 0

    def changing_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
        nonlocal call_count
        call_count += 1
        return actual_sha256 if call_count == 1 else "0" * 64

    monkeypatch.setattr(inspect_pdf, "sha256_file", changing_sha256)
    output = tmp_path / "changed-source-result"

    with pytest.raises(inspect_pdf.InspectionError, match="changed during extraction"):
        run_extraction(samples["known_text"], PageSelection.parse("1-2"), output)

    assert not output.exists()
    assert not list(tmp_path.glob(f".{output.name}.*.staging"))


def test_representative_arabic_columns_table_rotation_and_ocr_disabled(
    representative_pdf: Path, tmp_path: Path
) -> None:
    raw_output = tmp_path / "representative-raw"
    structured_output = tmp_path / "representative-structured"
    raw = run_cli(representative_pdf, "2-10", raw_output, "raw")
    structured = run_cli(representative_pdf, "2-10", structured_output, "structured")
    assert raw.returncode == 0, raw.stderr
    assert structured.returncode == 0, structured.stderr

    raw_arabic = (raw_output / "page_0002.txt").read_text(encoding="utf-8")
    normalized_raw = unicodedata.normalize("NFKC", raw_arabic.replace("\u00a0", " "))
    structured_arabic = (structured_output / "page_0002.md").read_text(encoding="utf-8")
    assert ARABIC_TEXT in normalized_raw
    assert ARABIC_TEXT in structured_arabic

    raw_columns = (raw_output / "page_0005.txt").read_text(encoding="utf-8")
    structured_columns = (structured_output / "page_0005.md").read_text(encoding="utf-8")
    assert raw_columns.index("RIGHT COLUMN B") < raw_columns.index("LEFT COLUMN B")
    assert structured_columns.index("LEFT COLUMN B") < structured_columns.index(
        "RIGHT COLUMN B"
    )
    structured_table = (structured_output / "page_0006.md").read_text(encoding="utf-8")
    assert "|Mass|7 kg|" in structured_table

    assert "ROTATED PAGE TOKEN" in (raw_output / "page_0007.txt").read_text(
        encoding="utf-8"
    )
    structured_manifest = read_json(structured_output / "manifest.json")
    rotated = next(page for page in structured_manifest["pages"] if page["pdf_page"] == 7)
    assert rotated["extraction_status"] == "no_text"

    image_only = next(page for page in structured_manifest["pages"] if page["pdf_page"] == 9)
    mixed = next(page for page in structured_manifest["pages"] if page["pdf_page"] == 10)
    assert image_only["extraction_status"] == "no_text"
    assert image_only["signals"]["image_count"] >= 1
    assert "IMAGE ONLY FIXTURE" not in (structured_output / "page_0009.md").read_text(
        encoding="utf-8"
    )
    assert mixed["signals"]["image_count"] >= 1
    assert "MIXED NATIVE TEXT" in (structured_output / "page_0010.md").read_text(
        encoding="utf-8"
    )
    assert "IMAGE REGION" not in (structured_output / "page_0010.md").read_text(
        encoding="utf-8"
    )
    assert structured_manifest["pages"][0]["page_label"] == "M-2"


def test_manifest_deterministic_fields_and_text_are_stable(
    samples: dict[str, Path], tmp_path: Path
) -> None:
    first_output = tmp_path / "first"
    second_output = tmp_path / "second"
    first = run_extraction(
        samples["known_text"], PageSelection.parse("1,3"), first_output
    )
    second = run_extraction(
        samples["known_text"], PageSelection.parse("1,3"), second_output
    )

    def deterministic_view(manifest: dict) -> dict:
        copy = json.loads(json.dumps(manifest))
        copy.pop("extraction_run_id")
        copy.pop("timing")
        return copy

    assert deterministic_view(first) == deterministic_view(second)
    assert (first_output / "page_0001.txt").read_bytes() == (
        second_output / "page_0001.txt"
    ).read_bytes()
    assert (first_output / "page_0003.txt").read_bytes() == (
        second_output / "page_0003.txt"
    ).read_bytes()


def test_evaluation_harness_emits_schema_valid_json_and_markdown(
    representative_pdf: Path, tmp_path: Path
) -> None:
    output = tmp_path / "evaluation"
    report = run_evaluation(
        representative_pdf,
        PageSelection.parse("1-10"),
        EXPECTATIONS,
        output,
    )

    validate_json(report, EVALUATION_SCHEMA)
    assert (output / "report.json").is_file()
    assert (output / "report.md").is_file()
    assert (output / "raw" / "manifest.json").is_file()
    assert (output / "structured" / "manifest.json").is_file()
    assert "accuracy" not in report
    assert report["method"]["fuzzy_matching"] is False
    assert report["method"]["llm_judge"] is False
    assert report["method"]["excludes_not_applicable_from_denominator"] is True
    for extractor in ("raw", "structured"):
        for metric_group in ("metrics", "canonical_metrics"):
            for metric in report["extractors"][extractor][metric_group].values():
                assert metric["display"] == (
                    f"{metric['passed_checks']} / {metric['applicable_checks']}"
                )


def test_canonical_comparison_is_nfkc_whitespace_only() -> None:
    value = "ＭＡＴＮ\u00a0\n  text\u200f"
    canonical = canonicalize_for_comparison(value)
    assert canonical == "MATN text\u200f"
    assert "\u200f" in canonical


def test_evaluation_validator_allows_accuracy_in_source_snippets() -> None:
    report = {
        "schema_version": 2,
        "evaluation_run_id": "00000000-0000-0000-0000-000000000000",
        "run_status": "completed",
        "source": {},
        "requested_pdf_pages": {},
        "expectations": {},
        "timing": {},
        "method": {},
        "extractors": {
            name: {
                "metrics": {},
                "canonical_metrics": {},
                "pages": [
                    {
                        "checks": {
                            "required_exact_snippets": {
                                "status": "pass",
                                "items": [
                                    {
                                        "expected": "Validation Accuracy: 58.0",
                                        "status": "pass",
                                    }
                                ],
                            }
                        }
                    }
                ],
                "canonical_pages": [],
            }
            for name in ("raw", "structured")
        },
    }

    validate_report(report)
