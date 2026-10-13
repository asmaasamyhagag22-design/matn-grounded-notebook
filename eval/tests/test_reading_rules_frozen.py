"""docs/reading_eval_rules.md and the normalization table are frozen (owner decision, 2026-10-04, before the first
measurement). Step 4b.2 was re-frozen with explicit owner approval before its first measurement. A change fails here
on purpose: update these hashes only in a commit of its own, with the owner's
approval, and never to move a result that has already been seen."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from eval.reading.metrics import NORMALIZATION_TABLE

REPO = Path(__file__).resolve().parents[2]
RULES_SHA256 = "5bc0d0db3336650ee023401520b09b527f6c2927457639183e7167bb1981c0b3"
THRESHOLDS_SHA256 = "ef426a3ac03756b7606d99782f2b7c1aa207c45cc4801ef26f5669711afba633"
TABLE_SHA256 = "42c289e8fe410e1b702135a56df8ae607d076f462d05e244854bb97d31348c94"


def test_rules_document_is_unchanged():
    text = (REPO / "docs" / "reading_eval_rules.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert hashlib.sha256(text.encode()).hexdigest() == RULES_SHA256


def test_implementation_thresholds_are_unchanged():
    text = (REPO / "eval" / "reading" / "thresholds.json").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert hashlib.sha256(text.encode()).hexdigest() == THRESHOLDS_SHA256


def test_normalization_table_is_unchanged():
    canonical = json.dumps(NORMALIZATION_TABLE, sort_keys=True, ensure_ascii=True)
    assert hashlib.sha256(canonical.encode()).hexdigest() == TABLE_SHA256
