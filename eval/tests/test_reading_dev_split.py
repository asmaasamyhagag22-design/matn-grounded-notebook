"""The 199 digital dev pages are frozen before tuning and stratified by document."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPLIT = ROOT / "eval" / "reading" / "dev_split.json"


def test_dev_page_split_is_reproducible_stratified_and_complete():
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    assert split["seed"] == 42042 and split["total_pages"] == 199
    assert set(split["documents"]) == {"2601-14525v1", "gao-21-519sp", "wb-eem-2021-12"}
    total = 0
    for doc_id, entry in split["documents"].items():
        pages = entry["pages"]
        expected = sorted(
            range(pages),
            key=lambda page: hashlib.sha256(f"{split['seed']}:{doc_id}:{page}".encode()).digest(),
        )
        tune_count = round(0.70 * pages)
        assert entry["dev_tune"] == sorted(expected[:tune_count])
        assert entry["dev_check"] == sorted(expected[tune_count:])
        assert set(entry["dev_tune"]).isdisjoint(entry["dev_check"])
        assert sorted(entry["dev_tune"] + entry["dev_check"]) == list(range(pages))
        total += pages
    assert total == 199
    assert sum(len(entry["dev_tune"]) for entry in split["documents"].values()) == 138
    assert sum(len(entry["dev_check"]) for entry in split["documents"].values()) == 61
