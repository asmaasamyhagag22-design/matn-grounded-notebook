"""Verify every gold item mechanically against the registered PDF page text.

Checks per gold file: JSON schema; doc_id/split/source sha match registry.json; 10-15 key points and <=10 key numbers
(numbers_note required when fewer than 10); unique IDs; page_index in range; page_label equals the PDF label when the
PDF defines one, otherwise (if given) appears as a standalone line on that page; evidence_quote is 40-250 characters
after normalization (normalize.py) and occurs exactly once on the stated page (so it lies within one page); value_as_written inside the quote (raw and normalized); key points <= 30 words;
page text files unchanged since registration (sha256).
Warnings (not failures): key points do not reach every third of the document.

The test split is sealed: it is read only with EVAL_MILESTONE=1, or before the freeze with --include-test-before-freeze.
Output contains IDs and codes only, never document text (standing rule 8).

Usage: python eval/verify_gold.py [--root eval] [--split dev|test|all] [--include-test-before-freeze] [--json report.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from extract_pages import page_file
from normalize import count_on_page, normalize_text, value_in_quote

SCHEMA = json.loads((Path(__file__).resolve().parent / "gold" / "schema.json").read_text(encoding="utf-8"))
KEY_POINTS_MIN, KEY_POINTS_MAX, KEY_NUMBERS_MAX, MAX_WORDS = 10, 15, 10, 30
QUOTE_MIN_CHARS, QUOTE_MAX_CHARS = 40, 250


class SealedSplitError(RuntimeError):
    pass


def quote_problems(quote: str, page_text: str) -> list[str]:
    """Gold quote rules: 40-250 characters after normalization, and exactly once on the stated page.

    The quote is matched against the text of ONE page, so a quote that runs across a page break is not found
    (QUOTE_NOT_ON_PAGE). Codes only; the caller adds item IDs and counts.
    """
    problems = []
    if not QUOTE_MIN_CHARS <= len(normalize_text(quote)) <= QUOTE_MAX_CHARS:
        problems.append("QUOTE_LENGTH")
    count = count_on_page(quote, page_text)
    if count == 0:
        problems.append("QUOTE_NOT_ON_PAGE")
    elif count > 1:
        problems.append("QUOTE_NOT_UNIQUE_ON_PAGE")
    return problems


def _gold_files(root: Path, split: str) -> list[Path]:
    return sorted((root / "gold" / split).glob("*.json"))


def _check_access(root: Path, splits: list[str], include_test_before_freeze: bool) -> None:
    if "test" not in splits or os.environ.get("EVAL_MILESTONE") == "1":
        return
    frozen = (root / "gold" / "MANIFEST.json").exists()
    if frozen or not include_test_before_freeze:
        raise SealedSplitError("eval/gold/test/ is sealed: run with EVAL_MILESTONE=1"
                               + ("" if frozen else " (or --include-test-before-freeze while drafting)"))


def verify(root: Path, splits: list[str], *, include_test_before_freeze: bool = False, warnings: list | None = None) -> list[dict]:
    _check_access(root, splits, include_test_before_freeze)
    registry = {d["doc_id"]: d for d in json.loads((root / "registry.json").read_text(encoding="utf-8"))["documents"]}
    failures: list[dict] = []
    validator = Draft202012Validator(SCHEMA)

    def fail(doc_id, item, code, **extra):
        failures.append({"doc_id": doc_id, "item": item, "code": code, **extra})

    for split in splits:
        for path in _gold_files(root, split):
            gold = json.loads(path.read_text(encoding="utf-8"))
            doc_id = gold.get("doc_id", path.stem)
            for error in validator.iter_errors(gold):
                fail(doc_id, "/".join(map(str, error.absolute_path)) or "-", "SCHEMA", rule=error.validator)
            reg = registry.get(doc_id)
            if reg is None or path.stem != doc_id:
                fail(doc_id, "-", "UNKNOWN_DOC_OR_FILENAME")
                continue
            if gold.get("split") != reg["split"] or split != reg["split"]:
                fail(doc_id, "-", "SPLIT_MISMATCH")
            if gold.get("source_sha256") != reg["sha256"]:
                fail(doc_id, "-", "SOURCE_SHA_MISMATCH")
            pages = {}
            for index, expected in enumerate(reg["page_text_sha256"]):
                data = page_file(root, doc_id, index).read_bytes() if page_file(root, doc_id, index).is_file() else b""
                if hashlib.sha256(data).hexdigest() != expected:
                    fail(doc_id, f"page:{index}", "PAGE_TEXT_SHA_MISMATCH")
                pages[index] = data.decode("utf-8", errors="replace")
            key_points = gold.get("key_points") or []
            key_numbers = gold.get("key_numbers") or []
            if not KEY_POINTS_MIN <= len(key_points) <= KEY_POINTS_MAX:
                fail(doc_id, "-", "KEY_POINT_COUNT", count=len(key_points))
            if len(key_numbers) > KEY_NUMBERS_MAX:
                fail(doc_id, "-", "KEY_NUMBER_COUNT", count=len(key_numbers))
            if len(key_numbers) < KEY_NUMBERS_MAX and not (gold.get("numbers_note") or "").strip():
                fail(doc_id, "-", "NUMBERS_NOTE_REQUIRED", count=len(key_numbers))
            seen: set[str] = set()
            for item in key_points + key_numbers:
                item_id = str(item.get("id"))
                if item_id in seen:
                    fail(doc_id, item_id, "DUPLICATE_ID")
                seen.add(item_id)
                index = item.get("page_index")
                if not isinstance(index, int) or not 0 <= index < reg["page_count"]:
                    fail(doc_id, item_id, "PAGE_OUT_OF_RANGE")
                    continue
                pdf_label = reg["page_labels"][index]
                label = item.get("page_label")
                if pdf_label and label != pdf_label:
                    fail(doc_id, item_id, "PAGE_LABEL_MISMATCH", pdf_label=pdf_label)
                elif not pdf_label and label is not None and not re.search(
                        r"(?m)^\s*" + re.escape(str(label)) + r"\s*$", pages[index]):
                    fail(doc_id, item_id, "PAGE_LABEL_MISMATCH", pdf_label=None)
                quote = str(item.get("evidence_quote", ""))
                for code in quote_problems(quote, pages[index]):
                    if code == "QUOTE_LENGTH":
                        fail(doc_id, item_id, code, chars=len(normalize_text(quote)), min=QUOTE_MIN_CHARS,
                             max=QUOTE_MAX_CHARS)
                    elif code == "QUOTE_NOT_UNIQUE_ON_PAGE":
                        fail(doc_id, item_id, code, page_index=index, count=count_on_page(quote, pages[index]))
                    else:
                        fail(doc_id, item_id, code, page_index=index)
                if "value_as_written" in item and not value_in_quote(str(item["value_as_written"]), str(item.get("evidence_quote", ""))):
                    fail(doc_id, item_id, "VALUE_NOT_IN_QUOTE")
                if "text" in item and len(str(item["text"]).split()) > MAX_WORDS:
                    fail(doc_id, item_id, "KEY_POINT_TOO_LONG", words=len(str(item["text"]).split()))
            n = reg["page_count"]
            if warnings is not None and n >= 3:
                thirds = {min(2, (kp["page_index"] * 3) // n) for kp in key_points if isinstance(kp.get("page_index"), int)}
                if thirds != {0, 1, 2}:
                    warnings.append({"doc_id": doc_id, "code": "KEY_POINTS_NOT_IN_EVERY_THIRD", "thirds": sorted(thirds)})
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify eval gold files against PDF page text.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--include-test-before-freeze", action="store_true")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    splits = ["dev", "test"] if args.split == "all" else [args.split]
    warnings: list[dict] = []
    try:
        failures = verify(args.root, splits, include_test_before_freeze=args.include_test_before_freeze, warnings=warnings)
    except SealedSplitError as exc:
        print(f"SEALED: {exc}")
        return 3
    counts = {s: len(_gold_files(args.root, s)) for s in splits}
    report = {"splits": splits, "gold_files": counts, "failures": failures, "warnings": warnings}
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for f in failures:
        print(json.dumps(f))
    for w in warnings:
        print("WARNING", json.dumps(w))
    print(f"gold files={counts} failures={len(failures)} warnings={len(warnings)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
