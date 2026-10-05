"""The 4b runner reads only the 3 dev documents, and its CER counts follow the frozen rules (section 1)."""
from __future__ import annotations

from eval.reading.digital import DEV_PAGE_SPLIT, _cer_counts, _reference_word_without_markers, dev_documents


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


def test_frozen_dev_subsets_cover_every_page_per_document():
    assert sum(len(entry["dev_tune"]) for entry in DEV_PAGE_SPLIT["documents"].values()) == 138
    assert sum(len(entry["dev_check"]) for entry in DEV_PAGE_SPLIT["documents"].values()) == 61


def test_reference_superscript_glued_to_a_word_is_removed_from_metric_text():
    markers = [{"text": "1", "bbox": (90, 0, 95, 5)}]
    assert _reference_word_without_markers("accountability.1", (0, 0, 95, 12), markers) == "accountability."
    assert _reference_word_without_markers("1Office", (90, 0, 120, 12), markers) == "Office"
    assert _reference_word_without_markers("process46;", (0, 0, 95, 12),
                                           [{"text": "46", "bbox": (80, 0, 90, 5)}]) == "process;"
