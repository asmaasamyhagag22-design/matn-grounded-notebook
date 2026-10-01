"""End-to-end tests for register -> extract -> verify_gold -> freeze, on synthetic PDFs built with PyMuPDF."""
from __future__ import annotations

import copy
import json
from importlib.metadata import metadata
from pathlib import Path

import pymupdf
import pytest

import cross_check
import extract_pages
import freeze
import register
import verify_gold

PAGES = [
    "Harbor pilot report\nThe pilot tested an evidence-first review workflow.\n"
    "It began on 12 March 2026 at the harbor office.\nReviewers checked every claim against its source page.\n1",
    "Eight volunteers reviewed short technical notes each week.\nThe team recorded 64 review sessions in total.\n"
    "The median session lasted 18 minutes per note.\nNotes without a source page were returned to authors.\n2",
    "Evidence-first review produced 42 accepted statements.\nThe pilot was too small for a general claim.\n"
    "A larger study would need several hundred notes.\nThe checklist line was printed twice by mistake.\n"
    "The checklist line was printed twice by mistake.\n3",
]


def make_pdf(path: Path, pages=PAGES) -> None:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=11)
    doc.save(path)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    for i in range(5):
        make_pdf(incoming / f"doc{i}.pdf")
    rows = "\n".join(f"| doc{i}.pdf | Doc {i} | Example Publisher | https://example.org/doc{i}.pdf | CC-BY-4.0 | report |"
                     for i in range(5))
    (incoming / "SOURCES.md").write_text(
        "| file | title | publisher | url | license | doc_type |\n|---|---|---|---|---|---|\n" + rows + "\n", encoding="utf-8")
    splits = {f"doc{i}": {"split": "dev" if i < 3 else "test", "doc_type": "report", "rationale": "test fixture"} for i in range(5)}
    (tmp_path / "splits.json").write_text(json.dumps(splits), encoding="utf-8")
    assert register.build_registry(tmp_path) == []
    return tmp_path


def gold_for(root: Path, doc_id: str) -> dict:
    reg = {d["doc_id"]: d for d in json.loads((root / "registry.json").read_text(encoding="utf-8"))["documents"]}[doc_id]
    quotes = [("The pilot tested an evidence-first review workflow.", 0),
              ("It began on 12 March 2026 at the harbor office.", 0),
              ("Reviewers checked every claim against its source page.", 0),
              ("Eight volunteers reviewed short technical notes each week.", 1),
              ("The team recorded 64 review sessions in total.", 1),
              ("The median session lasted 18 minutes per note.", 1),
              ("Notes without a source page were returned to authors.", 1),
              ("Evidence-first review produced 42 accepted statements.", 2),
              ("The pilot was too small for a general claim.", 2),
              ("A larger study would need several hundred notes.", 2)]
    key_points = [{"id": f"{doc_id}-kp-{i + 1:02d}", "text": f"Point {i + 1} about the pilot.", "importance": 1 + i % 3,
                   "category": "finding", "page_index": p, "page_label": None, "evidence_quote": q}
                  for i, (q, p) in enumerate(quotes)]
    key_numbers = [
        {"id": f"{doc_id}-kn-01", "value_as_written": "64", "description": "review sessions", "page_index": 1,
         "page_label": None, "evidence_quote": "The team recorded 64 review sessions in total."},
        {"id": f"{doc_id}-kn-02", "value_as_written": "42", "description": "accepted statements", "page_index": 2,
         "page_label": None, "evidence_quote": "Evidence-first review produced 42 accepted statements."},
    ]
    return {"schema_version": 1, "doc_id": doc_id, "split": reg["split"], "source_sha256": reg["sha256"],
            "drafted_by": "test", "key_points": key_points, "key_numbers": key_numbers,
            "numbers_note": "Only two numbers carry the message."}


def write_gold(root: Path, gold: dict) -> Path:
    path = root / "gold" / gold["split"] / f"{gold['doc_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(gold, indent=2), encoding="utf-8")
    return path


def codes(failures) -> set[str]:
    return {f["code"] for f in failures}


# ---------- registration gates ----------
def test_register_records_hashes_pages_labels_and_sources(root):
    reg = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    assert reg["library"]["name"] == "pymupdf" and reg["library"]["version"]
    doc = reg["documents"][0]
    assert len(doc["sha256"]) == 64 and doc["page_count"] == 3 and len(doc["page_labels"]) == 3
    assert doc["source"]["url"].startswith("https://") and doc["pages_without_text"] == []
    assert (root / "pages" / doc["doc_id"] / "p0001.txt").is_file()


def test_register_refuses_wrong_number_of_pdfs(root):
    (root / "incoming" / "doc4.pdf").unlink()
    assert "INCOMING_NOT_EXACTLY_5_PDFS" in {p["code"] for p in register.build_registry(root)}


def test_register_refuses_missing_source_row(root):
    text = (root / "incoming" / "SOURCES.md").read_text(encoding="utf-8")
    (root / "incoming" / "SOURCES.md").write_text("\n".join(l for l in text.splitlines() if "doc2.pdf" not in l), encoding="utf-8")
    assert "SOURCE_MISSING" in {p["code"] for p in register.build_registry(root)}


def test_register_refuses_pages_without_text(root):
    doc = pymupdf.open()
    doc.new_page()  # blank page: no text layer
    doc.save(root / "incoming" / "doc4.pdf")
    assert "PAGE_WITHOUT_TEXT" in {p["code"] for p in register.build_registry(root)}


# ---------- verification ----------
def test_valid_gold_passes(root):
    write_gold(root, gold_for(root, "doc0"))
    assert verify_gold.verify(root, splits=["dev"]) == []


@pytest.mark.parametrize("mutate,code", [
    (lambda g: g["key_points"][0].update(page_index=2), "QUOTE_NOT_ON_PAGE"),
    (lambda g: g["key_points"][0].update(evidence_quote="The pilot tested a review workflow."), "QUOTE_NOT_ON_PAGE"),
    (lambda g: g["key_numbers"][0].update(value_as_written="46"), "VALUE_NOT_IN_QUOTE"),
    (lambda g: g["key_points"][1].update(id=g["key_points"][0]["id"]), "DUPLICATE_ID"),
    (lambda g: g["key_points"][0].update(page_index=9), "PAGE_OUT_OF_RANGE"),
    (lambda g: g["key_points"][0].update(text=" ".join(["word"] * 31)), "KEY_POINT_TOO_LONG"),
    (lambda g: g.update(key_points=g["key_points"][:9]), "KEY_POINT_COUNT"),
    (lambda g: g.update(source_sha256="0" * 64), "SOURCE_SHA_MISMATCH"),
    (lambda g: g["key_points"][0].update(page_label="99"), "PAGE_LABEL_MISMATCH"),
    (lambda g: g.pop("numbers_note"), "NUMBERS_NOTE_REQUIRED"),
    (lambda g: g["key_points"][0].update(importance=5), "SCHEMA"),
    (lambda g: g["key_points"][0].update(evidence_quote="an evidence-first review workflow."), "QUOTE_LENGTH"),
    (lambda g: g["key_points"][0].update(evidence_quote="The pilot tested " + "a" * 240), "QUOTE_LENGTH"),
    (lambda g: g["key_points"][9].update(evidence_quote="The checklist line was printed twice by mistake."),
     "QUOTE_NOT_UNIQUE_ON_PAGE"),
])
def test_invalid_gold_is_rejected(root, mutate, code):
    gold = gold_for(root, "doc0")
    mutate(gold)
    write_gold(root, gold)
    assert code in codes(verify_gold.verify(root, splits=["dev"]))


# ---------- gold quote rules (Step 0 part 2, amendment B2) ----------
@pytest.mark.parametrize("chars,expected", [(39, ["QUOTE_LENGTH"]), (40, []), (250, []), (251, ["QUOTE_LENGTH"])])
def test_quote_length_bounds(chars, expected):
    quote = ("word " * 60)[:chars - 1].rstrip() + "x" * (chars - len(("word " * 60)[:chars - 1].rstrip()))
    assert len(quote) == chars
    assert verify_gold.quote_problems(quote, f"Start. {quote} End.") == expected


def test_quote_length_is_counted_after_normalization():
    page = "The   pilot\n tested an evidence-first   review workflow."  # 57 raw chars, 51 after normalization
    assert verify_gold.quote_problems(page, page) == []
    assert verify_gold.quote_problems("The   pilot\n tested   an  evidence", page) == ["QUOTE_LENGTH"]  # 28


def test_quote_must_appear_exactly_once_on_its_page():
    page = "Rates rose sharply in the second quarter of the year. Rates rose sharply in the second quarter of the year."
    assert verify_gold.quote_problems("Rates rose sharply in the second quarter of the year.", page) == [
        "QUOTE_NOT_UNIQUE_ON_PAGE"]
    assert verify_gold.quote_problems("Rates rose sharply in the second quarter of the year.", page[:54]) == []


def test_quote_must_lie_within_a_single_page():
    page_3 = "The final section of the report discusses the"
    page_4 = "limitations of the pilot study and next steps."
    quote = "discusses the limitations of the pilot study and next steps"
    assert verify_gold.quote_problems(quote, page_3) == ["QUOTE_NOT_ON_PAGE"]
    assert verify_gold.quote_problems(quote, page_4) == ["QUOTE_NOT_ON_PAGE"]


def test_quote_rule_failures_carry_ids_and_counts_not_text(root):
    gold = gold_for(root, "doc0")
    gold["key_points"][9]["evidence_quote"] = "The checklist line was printed twice by mistake."
    gold["key_points"][0]["evidence_quote"] = "an evidence-first review workflow."
    write_gold(root, gold)
    failures = verify_gold.verify(root, splits=["dev"])
    assert {"doc_id": "doc0", "item": "doc0-kp-10", "code": "QUOTE_NOT_UNIQUE_ON_PAGE", "page_index": 2,
            "count": 2} in failures
    assert {"doc_id": "doc0", "item": "doc0-kp-01", "code": "QUOTE_LENGTH", "chars": 34, "min": 40,
            "max": 250} in failures
    assert "printed twice" not in json.dumps(failures)


def test_printed_page_label_must_appear_on_page(root):
    gold = gold_for(root, "doc0")
    gold["key_points"][3]["page_label"] = "2"  # page 1 (0-based) prints "2" on its own line
    write_gold(root, gold)
    assert verify_gold.verify(root, splits=["dev"]) == []


def test_changed_page_text_is_detected(root):
    write_gold(root, gold_for(root, "doc0"))
    (root / "pages" / "doc0" / "p0001.txt").write_text("tampered", encoding="utf-8")
    assert "PAGE_TEXT_SHA_MISMATCH" in codes(verify_gold.verify(root, splits=["dev"]))


def test_failures_never_contain_document_text(root):
    gold = gold_for(root, "doc0")
    gold["key_points"][0]["page_index"] = 2
    write_gold(root, gold)
    blob = json.dumps(verify_gold.verify(root, splits=["dev"]))
    assert "evidence-first review workflow" not in blob  # IDs and codes only (standing rule 8)


# ---------- test split sealing and freeze ----------
def test_test_split_needs_flag_before_freeze_and_milestone_after(root, monkeypatch):
    monkeypatch.delenv("EVAL_MILESTONE", raising=False)
    write_gold(root, gold_for(root, "doc3"))
    with pytest.raises(verify_gold.SealedSplitError):
        verify_gold.verify(root, splits=["test"])
    assert verify_gold.verify(root, splits=["test"], include_test_before_freeze=True) == []
    write_gold(root, gold_for(root, "doc0"))
    freeze.write_manifest(root)
    with pytest.raises(verify_gold.SealedSplitError):
        verify_gold.verify(root, splits=["test"], include_test_before_freeze=True)
    monkeypatch.setenv("EVAL_MILESTONE", "1")
    assert verify_gold.verify(root, splits=["test"]) == []


def test_manifest_detects_changed_gold(root):
    path = write_gold(root, gold_for(root, "doc0"))
    freeze.write_manifest(root)
    assert freeze.check_manifest(root) == []
    data = json.loads(path.read_text(encoding="utf-8"))
    data["key_points"][0]["text"] = "Changed after freeze."
    path.write_text(json.dumps(data), encoding="utf-8")
    assert "GOLD_CHANGED_AFTER_FREEZE" in {p["code"] for p in freeze.check_manifest(root)}


# ---------- extractor provenance (amendment 3) ----------
def test_manifest_records_the_extractor(root):
    write_gold(root, gold_for(root, "doc0"))
    manifest = freeze.write_manifest(root)
    reg = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    assert manifest["extractor"]["name"] == "pymupdf"
    assert manifest["extractor"]["version"] == metadata("pymupdf")["Version"]
    assert manifest["extractor"]["text_call"] and manifest["extractor"] == reg["library"]


def test_freeze_refuses_when_installed_extractor_differs_from_registry(root, monkeypatch):
    write_gold(root, gold_for(root, "doc0"))
    real = extract_pages.extractor_info()
    monkeypatch.setattr(extract_pages, "extractor_info", lambda: {**real, "version": "0.0"})
    with pytest.raises(freeze.ExtractorMismatch):
        freeze.write_manifest(root)


def test_check_detects_extractor_change_after_freeze(root, monkeypatch):
    write_gold(root, gold_for(root, "doc0"))
    freeze.write_manifest(root)
    real = extract_pages.extractor_info()
    monkeypatch.setattr(extract_pages, "extractor_info", lambda: {**real, "version": "0.0"})
    assert "EXTRACTOR_CHANGED_AFTER_FREEZE" in {p["code"] for p in freeze.check_manifest(root)}


# ---------- second-extractor cross-check (amendment 3) ----------
needs_pdftotext = pytest.mark.skipif(cross_check.second_extractor() is None, reason="pdftotext not on PATH")


@needs_pdftotext
def test_cross_check_counts_quotes_that_also_verify_with_pdftotext(root):
    write_gold(root, gold_for(root, "doc0"))
    report = cross_check.cross_check(root, ["dev"])
    assert report["extractor"]["name"] == "pdftotext" and report["extractor"]["version"]
    assert report["items"] == 12 and report["verified"] == 12 and report["mismatches"] == []


@needs_pdftotext
def test_cross_check_reports_mismatches_with_ids_only(root):
    gold = gold_for(root, "doc0")
    gold["key_points"][0]["page_index"] = 2  # the quote is on page 0
    write_gold(root, gold)
    report = cross_check.cross_check(root, ["dev"])
    assert report["verified"] == 11
    assert report["mismatches"] == [{"doc_id": "doc0", "item": "doc0-kp-01", "page_index": 2,
                                     "code": "QUOTE_NOT_ON_PAGE_SECOND_EXTRACTOR", "found_on_pages": [0]}]
    assert "evidence-first review workflow" not in json.dumps(report)  # IDs and codes only (standing rule 8)


@needs_pdftotext
def test_cross_check_respects_the_sealed_test_split(root, monkeypatch):
    monkeypatch.delenv("EVAL_MILESTONE", raising=False)
    write_gold(root, gold_for(root, "doc3"))
    with pytest.raises(verify_gold.SealedSplitError):
        cross_check.cross_check(root, ["test"])
