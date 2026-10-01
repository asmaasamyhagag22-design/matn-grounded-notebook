"""Re-verify gold quotes against a SECOND text extractor, so the gold does not depend on one extractor's quirks.

The gold is drafted and verified against PyMuPDF text (eval/pages/, see extract_pages.py). This script extracts the
same PDFs with pdftotext (Xpdf or Poppler; nothing is installed: it uses the one on PATH, or $MATN_PDFTOTEXT) in two
modes: "default" (reading order) and "raw" (content-stream order). It then checks each evidence_quote with the same
normalization and word-boundary rule as verify_gold.py. An item counts as verified if its quote is on the stated page
in either mode.

Mismatches are REPORTED, never fixed: the report lists item IDs, page indexes, codes, a difference type (see
difference_type) and the pages where the quote was found instead. It never contains document text (standing
rule 8). The test split stays sealed as in verify_gold.py.

Usage: python eval/cross_check.py [--root eval] [--split dev|test|all] [--include-test-before-freeze] [--doc DOC_ID]
                                  [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from normalize import normalize_text, quote_on_page
from verify_gold import SealedSplitError, _check_access, _gold_files

MODES = {"default": [], "raw": ["-raw"]}


def second_extractor() -> dict | None:
    """Name, version and path of the pdftotext on this machine, or None."""
    exe = os.environ.get("MATN_PDFTOTEXT") or shutil.which("pdftotext")
    if not exe:
        return None
    banner = subprocess.run([exe, "-v"], capture_output=True, text=True)
    text = banner.stdout + banner.stderr
    version = re.search(r"pdftotext version (\S+)", text)
    vendor = "Xpdf" if "xpdfreader" in text.lower() else "Poppler" if "poppler" in text.lower() else "unknown"
    return {"name": "pdftotext", "vendor": vendor, "version": version.group(1) if version else None, "path": exe}


def pages_text(exe: str, pdf: Path, mode: str) -> list[str]:
    """Per-page text; pdftotext ends every page with a form feed."""
    out = subprocess.run([exe, "-enc", "UTF-8", "-eol", "unix", "-q", *MODES[mode], str(pdf), "-"],
                         capture_output=True, check=True).stdout.decode("utf-8", errors="replace")
    pages = out.split("\f")
    return pages[:-1] if pages and not pages[-1].strip() else pages


def difference_type(quote: str, texts: dict[str, list[str]], index: int) -> str:
    """Why a quote is not on its stated page in the second extractor (checked in this order):

    page_shift                 the quote is on another page;
    whitespace_or_hyphenation  it matches once all spaces and line breaks are ignored;
    symbols_or_punctuation     it matches on letters and digits alone;
    reading_order_or_missing   otherwise (text runs in another order, or text the extractor does not return).
    """
    if any(quote_on_page(quote, page) for pages in texts.values() for i, page in enumerate(pages) if i != index):
        return "page_shift"
    stated = [pages[index] for pages in texts.values() if index < len(pages)]

    def squeeze(text: str, pattern: str) -> str:
        return re.sub(pattern, "", normalize_text(text).casefold())

    for kind, pattern in (("whitespace_or_hyphenation", r"\s+"), ("symbols_or_punctuation", r"[^\w]|_")):
        if any(squeeze(quote, pattern) in squeeze(page, pattern) for page in stated):
            return kind
    return "reading_order_or_missing"


def cross_check(root: Path, splits: list[str], *, include_test_before_freeze: bool = False, doc: str | None = None) -> dict:
    _check_access(root, splits, include_test_before_freeze)
    extractor = second_extractor()
    if extractor is None:
        raise RuntimeError("no second extractor: pdftotext is not on PATH (and MATN_PDFTOTEXT is not set)")
    registry = {d["doc_id"]: d for d in json.loads((root / "registry.json").read_text(encoding="utf-8"))["documents"]}
    report = {"extractor": extractor, "modes": list(MODES), "items": 0, "verified": 0,
              "verified_by_mode": {m: 0 for m in MODES}, "documents": {}, "mismatches": [], "page_count_mismatches": []}
    for split in splits:
        for path in _gold_files(root, split):
            if doc is not None and path.stem != doc:
                continue
            gold = json.loads(path.read_text(encoding="utf-8"))
            doc_id = gold["doc_id"]
            reg = registry[doc_id]
            texts = {m: pages_text(extractor["path"], root / reg["file"], m) for m in MODES}
            for mode, pages in texts.items():
                if len(pages) != reg["page_count"]:
                    report["page_count_mismatches"].append({"doc_id": doc_id, "mode": mode, "pages": len(pages),
                                                            "registry": reg["page_count"]})
            counts = {"items": 0, "verified": 0}
            for item in gold.get("key_points", []) + gold.get("key_numbers", []):
                quote, index = str(item.get("evidence_quote", "")), item.get("page_index")
                on_page = {m: isinstance(index, int) and index < len(p) and quote_on_page(quote, p[index])
                           for m, p in texts.items()}
                counts["items"] += 1
                for mode, ok in on_page.items():
                    report["verified_by_mode"][mode] += ok
                if any(on_page.values()):
                    counts["verified"] += 1
                    continue
                found = sorted({i for p in texts.values() for i, page in enumerate(p) if quote_on_page(quote, page)})
                report["mismatches"].append({"doc_id": doc_id, "item": item.get("id"), "page_index": index,
                                             "code": "QUOTE_NOT_ON_PAGE_SECOND_EXTRACTOR", "found_on_pages": found,
                                             "difference": difference_type(quote, texts, index) if isinstance(index, int)
                                             else "page_out_of_range"})
            report["documents"][doc_id] = counts
            report["items"] += counts["items"]
            report["verified"] += counts["verified"]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-verify gold quotes against a second PDF text extractor.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--include-test-before-freeze", action="store_true")
    parser.add_argument("--doc", help="check only this doc_id")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    splits = ["dev", "test"] if args.split == "all" else [args.split]
    try:
        report = cross_check(args.root, splits, include_test_before_freeze=args.include_test_before_freeze, doc=args.doc)
    except SealedSplitError as exc:
        print(f"SEALED: {exc}")
        return 3
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    for m in report["mismatches"] + report["page_count_mismatches"]:
        print(json.dumps(m))
    e = report["extractor"]
    print(f"second extractor={e['name']} {e['vendor']} {e['version']} items={report['items']} "
          f"verified={report['verified']} by_mode={report['verified_by_mode']} mismatches={len(report['mismatches'])}")
    return 1 if report["mismatches"] or report["page_count_mismatches"] else 0


if __name__ == "__main__":
    sys.exit(main())
