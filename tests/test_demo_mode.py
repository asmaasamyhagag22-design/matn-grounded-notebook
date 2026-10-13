from __future__ import annotations

import urllib.request
from pathlib import Path
import tomllib

import pytest
from PIL import Image
import matn_presentation.demo as demo

import matn_presentation.book_demo as book_demo
from matn_presentation.demo import prepare_validated_demo


@pytest.fixture(autouse=True)
def synthetic_demo_figure(tmp_path, monkeypatch):
    """Exercise demo routing/rendering without distributing the ignored source PDF.

    The image is a synthetic asset fixture, not evidence for source-paper claims.
    """
    monkeypatch.setattr(demo, "DEFAULT_DEMO_OUTPUT", tmp_path / "demo")

    def render_fixture(pdf_path, output_path):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (738, 831), "white").save(output_path)
        return {"method": "synthetic test asset"}

    monkeypatch.setattr(demo, "render_figure_2", render_fixture)
    # The fallback's default is bound at definition time: route outputs into tmp_path.
    monkeypatch.setattr(book_demo, "prepare_validated_demo",
                        lambda: prepare_validated_demo(tmp_path / "paper-fallback"))


def test_validated_demo_makes_zero_network_or_model_calls(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("validated demo attempted network access")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    result = prepare_validated_demo(tmp_path / "demo")
    assert result["plan"]["generation_mode"] == "validated_demo"
    assert result["plan"]["provenance"]["model_generation_calls"] == 0
    assert result["validation"]["status"] == "validated"
    assert result["pptx_path"].is_file()
    assert result["plan_path"].is_file()
    assert result["asset_path"].is_file()


def test_validated_demo_uses_tracked_inputs_not_ignored_output():
    import matn_presentation.demo as demo

    assert demo.SOURCE_RUN == demo.PROJECT_ROOT / "demo" / "phase04a"
    assert (demo.SOURCE_RUN / "claims.json").is_file()
    assert (demo.SOURCE_RUN / "semantic-plan.json").is_file()


def test_streamlit_launch_does_not_require_first_run_telemetry_prompt():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert config["browser"]["gatherUsageStats"] is False
    assert config["server"]["showEmailPrompt"] is False


def test_primary_demo_falls_back_to_paper_when_book_bundle_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(book_demo, "BOOK_PLAN", tmp_path / "missing-plan.json")
    monkeypatch.setattr(book_demo, "BOOK_CLAIMS", tmp_path / "missing-claims.json")
    monkeypatch.setattr(book_demo, "BOOK_PPTX", tmp_path / "missing.pptx")
    monkeypatch.setattr(book_demo, "BOOK_PDF", tmp_path / "missing.pdf")
    monkeypatch.setattr(book_demo, "BOOK_RECEIPT", tmp_path / "missing-receipt.json")
    result = book_demo.load_primary_demo()
    assert result["sample_kind"] == "paper_fallback"
    assert result["plan"]["generation_mode"] == "validated_demo"
    assert result["load_run_details"]["model_generation_calls"] == 0


def test_prepared_book_demo_requires_a_validated_complete_bundle(tmp_path, monkeypatch):
    paths = {
        "BOOK_PLAN": tmp_path / "deck-plan.json",
        "BOOK_CLAIMS": tmp_path / "claims.json",
        "BOOK_PPTX": tmp_path / "book.pptx",
        "BOOK_PDF": tmp_path / "book.pdf",
        "BOOK_RECEIPT": tmp_path / "validation-receipt.json",
    }
    for name, path in paths.items():
        monkeypatch.setattr(book_demo, name, path)
        if name == "BOOK_RECEIPT":
            path.write_text('{"status":"validated"}', encoding="utf-8")
        else:
            path.write_bytes(b"present")

    assert book_demo.prepared_book_demo_ready() is True
    paths["BOOK_RECEIPT"].write_text('{"status":"pending"}', encoding="utf-8")
    assert book_demo.prepared_book_demo_ready() is False


def test_streamlit_main_path_uses_plain_audience_labels():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert 'st.tabs(["Overview", "Presentation", "Sources"])' in source
    assert 'st.button("Create presentation"' in source
    assert '"Download PowerPoint"' in source
    assert "Prepared sample — opens instantly." in source
    assert "key=_preview_sort_key" in source
    assert "Validated Demo Mode" not in source
    assert "Live Local Generation" not in source
    assert "English MVP" not in source
    assert "Grounded citations" not in source
