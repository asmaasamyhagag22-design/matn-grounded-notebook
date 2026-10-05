"""Step 4c OCR rules are frozen before the first OCR measurement (docs/ocr_rules.md). A change fails here on purpose:
update a hash only in a commit of its own, with the owner's approval, and never to move a result already seen. The
confidence bar is the one planned change: calibrated on dev-tune and frozen in its own commit before dev-check."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FROZEN = {
    "docs/ocr_rules.md": "cc3f6871708b0d4d05b49b14ac577fccbe55f1bf5900587a4e9bdb50027057cb",
    "matn_reading/ocr/rapidocr_settings.json": "dc6e9e3febe5905111af74e8aade66d3d3953943939f0b86af0b3c2093358323",
    "matn_reading/ocr/consensus.py": "1d791a18742380960409403ad6acc9477d40da690224c3714c8ada7b98553a3a",
    "matn_reading/ocr/numbers.py": "9456df442c6d850e053c7efb159c46cb9894d5f61783974538b1976fb271b762",
    "matn_reading/ocr/consistency.py": "b7b684189715e65713508b96dff7cb08be32c1f85803a17c152201559fe8411d",
}
RULES_WITHOUT_BAR_SHA256 = "0b0491b6a0904e88880d9570dc93a756fd278daeee4b501d678e9b971b2553fc"
CONFIDENCE_BAR = 1.0


def _sha(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode()).hexdigest()


def test_frozen_ocr_files_are_unchanged():
    for relative, expected in FROZEN.items():
        assert _sha((REPO / relative).read_text(encoding="utf-8")) == expected, relative


def test_ocr_rules_are_unchanged_apart_from_the_calibrated_bar():
    rules = json.loads((REPO / "matn_reading" / "ocr" / "ocr_rules.json").read_text(encoding="utf-8"))
    assert rules.pop("confidence_bar") == CONFIDENCE_BAR
    assert _sha(json.dumps(rules, sort_keys=True, ensure_ascii=True)) == RULES_WITHOUT_BAR_SHA256
