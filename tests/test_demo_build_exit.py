"""Overnight review P2: a failed PowerPoint export must not look like a successful build."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from matn_deck import demo_build


def _stub_pipeline(monkeypatch, tmp_path: Path, export_result: tuple[bool, str]) -> None:
    monkeypatch.setattr(demo_build, "OUT", tmp_path)
    monkeypatch.setattr(demo_build, "load_demo_doc", lambda path: SimpleNamespace(doc_key="gao_21_519sp"))
    monkeypatch.setattr(demo_build, "build_plan",
                        lambda doc, use_model_phrases=False: SimpleNamespace(plan=SimpleNamespace(slides=[1]), meta=[]))
    monkeypatch.setattr(demo_build, "render_deck", lambda doc, demo, template_id, out_dir: {
        "slides": 1, "overflows": [], "hard_violations": [], "render_seconds": 0.0})
    monkeypatch.setattr(demo_build, "export", lambda decks: export_result)
    monkeypatch.setattr(demo_build, "manifest", lambda: {})


def test_main_returns_nonzero_when_the_export_fails(monkeypatch, tmp_path):
    _stub_pipeline(monkeypatch, tmp_path, (False, "EXPORT_FAILED:boom"))
    assert demo_build.main(["--doc", "gao_21_519sp", "--template", "modulo"]) != 0


def test_main_returns_zero_when_the_export_succeeds(monkeypatch, tmp_path):
    _stub_pipeline(monkeypatch, tmp_path, (True, "exported"))
    assert demo_build.main(["--doc", "gao_21_519sp", "--template", "modulo"]) == 0


def test_export_fails_when_powershell_exits_zero_but_outputs_are_missing(monkeypatch, tmp_path):
    deck = tmp_path / "deck"
    deck.mkdir()
    (deck / "deck.pptx").write_bytes(b"pptx")
    monkeypatch.setattr(demo_build.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="exported", stderr=""))
    ok, log = demo_build.export([deck])
    assert not ok
    assert "deck.pdf" in log


def test_export_succeeds_when_pdf_and_pngs_exist(monkeypatch, tmp_path):
    deck = tmp_path / "deck"
    (deck / "png").mkdir(parents=True)
    (deck / "deck.pptx").write_bytes(b"pptx")

    def fake_run(*args, **kwargs):
        (deck / "deck.pdf").write_bytes(b"%PDF")
        (deck / "png" / "slide_01.png").write_bytes(b"png")
        return subprocess.CompletedProcess(args, 0, stdout="exported", stderr="")

    monkeypatch.setattr(demo_build.subprocess, "run", fake_run)
    ok, _ = demo_build.export([deck])
    assert ok
