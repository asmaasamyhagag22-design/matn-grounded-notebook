from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest
from jsonschema import Draft202012Validator

from document_store import build_document_store, read_json, select_source
from inspect_pdf import InspectionError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STORE_SCHEMA = PROJECT_ROOT / "schemas" / "document-store.schema.json"
SELECTION_SCHEMA = PROJECT_ROOT / "schemas" / "source-selection.schema.json"


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _fixture(
    tmp_path: Path,
    structured_pages: list[str],
    *,
    toc: list[list[object]] | None = None,
    manual_headings: list[dict] | None = None,
    manual_hf: list[dict] | None = None,
    printed_pages: list[dict] | None = None,
) -> tuple[dict, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    pdf = tmp_path / "source.pdf"
    document = pymupdf.open()
    for number in range(1, len(structured_pages) + 1):
        page = document.new_page()
        page.insert_text((72, 72), f"Synthetic page {number}")
    if toc is not None:
        document.set_toc(toc)
    document.save(pdf)
    document.close()

    sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    source = {
        "file_name": "source.pdf",
        "size_bytes": pdf.stat().st_size,
        "sha256": sha256,
        "page_count": len(structured_pages),
    }
    raw_dir = tmp_path / "raw"
    structured_dir = tmp_path / "structured"
    raw_dir.mkdir()
    structured_dir.mkdir()
    raw_records = []
    structured_records = []
    for number, markdown in enumerate(structured_pages, 1):
        raw_text = markdown.replace("#", "").replace("*", "")
        raw_path = f"page_{number:04d}.txt"
        structured_path = f"page_{number:04d}.md"
        (raw_dir / raw_path).write_text(raw_text, encoding="utf-8")
        (structured_dir / structured_path).write_text(markdown, encoding="utf-8")
        common = {
            "page_index": number - 1,
            "pdf_page": number,
            "page_label": f"L-{number}",
            "printed_page": None,
            "text_char_count": len(markdown),
            "extraction_status": "text_present",
            "human_review": "not_performed",
            "signals": {"image_count": 0, "drawing_count": 0},
            "warnings": [],
            "error": None,
        }
        raw_records.append(common | {"text_path": raw_path})
        structured_records.append(common | {"text_path": structured_path})

    def manifest(name: str, run_id: str, pages: list[dict]) -> dict:
        return {
            "schema_version": 2,
            "extraction_run_id": run_id,
            "run_status": "completed",
            "source": source,
            "extractor": {
                "name": name,
                "version": "test",
                "settings": {"ocr": False},
            },
            "requested_pdf_pages": {
                "input": f"1-{len(structured_pages)}",
                "pdf_pages": list(range(1, len(structured_pages) + 1)),
                "page_indices": list(range(len(structured_pages))),
                "numbering": "test",
            },
            "timing": {},
            "environment": {},
            "pages": pages,
        }

    _write_json(raw_dir / "manifest.json", manifest("PyMuPDF Page.get_text", "raw-run", raw_records))
    _write_json(
        structured_dir / "manifest.json",
        manifest("PyMuPDF4LLM to_markdown", "structured-run", structured_records),
    )
    manual = tmp_path / "manual.json"
    _write_json(
        manual,
        {
            "schema_version": 1,
            "headings": manual_headings or [],
            "header_footer": manual_hf or [],
            "printed_pages": printed_pages or [],
        },
    )
    output = tmp_path / "store"
    store = build_document_store(pdf, raw_dir, structured_dir, output, manual_corrections=manual)
    return store, output, pdf


def _confirm(title: str, page: int, level: int, section_id: str) -> dict:
    return {
        "normalized_title": title,
        "pdf_page": page,
        "action": "confirm",
        "level": level,
        "section_id": section_id,
    }


def test_mid_page_boundaries_hierarchy_header_footer_and_schemas(tmp_path: Path) -> None:
    pages = [
        "RUNNING TITLE\n\n# **Abstract**\n\nAbstract body.\n\nDRAFT",
        "RUNNING TITLE\n\n# **1. Introduction**\n\nIntroduction tail.\n\n# **2. Methods**\n\nMethods start.\n\nDRAFT",
        "RUNNING TITLE\n\n## **2.1. Child**\n\nRepeated body phrase.\n\nDRAFT",
        "RUNNING TITLE\n\n# **3. Empty**\n\n# **References**\n\nReference body.\n\nDRAFT",
    ]
    headings = [
        _confirm("Abstract", 1, 1, "sec-abstract"),
        _confirm("1. Introduction", 2, 1, "sec-1"),
        _confirm("2. Methods", 2, 1, "sec-2"),
        _confirm("2.1. Child", 3, 2, "sec-2-1"),
        _confirm("3. Empty", 4, 1, "sec-3"),
        _confirm("References", 4, 1, "sec-references"),
    ]
    store, output, _ = _fixture(
        tmp_path,
        pages,
        manual_headings=headings,
        manual_hf=[
            {"normalized_text": "RUNNING TITLE", "position": "header", "action": "confirm"},
            {"normalized_text": "DRAFT", "position": "footer", "action": "confirm"},
        ],
        printed_pages=[{"pdf_page": 2, "printed_page": "1"}],
    )

    Draft202012Validator(read_json(STORE_SCHEMA)).validate(store)
    assert store["pages"][1]["printed_page"] == "1"
    assert store["pages"][0]["page_label"] == "L-1"
    assert not any(item["normalized_text"] == "repeated body phrase." for item in store["header_footer_candidates"])
    sections = {item["section_id"]: item for item in store["sections"]}
    assert sections["sec-2-1"]["parent_section_id"] == "sec-2"
    assert sections["sec-1"]["first_pdf_page"] == sections["sec-1"]["last_pdf_page"] == 2
    selected_intro = select_source(store, section_ids=["sec-1"])
    intro_text = "\n".join(item["selection_text"] for item in selected_intro["chunks"])
    assert "Introduction tail" in intro_text
    assert "Methods start" not in intro_text
    assert selected_intro["excluded_boundary_fragments"]

    selected_methods = select_source(store, section_ids=["sec-2"])
    methods_text = "\n".join(item["selection_text"] for item in selected_methods["chunks"])
    assert "Methods start" in methods_text and "Repeated body phrase" in methods_text
    assert "RUNNING TITLE" not in methods_text and "DRAFT" not in methods_text
    assert selected_methods["excluded_repetitive_header_footer"]
    Draft202012Validator(read_json(SELECTION_SCHEMA)).validate(selected_methods)

    empty = select_source(store, section_ids=["sec-3"])
    assert len(empty["included_chunk_ids"]) == 1
    assert (output / "text" / "raw" / "page_0001.txt").is_file()
    assert (output / "text" / "structured" / "page_0001.md").is_file()
    assert not any(str(value).startswith(str(tmp_path)) for value in store["document"].values())


def test_heading_at_page_end_continues_on_next_page(tmp_path: Path) -> None:
    store, _, _ = _fixture(
        tmp_path,
        ["Earlier body.\n\n# **1. Last-line heading**", "Continued body.\n\n# **2. Next**"],
        manual_headings=[
            _confirm("1. Last-line heading", 1, 1, "sec-1"),
            _confirm("2. Next", 2, 1, "sec-2"),
        ],
    )
    selected = select_source(store, section_ids=["sec-1"])
    assert selected["resolved_pdf_pages"] == [1, 2]
    text = "\n".join(item["selection_text"] for item in selected["chunks"])
    assert "Continued body" in text
    assert "2. Next" not in text


def test_outline_present_absent_and_conflicting(tmp_path: Path) -> None:
    agreed, _, _ = _fixture(
        tmp_path / "agreed",
        ["# **1. Introduction**\n\nBody"],
        toc=[[1, "1. Introduction", 1]],
    )
    assert agreed["outline"]["present"] is True
    assert agreed["heading_candidates"][0]["evidence_status"] == "outline_and_heading_agree"
    assert agreed["sections"][0]["confirmation_status"] == "confirmed"

    absent, _, _ = _fixture(tmp_path / "absent", ["# **1. Introduction**\n\nBody"])
    assert absent["outline"]["present"] is False
    assert absent["sections"][0]["confirmation_status"] == "proposed"
    with pytest.raises(ValueError, match="unconfirmed"):
        select_source(absent, section_ids=["sec-1"])
    allowed = select_source(absent, section_ids=["sec-1"], allow_unconfirmed=True)
    assert allowed["confirmation_status"] == "explicitly_allowed_unconfirmed"

    conflicting, _, _ = _fixture(
        tmp_path / "conflict",
        ["# **1. Introduction**\n\nBody"],
        toc=[[1, "Different outline title", 1]],
    )
    assert conflicting["heading_candidates"][0]["evidence_status"] == "conflicting_evidence"
    assert conflicting["sections"][0]["confirmation_status"] == "proposed"


def test_noncontiguous_pages_and_bad_selectors(tmp_path: Path) -> None:
    store, output, _ = _fixture(tmp_path, ["Page one", "Page two", "Page three"])
    selected = select_source(store, pages="1,3")
    assert selected["selection_scope"] == "page-scoped"
    assert selected["resolved_pdf_pages"] == [1, 3]
    assert {item["pdf_page"] for item in selected["citations"]} == {1, 3}
    with pytest.raises(InspectionError):
        select_source(store, pages="3-2")
    with pytest.raises(ValueError, match="outside"):
        select_source(store, pages="4")
    with pytest.raises(ValueError, match="section not found"):
        select_source(store, section_ids=["sec-missing"])

    cli = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "select_source.py"),
            "--document-store",
            str(output),
            "--pages",
            "abc",
            "--out",
            str(tmp_path / "bad.json"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert cli.returncode == 2
    assert not (tmp_path / "bad.json").exists()


def test_duplicate_heading_manual_rule_is_ambiguous(tmp_path: Path) -> None:
    store, _, _ = _fixture(
        tmp_path,
        ["# **Repeated**\n\nFirst", "# **Repeated**\n\nSecond"],
        manual_headings=[{"normalized_title": "Repeated", "action": "confirm"}],
    )
    assert any("matched 2 candidates" in warning for warning in store["warnings"])
    assert all(item["status"] == "proposed" for item in store["heading_candidates"])


def test_failed_build_does_not_publish_final_store(tmp_path: Path) -> None:
    store, output, pdf = _fixture(tmp_path / "base", ["# **1. One**"])
    assert store and output.exists()
    bad_out = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="SHA-256"):
        build_document_store(
            _mutated_copy(pdf, tmp_path / "mutated.pdf"),
            tmp_path / "base" / "raw",
            tmp_path / "base" / "structured",
            bad_out,
        )
    assert not bad_out.exists()


def _mutated_copy(source: Path, target: Path) -> Path:
    target.write_bytes(source.read_bytes() + b"mutation")
    return target
