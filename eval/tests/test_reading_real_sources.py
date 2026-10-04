"""Real scans are measured only when the file's sha256 equals the one recorded in sources.json."""
from __future__ import annotations

import hashlib
import json

import pytest

from eval.reading.real.verify import SourceMismatch, require_verified, verify_sources


def _setup(tmp_path, content: bytes, recorded: bytes | None = None):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "doc.pdf").write_bytes(content)
    sources = tmp_path / "sources.json"
    sha = hashlib.sha256(recorded if recorded is not None else content).hexdigest()
    sources.write_text(json.dumps({"documents": [
        {"doc_key": "doc", "file": "doc.pdf", "sha256_seen_2026_10_04": sha},
        {"doc_key": "absent", "file": "absent.pdf", "sha256_seen_2026_10_04": "0" * 64},
    ]}), encoding="utf-8")
    return sources, incoming


def test_matching_file_is_verified(tmp_path):
    sources, incoming = _setup(tmp_path, b"%PDF-1.4 scan")
    status = verify_sources(sources, incoming)
    assert status["doc"]["status"] == "ok"
    assert status["absent"]["status"] == "missing"
    assert require_verified("doc", sources, incoming) == incoming / "doc.pdf"


def test_a_changed_file_is_refused_before_measurement(tmp_path):
    sources, incoming = _setup(tmp_path, b"%PDF-1.4 tampered", recorded=b"%PDF-1.4 original")
    assert verify_sources(sources, incoming)["doc"]["status"] == "mismatch"
    with pytest.raises(SourceMismatch, match="SHA256_MISMATCH"):
        require_verified("doc", sources, incoming)


def test_a_missing_file_is_refused(tmp_path):
    sources, incoming = _setup(tmp_path, b"x")
    with pytest.raises(SourceMismatch, match="MISSING"):
        require_verified("absent", sources, incoming)


def test_the_committed_sources_file_has_a_hash_for_every_document():
    from eval.reading.real.verify import SOURCES

    documents = json.loads(SOURCES.read_text(encoding="utf-8"))["documents"]
    assert len(documents) == 3
    assert all(len(d["sha256_seen_2026_10_04"]) == 64 for d in documents)
