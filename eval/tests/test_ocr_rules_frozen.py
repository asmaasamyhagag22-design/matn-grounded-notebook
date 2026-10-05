"""Step 4c OCR rules are frozen before the first OCR measurement (docs/ocr_rules.md). A change fails here on purpose:
update a hash only in a commit of its own, with the owner's approval, and never to move a result already seen. The
confidence bar stays 1.0. The owner-approved close-out re-freeze pins layout, orientation, adaptive denoise and the fresh holdout before its final measurement."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FROZEN = {
    "matn_reading/ocr/closeout_rules.json": "0a03d4331c6b3b9f4c9043daffa6dc4a9ae645b12e2e8f62c5b82e2b4c705985",
    "matn_reading/ocr/preprocess.py": "d153f7585b95f037de50f174219ad6f166077e989213a22f10a8456b844cddae",
    "matn_reading/ocr/regions.py": "88bab7b1bdddfa3753dc8b574e57586cfb633178a1e5d13dc61d2a123d0cea63",
    "matn_reading/ocr/route.py": "d36de4f457d71c4a7188d8fa56ec13dbed456cc073860f93ae9f6650e046c0f5",
    "matn_reading/ocr/worker.py": "262d30a6626b5da5ec3eeab75e4728819498f61d9312dee875485b764ddb26b0",
    "matn_reading/ocr/reader1.py": "fed053f26fbb70a32e0451731ada65eeeb0824a763084eabedab20f0d8940e15",
    "matn_reading/cli.py": "a296b8de5f466a78a2ea4d2b004459e13954b38302e057f4ff125d1684f47672",
    "eval/reading/synthetic/holdout2.json": "3ed1cd6cc64495264a48c30cb37523fa03ba134bf8062b510aa090f3d1b02a96",
    "docs/ocr_rules.md": "8f4f9cee70971a8587bae834c36839494613dcccb0fdf670c8ecca55f79709d2",
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
