"""Freeze the evaluation reference: record sha256 of every gold file, the registry and the split file.

After eval/gold/MANIFEST.json exists, the test split is sealed (hook R4 and verify_gold.py) and any change to a gold
file is detected by --check. Hashing reads bytes only; nothing is printed except paths, hashes and codes.

Usage: python eval/freeze.py [--root eval] --write | --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gold_paths(root: Path) -> list[Path]:
    return sorted(p for split in ("dev", "test") for p in (root / "gold" / split).glob("*.json"))


def write_manifest(root: Path) -> dict:
    manifest = {
        "schema_version": 1,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "registry_sha256": _sha(root / "registry.json"),
        "splits_sha256": _sha(root / "splits.json") if (root / "splits.json").is_file() else None,
        "schema_sha256": _sha(Path(__file__).resolve().parent / "gold" / "schema.json"),
        "gold": {p.relative_to(root).as_posix(): _sha(p) for p in _gold_paths(root)},
    }
    (root / "gold" / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def check_manifest(root: Path) -> list[dict]:
    path = root / "gold" / "MANIFEST.json"
    if not path.is_file():
        return [{"code": "MANIFEST_MISSING"}]
    manifest = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    current = {p.relative_to(root).as_posix(): _sha(p) for p in _gold_paths(root)}
    for rel, digest in manifest["gold"].items():
        if current.get(rel) != digest:
            problems.append({"code": "GOLD_CHANGED_AFTER_FREEZE", "file": rel})
    for rel in sorted(set(current) - set(manifest["gold"])):
        problems.append({"code": "GOLD_ADDED_AFTER_FREEZE", "file": rel})
    if _sha(root / "registry.json") != manifest["registry_sha256"]:
        problems.append({"code": "REGISTRY_CHANGED_AFTER_FREEZE"})
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze or check the eval gold manifest.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        manifest = write_manifest(args.root)
        print(f"MANIFEST written: {len(manifest['gold'])} gold files")
        return 0
    problems = check_manifest(args.root)
    for p in problems:
        print(json.dumps(p))
    print(f"manifest check problems={len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
