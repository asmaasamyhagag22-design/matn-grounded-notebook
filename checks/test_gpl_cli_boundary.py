"""Guard for ADR-0002: pdftotext (Xpdf, GPL) is an external CLI for eval cross-checks only.

Fails when any code file outside eval tooling mentions pdftotext in any form: a subprocess call, a path, an
environment variable such as MATN_PDFTOTEXT, or a comment. Pipeline code must never call or depend on it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import gpl_cli_boundary as guard

REPO = Path(__file__).resolve().parents[1]
ADR = REPO / "docs" / "adr" / "0002-pdftotext-gpl-eval-cross-check-only.md"


@pytest.mark.parametrize("source", [
    "import subprocess\nsubprocess.run(['pdftotext', 'a.pdf', '-'])\n",
    "EXE = shutil.which('pdftotext.exe')\n",
    "exe = os.environ['MATN_PDFTOTEXT']\n",
    "# fall back to PdfToText when PyMuPDF fails\n",
    "pdftotext -layout in.pdf out.txt\n",
])
def test_every_mention_counts(source):
    assert [line for line, _ in guard.references(source)] == [source.count("\n", 0, source.lower().index("pdftotext")) + 1]


@pytest.mark.parametrize("source", ["text = pdf_to_text(path)\n", "# convert pdf to text\n", "pdftext = 1\n"])
def test_lookalikes_do_not_count(source):
    assert guard.references(source) == []


def test_eval_tooling_is_allowed_and_other_code_is_not(tmp_path):
    files = {
        "eval/cross_check.py": "subprocess.run(['pdftotext'])\n",
        "app.py": "subprocess.run(['pdftotext'])\n",
        "matn_summarization/extract.py": "# pdftotext fallback\n",
        "scripts/run.ps1": "& pdftotext.exe in.pdf\n",
        ".githooks/pre-commit": "pdftotext -v\n",
        "README.md": "pdftotext is used by eval only\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    assert sorted(guard.scan(tmp_path, sorted(files))) == [".githooks/pre-commit", "app.py",
                                                           "matn_summarization/extract.py", "scripts/run.ps1"]


def test_no_pipeline_code_references_pdftotext():
    violations = guard.scan(REPO, guard.code_files(REPO))
    assert violations == {}, f"ADR-0002: pdftotext outside eval tooling: {violations}"


def test_adr_states_the_rule_and_names_this_guard():
    text = ADR.read_text(encoding="utf-8")
    assert "pdftotext" in text and "checks/test_gpl_cli_boundary.py" in text
