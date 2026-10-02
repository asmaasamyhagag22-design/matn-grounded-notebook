"""End-to-end tests for register -> extract -> verify_gold -> freeze, on synthetic PDFs built with PyMuPDF."""
from __future__ import annotations

import copy
import json
import shutil
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


COMMIT = "c0ffee" + "0" * 34

SOURCES_HEADER = ("| file | title | publisher | url | pdf_url | license | license_url | doc_type | notes |\n"
                  "|---|---|---|---|---|---|---|---|---|\n")


def make_pdf(path: Path, pages=PAGES) -> None:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=11)
    doc.save(path)


@pytest.fixture(scope="session")
def registered_template(tmp_path_factory) -> Path:
    """Built and registered once per session (5 PDFs + extraction); each test gets its own copy via `root`."""
    template = tmp_path_factory.mktemp("registered-root")
    incoming = template / "incoming"
    incoming.mkdir()
    for i in range(5):
        make_pdf(incoming / f"doc{i}.pdf")
    rows = "\n".join(f"| doc{i}.pdf | Doc {i} | Example Publisher | https://example.org/doc{i} | https://example.org/doc{i}.pdf "
                     f"| CC-BY-4.0 | https://creativecommons.org/licenses/by/4.0/ | report | |" for i in range(5))
    (incoming / "SOURCES.md").write_text(SOURCES_HEADER + rows + "\n", encoding="utf-8")
    splits = {f"doc{i}": {"split": "dev" if i < 3 else "test", "doc_type": "report", "rationale": "test fixture"} for i in range(5)}
    (template / "splits.json").write_text(json.dumps(splits), encoding="utf-8")
    assert register.build_registry(template) == []
    return template


@pytest.fixture()
def root(tmp_path: Path, registered_template: Path) -> Path:
    """A fresh, registered evaluation root per test (a copy, so tests may change anything in it)."""
    copy = tmp_path / "root"
    shutil.copytree(registered_template, copy)
    return copy


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
    key_points = [{"id": f"{doc_id}-kp-{i + 1:02d}", "text": "A point about the pilot.", "kind": "finding",
                   "importance": 1 + i % 3, "section_path": ["Harbor pilot report"], "page_index": p, "page_label": None,
                   "evidence_quote": q}
                  for i, (q, p) in enumerate(quotes)]
    key_numbers = [
        {"id": f"{doc_id}-kn-01", "value_as_written": "64", "label": "review sessions", "unit": "count", "source": "body",
         "page_index": 1, "page_label": None, "evidence_quote": "The team recorded 64 review sessions in total."},
        {"id": f"{doc_id}-kn-02", "value_as_written": "42", "label": "accepted statements", "unit": "count",
         "source": "body", "page_index": 2, "page_label": None,
         "evidence_quote": "Evidence-first review produced 42 accepted statements."},
    ]
    return {"schema_version": 2, "doc_id": doc_id, "split": reg["split"], "source_sha256": reg["sha256"],
            "drafted_by": "test", "body_pages": {"first": 0, "last": 2, "reason": "the whole fixture"},
            "key_points": key_points, "key_numbers": key_numbers, "numbers_note": "Only two numbers carry the message."}


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


def test_hashed_json_files_are_written_with_lf_on_every_platform(root):
    # freeze.py hashes these files; CRLF on Windows would not match an LF checkout on Ubuntu.
    write_gold(root, gold_for(root, "doc0"))
    freeze.write_manifest(root, commit=COMMIT)
    for name in ("registry.json", "gold/MANIFEST.json"):
        assert b"\r\n" not in (root / name).read_bytes(), name


def test_register_refuses_wrong_number_of_pdfs(root):
    (root / "incoming" / "doc4.pdf").unlink()
    assert "INCOMING_NOT_EXACTLY_5_PDFS" in {p["code"] for p in register.build_registry(root)}


def test_register_refuses_missing_source_row(root):
    text = (root / "incoming" / "SOURCES.md").read_text(encoding="utf-8")
    (root / "incoming" / "SOURCES.md").write_text("\n".join(l for l in text.splitlines() if "doc2.pdf" not in l), encoding="utf-8")
    assert "SOURCE_MISSING" in {p["code"] for p in register.build_registry(root)}


@pytest.mark.parametrize("column,value", [("license", "TO CONFIRM (see arXiv abstract page)"), ("pdf_url", ""),
                                          ("license", ""), ("doc_type", ""), ("title", "")])
def test_register_refuses_incomplete_source_rows(root, column, value):
    path = root / "incoming" / "SOURCES.md"
    header = [c.strip() for c in SOURCES_HEADER.splitlines()[0].strip("|").split("|")]
    lines = path.read_text(encoding="utf-8").splitlines()
    for n, line in enumerate(lines):
        if line.startswith("| doc2.pdf"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            cells[header.index(column)] = value
            lines[n] = "| " + " | ".join(cells) + " |"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    problems = register.build_registry(root)
    assert {"code": "SOURCE_INCOMPLETE", "file": "doc2.pdf", "fields": [column]} in problems


def test_register_records_pdf_url_and_license_url(root):
    doc = json.loads((root / "registry.json").read_text(encoding="utf-8"))["documents"][0]
    assert doc["source"]["pdf_url"] == "https://example.org/doc0.pdf"
    assert doc["source"]["license_url"] == "https://creativecommons.org/licenses/by/4.0/"
    assert doc["source"]["url"] == "https://example.org/doc0" and "notes" in doc["source"]


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
    # schema v2 fields
    (lambda g: g["key_points"][0].update(kind="conclusion"), "SCHEMA"),
    (lambda g: g["key_points"][0].pop("section_path"), "SCHEMA"),
    (lambda g: g["key_points"][0].update(section_path=[]), "SCHEMA"),
    (lambda g: g["key_numbers"][0].update(source="chart"), "SCHEMA"),
    (lambda g: g["key_numbers"][0].pop("unit"), "SCHEMA"),
    (lambda g: g["key_numbers"][0].update(label="x" * 81), "SCHEMA"),
    (lambda g: g.pop("body_pages"), "SCHEMA"),
    (lambda g: g["key_points"][0].update(quote_flags=["looks_fine"]), "SCHEMA"),
    # rule 3: every number in a key point's text or a key number's label is in its quote
    (lambda g: g["key_points"][0].update(text="The pilot ran for 12 weeks."), "NUMBER_NOT_IN_QUOTE"),
    (lambda g: g["key_points"][4].update(text="The team recorded 46 review sessions."), "NUMBER_NOT_IN_QUOTE"),
    (lambda g: g["key_points"][1].update(text="It began on 12 March 2025."), "NUMBER_NOT_IN_QUOTE"),
    (lambda g: g["key_numbers"][0].update(label="review sessions in 2025"), "NUMBER_NOT_IN_QUOTE"),
    # body range and spread
    (lambda g: g.update(body_pages={"first": 2, "last": 1, "reason": "x"}), "BODY_PAGES_INVALID"),
    (lambda g: g.update(body_pages={"first": 0, "last": 3, "reason": "x"}), "BODY_PAGES_INVALID"),
    (lambda g: [kp.update(page_index=0, evidence_quote="The pilot tested an evidence-first review workflow.")
                for kp in g["key_points"]], "KEY_POINTS_NOT_SPREAD"),
])
def test_invalid_gold_is_rejected(root, mutate, code):
    gold = gold_for(root, "doc0")
    mutate(gold)
    write_gold(root, gold)
    assert code in codes(verify_gold.verify(root, splits=["dev"]))


def test_numbers_copied_from_the_quote_pass():
    assert verify_gold.numbers_missing("It began on 12 March 2026.", "It began on 12 March 2026 at the harbor office.") == []
    assert verify_gold.numbers_missing("Targets for 2025-2030 and 7.7% growth", "the 2025-2030 plan targets 7.7%") == []
    assert verify_gold.numbers_missing("FY2021 revenue", "revenue in FY2021 rose") == []
    assert verify_gold.numbers_missing("1,024 GPUs", "We used 1,024 GPUs.") == []
    assert verify_gold.numbers_missing("1024 GPUs", "We used 1,024 GPUs.") == [0]  # reformatted: not as printed
    assert verify_gold.numbers_missing("45 cases", "in 145 cases") == [0]  # part of a larger number
    assert verify_gold.numbers_missing("no numbers here", "1, 2, 3") == []


def test_spread_runs_within_body_pages_only(root):
    gold = gold_for(root, "doc0")
    for kp in gold["key_points"]:
        kp.update(page_index=0, evidence_quote="The pilot tested an evidence-first review workflow.")
    gold["body_pages"] = {"first": 0, "last": 0, "reason": "a one-page document body"}
    write_gold(root, gold)
    assert "KEY_POINTS_NOT_SPREAD" not in codes(verify_gold.verify(root, splits=["dev"]))


def test_warnings_for_heading_outside_body_and_duplicate_quotes(root):
    gold = gold_for(root, "doc0")
    gold["key_points"][3]["section_path"] = ["Harbor pilot report", "A heading that is not printed"]
    gold["body_pages"] = {"first": 1, "last": 2, "reason": "page 0 is the title page"}
    gold["key_points"][5]["evidence_quote"] = gold["key_points"][6]["evidence_quote"]
    write_gold(root, gold)
    warnings: list = []
    failures = verify_gold.verify(root, splits=["dev"], warnings=warnings)
    found = {(w["code"], w.get("item")) for w in warnings}
    assert ("SECTION_HEADING_NOT_FOUND", "doc0-kp-04") in found
    assert ("KEY_POINT_OUTSIDE_BODY", "doc0-kp-01") in found
    assert ("DUPLICATE_QUOTE", "doc0-kp-07") in found
    assert "SECTION_HEADING_NOT_FOUND" not in codes(failures)


def test_doc_filter_checks_one_document(root):
    write_gold(root, gold_for(root, "doc0"))
    bad = gold_for(root, "doc1")
    bad["key_points"][0]["page_index"] = 2
    write_gold(root, bad)
    assert verify_gold.verify(root, splits=["dev"], doc="doc0") == []
    assert {f["doc_id"] for f in verify_gold.verify(root, splits=["dev"], doc="doc1")} == {"doc1"}


# ---------- hidden text (reviewer decision 1, Step 0 close-out) ----------
HIDDEN_BY_IMAGE = "An outdated paragraph lies under the cover picture here."
HIDDEN_BY_FILL = "Another outdated paragraph lies under a white panel here."


def _pdf_with_hidden_text(path: Path) -> None:
    doc = pymupdf.open()
    for n, text in enumerate(PAGES):
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=11)
        if n == 0:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), 0)
            pix.clear_with(90)
            page.insert_text((72, 400), HIDDEN_BY_IMAGE, fontsize=11)
            page.insert_image(pymupdf.Rect(60, 380, 560, 415), pixmap=pix)
            page.insert_text((72, 500), HIDDEN_BY_FILL, fontsize=11)
            page.draw_rect(pymupdf.Rect(60, 480, 560, 515), color=None, fill=(1, 1, 1))
    doc.save(path)


@pytest.fixture()
def hidden_root(root):
    _pdf_with_hidden_text(root / "incoming" / "doc0.pdf")
    assert register.build_registry(root) == []
    return root


def test_quote_in_text_hidden_by_an_image_fails(hidden_root):
    gold = gold_for(hidden_root, "doc0")
    gold["key_points"][0]["evidence_quote"] = HIDDEN_BY_IMAGE
    write_gold(hidden_root, gold)
    failures = verify_gold.verify(hidden_root, splits=["dev"])
    assert {"doc_id": "doc0", "item": "doc0-kp-01", "code": "QUOTE_IN_HIDDEN_TEXT", "page_index": 0,
            "cover": "image"} in failures


def test_quote_in_text_hidden_by_a_vector_fill_is_a_warning(hidden_root):
    gold = gold_for(hidden_root, "doc0")
    gold["key_points"][0]["evidence_quote"] = HIDDEN_BY_FILL
    write_gold(hidden_root, gold)
    warnings: list = []
    failures = verify_gold.verify(hidden_root, splits=["dev"], warnings=warnings)
    assert failures == []
    assert {"doc_id": "doc0", "item": "doc0-kp-01", "code": "QUOTE_IN_HIDDEN_TEXT", "page_index": 0,
            "cover": "vector"} in warnings


def test_visible_quotes_on_a_page_with_hidden_text_still_pass(hidden_root):
    write_gold(hidden_root, gold_for(hidden_root, "doc0"))
    warnings: list = []
    assert verify_gold.verify(hidden_root, splits=["dev"], warnings=warnings) == [] and warnings == []


def test_missing_pdf_is_reported_because_hidden_text_cannot_be_checked(root):
    write_gold(root, gold_for(root, "doc0"))
    (root / "incoming" / "doc0.pdf").unlink()
    assert "PDF_MISSING" in codes(verify_gold.verify(root, splits=["dev"]))


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
    freeze.write_manifest(root, commit=COMMIT)
    with pytest.raises(verify_gold.SealedSplitError):
        verify_gold.verify(root, splits=["test"], include_test_before_freeze=True)
    monkeypatch.setenv("EVAL_MILESTONE", "1")
    assert verify_gold.verify(root, splits=["test"]) == []


def test_manifest_detects_changed_gold(root):
    path = write_gold(root, gold_for(root, "doc0"))
    freeze.write_manifest(root, commit=COMMIT)
    assert freeze.check_manifest(root) == []
    data = json.loads(path.read_text(encoding="utf-8"))
    data["key_points"][0]["text"] = "Changed after freeze."
    path.write_text(json.dumps(data), encoding="utf-8")
    assert "GOLD_CHANGED_AFTER_FREEZE" in {p["code"] for p in freeze.check_manifest(root)}


# ---------- extractor provenance (amendment 3) ----------
def test_manifest_records_the_extractor(root):
    write_gold(root, gold_for(root, "doc0"))
    manifest = freeze.write_manifest(root, commit=COMMIT)
    reg = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    assert manifest["extractor"]["name"] == "pymupdf"
    assert manifest["extractor"]["version"] == metadata("pymupdf")["Version"]
    assert manifest["extractor"]["text_call"] and manifest["extractor"] == reg["library"]


def test_manifest_records_split_commit_labels_second_extractor_and_reviews(root):
    write_gold(root, gold_for(root, "doc0"))
    review = root / "gold" / "dev" / "reviews" / "doc0.json"
    review.parent.mkdir(parents=True)
    review.write_text('{"changes": []}\n', encoding="utf-8")
    manifest = freeze.write_manifest(root, commit=COMMIT)
    assert manifest["gold_commit"] == COMMIT
    assert manifest["split"] == {"doc0": "dev", "doc1": "dev", "doc2": "dev", "doc3": "test", "doc4": "test"}
    assert manifest["labels"] == {"created_by": "claude", "review": "independent_subagent", "human_spot_check": "pending"}
    assert list(manifest["reviews"]) == ["gold/dev/reviews/doc0.json"]
    second = manifest["second_extractor"]
    assert second is None or (second["name"] == "pdftotext" and second["version"] and "path" not in second)
    review.write_text('{"changes": ["edited"]}\n', encoding="utf-8")
    assert "REVIEW_CHANGED_AFTER_FREEZE" in {p["code"] for p in freeze.check_manifest(root)}


def _git(cwd, *args):
    import subprocess
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_gold_commit_refuses_uncommitted_gold_and_returns_head_when_clean(root):
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.org")
    _git(root, "config", "user.name", "t")
    path = write_gold(root, gold_for(root, "doc0"))
    with pytest.raises(freeze.GoldNotCommitted):
        freeze.gold_commit(root, root)  # untracked gold
    _git(root, "add", "gold")
    _git(root, "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "gold")
    assert freeze.gold_commit(root, root) == _git(root, "rev-parse", "HEAD")
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(freeze.GoldNotCommitted):
        freeze.gold_commit(root, root)  # modified after the commit


def test_freeze_refuses_when_installed_extractor_differs_from_registry(root, monkeypatch):
    write_gold(root, gold_for(root, "doc0"))
    real = extract_pages.extractor_info()
    monkeypatch.setattr(extract_pages, "extractor_info", lambda: {**real, "version": "0.0"})
    with pytest.raises(freeze.ExtractorMismatch):
        freeze.write_manifest(root, commit=COMMIT)


def test_check_detects_extractor_change_after_freeze(root, monkeypatch):
    write_gold(root, gold_for(root, "doc0"))
    freeze.write_manifest(root, commit=COMMIT)
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
                                     "code": "QUOTE_NOT_ON_PAGE_SECOND_EXTRACTOR", "found_on_pages": [0],
                                     "difference": "page_shift"}]
    assert "evidence-first review workflow" not in json.dumps(report)  # IDs and codes only (standing rule 8)


@pytest.mark.parametrize("name,quote,page,other,expected", [
    ("found on another page", "the pilot tested a workflow", "unrelated text here", "so the pilot tested a workflow", "page_shift"),
    ("line break inside a word", "the evidence-first review workflow", "the evi dence-first re view workflow", "", "whitespace_or_hyphenation"),
    ("hyphen split differently", "a state-of-the-art model", "a state-of-the- art model", "", "whitespace_or_hyphenation"),
    ("symbols differ", "costs rose by 3% (net)", "costs rose by 3 % net", "", "symbols_or_punctuation"),
    ("words reordered or missing", "the team recorded sessions", "sessions the team recorded", "", "reading_order_or_missing"),
])
def test_difference_type(name, quote, page, other, expected):
    texts = {"default": [page, other], "raw": [page, other]}
    assert cross_check.difference_type(quote, texts, 0) == expected, name


@needs_pdftotext
def test_cross_check_without_filter_checks_every_gold_file(root):
    for doc_id in ("doc0", "doc1", "doc2"):
        write_gold(root, gold_for(root, doc_id))
    report = cross_check.cross_check(root, ["dev"])
    assert sorted(report["documents"]) == ["doc0", "doc1", "doc2"] and report["items"] == 36


@needs_pdftotext
def test_cross_check_doc_filter(root):
    write_gold(root, gold_for(root, "doc0"))
    write_gold(root, gold_for(root, "doc1"))
    report = cross_check.cross_check(root, ["dev"], doc="doc1")
    assert list(report["documents"]) == ["doc1"] and report["items"] == 12


@needs_pdftotext
def test_cross_check_respects_the_sealed_test_split(root, monkeypatch):
    monkeypatch.delenv("EVAL_MILESTONE", raising=False)
    write_gold(root, gold_for(root, "doc3"))
    with pytest.raises(verify_gold.SealedSplitError):
        cross_check.cross_check(root, ["test"])
