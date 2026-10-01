"""Text-layer health check for every registered PDF page. Flags pages that look scanned or garbled; never OCRs.

Per page, from the registered PyMuPDF text (eval/pages/) and from pdftotext (second extractor, ADR-0002):
  chars           non-whitespace characters
  alpha_ratio     letters / non-whitespace characters
  bad_chars       U+FFFD replacement characters, private-use code points and "(cid:N)" glyph placeholders
  image_coverage  share of the page area covered by images (PyMuPDF image boxes, capped at 1)
  overlap         shared word tokens of the two extractors / the larger token set (None when both are tiny)
Flags (thresholds below):
  NO_TEXT              no text layer at all                                       blocking
  LOOKS_SCANNED        images cover >= 80% of the page and < 200 characters        blocking
  GARBLED              bad glyphs > 1% of characters, or a long page of < 25% letters  blocking
  EXTRACTORS_DISAGREE  overlap < 0.6                                              blocking
  LOW_TEXT             under 200 characters (covers, dividers): information only
The report holds numbers and page indexes only, no document text (standing rule 8).

Usage: python eval/health_check.py [--root eval] [--json report.json]   (exit 1 if any page has a blocking flag)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pymupdf  # eval tooling only (ADR-0001)

import cross_check
from extract_pages import page_file

LOW_TEXT_CHARS = 200
SCANNED_IMAGE_COVERAGE = 0.8
BAD_CHAR_RATIO = 0.01
GARBLED_ALPHA_RATIO = 0.25
OVERLAP_MIN = 0.6
OVERLAP_MIN_TOKENS = 20
BLOCKING = {"NO_TEXT", "LOOKS_SCANNED", "GARBLED", "EXTRACTORS_DISAGREE"}
_BAD = re.compile(r"�|[-]|\(cid:\d+\)")


def bad_chars(text: str) -> int:
    return len(_BAD.findall(text))


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def token_overlap(a: str, b: str) -> float | None:
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return None
    return round(len(ta & tb) / max(len(ta), len(tb)), 4)


def classify(m: dict) -> list[str]:
    if m["chars"] == 0:
        return ["NO_TEXT"]
    flags = []
    if m["image_coverage"] >= SCANNED_IMAGE_COVERAGE and m["chars"] < LOW_TEXT_CHARS:
        flags.append("LOOKS_SCANNED")
    if m["chars"] < LOW_TEXT_CHARS:
        flags.append("LOW_TEXT")
    if m["bad_chars"] / m["chars"] > BAD_CHAR_RATIO or (m["chars"] >= LOW_TEXT_CHARS and m["alpha_ratio"] < GARBLED_ALPHA_RATIO):
        flags.append("GARBLED")
    if m["overlap"] is not None and m["overlap"] < OVERLAP_MIN:
        flags.append("EXTRACTORS_DISAGREE")
    return flags


def _image_coverage(page: pymupdf.Page) -> float:
    area = abs(page.rect)
    covered = sum(abs(pymupdf.Rect(info["bbox"]) & page.rect) for info in page.get_image_info())
    return round(min(1.0, covered / area), 4) if area else 0.0


def page_metrics(text: str, second: str | None, page: pymupdf.Page) -> dict:
    visible = re.sub(r"\s+", "", text)
    tokens, second_tokens = len(_tokens(text)), (len(_tokens(second)) if second is not None else None)
    overlap = None
    if second is not None and max(tokens, second_tokens) >= OVERLAP_MIN_TOKENS:
        overlap = token_overlap(text, second)
    m = {"chars": len(visible), "alpha_ratio": round(sum(c.isalpha() for c in visible) / len(visible), 4) if visible else 0.0,
         "bad_chars": bad_chars(text), "image_coverage": _image_coverage(page), "tokens": tokens,
         "second_tokens": second_tokens, "overlap": overlap}
    m["flags"] = classify(m)
    return m


def check_pdf(pdf: Path, texts: list[str] | None = None) -> list[dict]:
    """Metrics per page; `texts` is the registered PyMuPDF text (extracted here when not given)."""
    extractor = cross_check.second_extractor()
    second = cross_check.pages_text(extractor["path"], pdf, "default") if extractor else None
    report = []
    with pymupdf.open(pdf) as doc:
        for page in doc:
            text = texts[page.number] if texts is not None else page.get_text("text")
            other = second[page.number] if second is not None and page.number < len(second) else None
            report.append({"page_index": page.number, **page_metrics(text, other, page)})
    return report


def check_registry(root: Path) -> dict:
    registry = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    extractor = cross_check.second_extractor()
    out = {"second_extractor": extractor, "thresholds": {
        "low_text_chars": LOW_TEXT_CHARS, "scanned_image_coverage": SCANNED_IMAGE_COVERAGE, "bad_char_ratio": BAD_CHAR_RATIO,
        "garbled_alpha_ratio": GARBLED_ALPHA_RATIO, "overlap_min": OVERLAP_MIN, "overlap_min_tokens": OVERLAP_MIN_TOKENS},
        "documents": {}}
    for doc in registry["documents"]:
        texts = [page_file(root, doc["doc_id"], i).read_text(encoding="utf-8") for i in range(doc["page_count"])]
        pages = check_pdf(root / doc["file"], texts)
        flagged = {}
        for p in pages:
            for flag in p["flags"]:
                flagged.setdefault(flag, []).append(p["page_index"])
        out["documents"][doc["doc_id"]] = {"split": doc["split"], "page_count": doc["page_count"], "flagged": flagged,
                                           "blocking": sorted(BLOCKING & set(flagged)), "pages": pages}
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Text-layer health check of the registered evaluation PDFs.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    report = check_registry(args.root)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    blocking = False
    for doc_id, doc in report["documents"].items():
        print(f"{doc_id:34} pages={doc['page_count']:3} flagged={json.dumps(doc['flagged'])}")
        blocking |= bool(doc["blocking"])
    print(f"blocking={blocking}")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
