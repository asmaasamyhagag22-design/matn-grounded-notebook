from __future__ import annotations

import json
import re
from pathlib import Path

import matn_presentation.live as live


ROOT = Path(__file__).resolve().parents[1]


class FakeLocalClient:
    def __init__(self):
        self.generate_calls = 0
        self.base_url = "http://127.0.0.1:11434"
        self.contacted_hosts = []

    def show(self, model):
        self.contacted_hosts.append("127.0.0.1")
        return {"resolved_digest": "fake", "ollama_version": "test"}

    def generate(self, model, prompt, schema, num_ctx, num_predict, temperature, think):
        self.generate_calls += 1
        ids = list(dict.fromkeys(re.findall(r'live-p\d{3}-\d{3}', prompt)))
        bullets = [{"text": f"Grounded source statement {index + 1}", "claim_ids": [claim_id]} for index, claim_id in enumerate(ids[:5])]
        while len(bullets) < 3:
            bullets.append({"text": "Grounded source statement", "claim_ids": [ids[0]]})
        value = {
            "summary_title": "Local grounded source summary",
            "summary_points": bullets[:3],
            "slides": [
                {"title": f"Evidence group {index + 1}", "purpose": "Present accepted source evidence.", "layout": "title_and_bullets", "bullets": bullets[:3]}
                for index in range(4)
            ],
        }
        return json.dumps(value), {"done_reason": "stop"}


def test_live_local_cache_miss_then_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "LIVE_CACHE", tmp_path / "cache")
    client = FakeLocalClient()
    first = live.generate_live_local(
        ROOT / "documents" / "2601.14525v1.pdf",
        [2, 3],
        tmp_path / "run-1",
        client=client,
    )
    assert client.generate_calls == 1
    assert first["run_details"]["cache_status"] == "miss"
    assert first["plan"]["provenance"]["model_generation_calls"] == 1
    second = live.generate_live_local(
        ROOT / "documents" / "2601.14525v1.pdf",
        [2, 3],
        tmp_path / "run-2",
        client=FakeLocalClient(),
    )
    assert second["run_details"]["cache_status"] == "hit"
    assert second["plan"]["provenance"]["model_generation_calls"] == 0
    assert second["pptx_path"].is_file()
