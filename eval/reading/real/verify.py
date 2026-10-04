"""Gate for the real-scan benchmark: a PDF is measured only if its sha256 equals the one in sources.json.

Every measurement entry point calls ``require_verified(doc_key)`` first; a missing or changed file raises
``SourceMismatch`` and nothing is measured.

Usage: .venv\\Scripts\\python.exe -m eval.reading.real.verify      (prints the status of all three files)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "sources.json"
INCOMING = HERE / "incoming"
HASH_FIELD = "sha256_seen_2026_10_04"


class SourceMismatch(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sources(sources: Path = SOURCES, incoming: Path = INCOMING) -> dict[str, dict]:
    status: dict[str, dict] = {}
    for document in json.loads(sources.read_text(encoding="utf-8"))["documents"]:
        path = incoming / document["file"]
        expected = document[HASH_FIELD]
        if not path.is_file():
            status[document["doc_key"]] = {"status": "missing", "path": str(path), "expected": expected}
            continue
        actual = _sha256(path)
        status[document["doc_key"]] = {"status": "ok" if actual == expected else "mismatch", "path": str(path),
                                       "expected": expected, "actual": actual}
    return status


def require_verified(doc_key: str, sources: Path = SOURCES, incoming: Path = INCOMING) -> Path:
    entry = verify_sources(sources, incoming).get(doc_key)
    if entry is None:
        raise SourceMismatch(f"UNKNOWN_DOC:{doc_key}")
    if entry["status"] == "missing":
        raise SourceMismatch(f"MISSING:{doc_key}:{entry['path']}")
    if entry["status"] != "ok":
        raise SourceMismatch(f"SHA256_MISMATCH:{doc_key}: expected {entry['expected']}, got {entry['actual']}")
    return Path(entry["path"])


if __name__ == "__main__":
    report = verify_sources()
    for key, entry in report.items():
        print(f"{entry['status']:8} {key}")
    sys.exit(0 if all(e["status"] == "ok" for e in report.values()) else 1)
