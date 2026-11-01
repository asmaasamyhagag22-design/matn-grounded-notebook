import json

import pytest

from matn_app.profiling import collect, summarize


def test_profile_is_opt_in_and_preserves_exceptions(tmp_path):
    with collect(tmp_path):
        pass
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError, match="same failure"):
        with collect(tmp_path, enabled=True):
            raise ValueError("same failure")
    result = json.loads((tmp_path / "profile.json").read_bytes())
    assert result["wall_seconds"] >= 0
    assert result["timing_scope"].startswith("inclusive")


def test_profile_reports_real_nested_stream_statistics_without_source_text(tmp_path):
    secret = "Do not copy source text into performance summaries"
    (tmp_path / "answer-receipts.json").write_text(json.dumps(dict(trace=[dict(attempt=0,
        payload=dict(prompt=secret), raw=dict(first_content_seconds=2,
        final_statistics=dict(prompt_eval_count=123, eval_count=12, prompt_eval_duration=3_000_000_000,
                              eval_duration=4_000_000_000, load_duration=1_000_000_000)))], response={})))
    with collect(tmp_path, enabled=True):
        pass
    raw = (tmp_path / "profile.json").read_text()
    assert secret not in raw
    row = json.loads(raw)["generations"][0]
    assert row["prompt_tokens"] == 123
    assert row["prompt_eval_seconds"] == 3
    assert row["generation_seconds"] == 4


def test_stage_timers_preserve_digital_pdf_evidence_and_restore_functions(tmp_path):
    from matn_app.evidence import run_request
    from matn_reading.pdf_page import OpenPdf
    from tests.reading.pdf_fixtures import write_pdf
    pdf = write_pdf(tmp_path / "public-fixture.pdf", b"BT /F1 12 Tf 72 600 Td (Alpha may expand.) Tj ET\n")
    original = OpenPdf.page
    before = run_request(dict(operation="ingest", inputs=[str(pdf)], workdir=str(tmp_path / "before"), fake=True))
    with collect(tmp_path / "after", enabled=True):
        after = run_request(dict(operation="ingest", inputs=[str(pdf)], workdir=str(tmp_path / "after"), fake=True))
    assert OpenPdf.page is original
    assert before["status"] == after["status"] == "complete"
    assert before["text"] == after["text"]
    assert [c["text"] for c in before["citations"]] == [c["text"] for c in after["citations"]]
    value = json.loads((tmp_path / "after/profile.json").read_bytes())
    assert value["stages"]["pdf_text_extraction"]["calls"] == 1
    assert value["stages"]["structure_assembly"]["calls"] == 1
