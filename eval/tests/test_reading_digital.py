"""The 4b runner reads only the 3 dev documents, and its CER counts follow the frozen rules (section 1)."""
from __future__ import annotations

from eval.reading.digital import _cer_counts, dev_documents


def test_only_the_three_dev_documents_are_listed():
    docs = dev_documents()
    assert sorted(d for d, _ in docs) == ["2601-14525v1", "gao-21-519sp", "wb-eem-2021-12"]
    assert all("nist" not in str(p) and "egypt" not in str(p) for _, p in docs)


def test_cer_counts_matched_and_unmatched_blocks():
    ref = [((0, 0, 100, 20), "GDP grew 3.2%"), ((0, 50, 100, 70), "unmatched reference")]
    hyp = [((1, 1, 99, 21), "GDP grew 3.7%"), ((300, 300, 400, 320), "extra")]
    counts = _cer_counts(ref, hyp)
    assert counts["matched_blocks"] == 1
    assert counts["chars"] == len("GDP grew 3.2%") + len("unmatched reference")
    assert counts["char_edits"] == 1 + len("unmatched reference") + len("extra")
