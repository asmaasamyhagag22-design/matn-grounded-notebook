"""Freeze the evaluation reference: record sha256 of every gold file, its review log, the registry and the split file.

After eval/gold/MANIFEST.json exists, the test split is sealed (hook R4 and verify_gold.py) and any change to a gold
file or a review log is detected by --check. The manifest also records:
- the primary text extractor (name, version, MuPDF version, call) that produced eval/pages/: --write refuses if the
  installed extractor differs from the one recorded at registration, and --check reports
  EXTRACTOR_CHANGED_AFTER_FREEZE if it changes later, because the gold quotes were verified against its text;
- the second extractor used by cross_check.py (pdftotext name, vendor, version; ADR-0002);
- the split of every document (from registry.json);
- gold_commit: the commit that holds the gold. --write refuses while any file under gold/ differs from HEAD or is
  untracked, so the manifest always points at committed gold;
- the labels of the reference: created_by=claude, review=independent_subagent, human_spot_check=pending.
Hashing reads bytes only; nothing is printed except paths, hashes and codes.

Usage: python eval/freeze.py [--root eval] --write | --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import cross_check
import extract_pages

REPO = Path(__file__).resolve().parents[1]
LABELS = {"created_by": "claude", "review": "independent_subagent", "human_spot_check": "pending"}


class ExtractorMismatch(RuntimeError):
    pass


class GoldNotCommitted(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gold_paths(root: Path) -> list[Path]:
    return sorted(p for split in ("dev", "test") for p in (root / "gold" / split).glob("*.json"))


def _review_paths(root: Path) -> list[Path]:
    return sorted(p for split in ("dev", "test") for p in (root / "gold" / split / "reviews").glob("*.json"))


def _second_extractor() -> dict | None:
    found = cross_check.second_extractor()
    return {k: found[k] for k in ("name", "vendor", "version")} if found else None  # no machine path


def gold_commit(repo: Path, root: Path) -> str:
    """HEAD of `repo`, provided every file under <root>/gold is committed unchanged; else GoldNotCommitted."""
    gold = (root / "gold").resolve()
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", str(gold)], cwd=repo,
                            capture_output=True, text=True, check=True).stdout
    if status.strip():
        raise GoldNotCommitted(f"{len(status.splitlines())} file(s) under gold/ are not committed: commit the gold first")
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def write_manifest(root: Path, *, commit: str) -> dict:
    registry = json.loads((root / "registry.json").read_text(encoding="utf-8"))
    installed = extract_pages.extractor_info()
    if registry.get("library") != installed:
        raise ExtractorMismatch(f"registry.json was built with {registry.get('library')}, installed is {installed}: "
                                "re-register first")
    manifest = {
        "schema_version": 2,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gold_commit": commit,
        "labels": LABELS,
        "split": {d["doc_id"]: d["split"] for d in registry["documents"]},
        "registry_sha256": _sha(root / "registry.json"),
        "splits_sha256": _sha(root / "splits.json") if (root / "splits.json").is_file() else None,
        "schema_sha256": _sha(Path(__file__).resolve().parent / "gold" / "schema.json"),
        "extractor": installed,
        "second_extractor": _second_extractor(),
        "gold": {p.relative_to(root).as_posix(): _sha(p) for p in _gold_paths(root)},
        "reviews": {p.relative_to(root).as_posix(): _sha(p) for p in _review_paths(root)},
    }
    (root / "gold" / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


def check_manifest(root: Path) -> list[dict]:
    path = root / "gold" / "MANIFEST.json"
    if not path.is_file():
        return [{"code": "MANIFEST_MISSING"}]
    manifest = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    for kind, paths in (("GOLD", _gold_paths(root)), ("REVIEW", _review_paths(root))):
        frozen = manifest.get("gold" if kind == "GOLD" else "reviews", {})
        current = {p.relative_to(root).as_posix(): _sha(p) for p in paths}
        for rel, digest in frozen.items():
            if current.get(rel) != digest:
                problems.append({"code": f"{kind}_CHANGED_AFTER_FREEZE", "file": rel})
        for rel in sorted(set(current) - set(frozen)):
            problems.append({"code": f"{kind}_ADDED_AFTER_FREEZE", "file": rel})
    if _sha(root / "registry.json") != manifest["registry_sha256"]:
        problems.append({"code": "REGISTRY_CHANGED_AFTER_FREEZE"})
    if manifest.get("extractor") != extract_pages.extractor_info():
        problems.append({"code": "EXTRACTOR_CHANGED_AFTER_FREEZE", "frozen": manifest.get("extractor"),
                         "installed": extract_pages.extractor_info()})
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze or check the eval gold manifest.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        try:
            manifest = write_manifest(args.root, commit=gold_commit(REPO, args.root))
        except (ExtractorMismatch, GoldNotCommitted) as exc:
            print(f"REFUSED: {exc}")
            return 1
        print(f"MANIFEST written: {len(manifest['gold'])} gold files, {len(manifest['reviews'])} review logs, "
              f"gold_commit={manifest['gold_commit']}")
        return 0
    problems = check_manifest(args.root)
    for p in problems:
        print(json.dumps(p))
    print(f"manifest check problems={len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
