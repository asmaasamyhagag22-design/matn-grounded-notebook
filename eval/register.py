"""Register the evaluation PDFs: sha256, page count, page labels, text layer, public source, split.

Inputs (under --root, default eval/):
  incoming/*.pdf       exactly 5 public PDFs (git-ignored; pinned by sha256 here)
  incoming/SOURCES.md  markdown table: | file | title | publisher | url | license | doc_type |
  splits.json          {doc_id: {"split": "dev"|"test", "doc_type": str, "rationale": str}}  (optional on a first run)
Output: registry.json, and pages/<doc_id>/pNNNN.txt via extract_pages.

Usage: python eval/register.py [--root eval] [--allow-missing-splits]
Exit code 0 only when every gate passes; problems are printed as codes (no document text).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import extract_pages

EXPECTED_PDFS = 5


def doc_id_for(path: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")[:48]


def parse_sources(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not path.is_file():
        return rows
    header: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        row = dict(zip(header, cells))
        if row.get("file"):
            rows[row["file"]] = row
    return rows


def build_registry(root: Path, *, allow_missing_splits: bool = False) -> list[dict]:
    problems: list[dict] = []
    incoming = root / "incoming"
    pdfs = sorted(incoming.glob("*.pdf"))
    others = sorted(p.name for p in incoming.iterdir() if p.is_file() and p.suffix.lower() != ".pdf" and p.name != "SOURCES.md") if incoming.is_dir() else []
    if len(pdfs) != EXPECTED_PDFS or others:
        problems.append({"code": "INCOMING_NOT_EXACTLY_5_PDFS", "pdfs": len(pdfs), "other_files": others})
    sources_path = incoming / "SOURCES.md"
    if not sources_path.is_file():
        problems.append({"code": "SOURCES_MD_MISSING"})
    sources = parse_sources(sources_path)
    splits_path = root / "splits.json"
    splits = json.loads(splits_path.read_text(encoding="utf-8")) if splits_path.is_file() else {}
    registry = {"schema_version": 1, "library": extract_pages.extractor_info(), "documents": []}
    for pdf in pdfs:
        doc_id = doc_id_for(pdf)
        data = pdf.read_bytes()
        info = extract_pages.extract(pdf, root, doc_id)
        source = sources.get(pdf.name)
        if not source or not source.get("url") or not source.get("publisher"):
            problems.append({"code": "SOURCE_MISSING", "file": pdf.name})
        if info["pages_without_text"]:
            problems.append({"code": "PAGE_WITHOUT_TEXT", "doc_id": doc_id, "pages": info["pages_without_text"]})
        split = splits.get(doc_id, {})
        if split.get("split") not in {"dev", "test"} and not allow_missing_splits:
            problems.append({"code": "SPLIT_MISSING", "doc_id": doc_id})
        registry["documents"].append({
            "doc_id": doc_id, "file": f"incoming/{pdf.name}", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            **info,
            "source": {k: (source or {}).get(k, "") for k in ("title", "publisher", "url", "license")},
            "doc_type": split.get("doc_type") or (source or {}).get("doc_type", ""),
            "split": split.get("split"), "split_rationale": split.get("rationale", ""),
        })
    counts = {s: sum(d["split"] == s for d in registry["documents"]) for s in ("dev", "test")}
    if not allow_missing_splits and (counts["dev"], counts["test"]) != (3, 2) and len(pdfs) == EXPECTED_PDFS:
        problems.append({"code": "SPLIT_NOT_3_DEV_2_TEST", "counts": counts})
    registry["split_counts"] = counts
    (root / "registry.json").write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--allow-missing-splits", action="store_true")
    args = parser.parse_args(argv)
    problems = build_registry(args.root, allow_missing_splits=args.allow_missing_splits)
    for p in problems:
        print(json.dumps(p))
    print(f"registry: {args.root / 'registry.json'} problems={len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
