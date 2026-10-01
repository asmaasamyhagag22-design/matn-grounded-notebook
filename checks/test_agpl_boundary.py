"""Guard for ADR-0001: PyMuPDF (AGPL-3.0) is allowed in eval tooling only, pending legal review.

Fails when any Python file outside eval/ imports fitz, pymupdf or a pymupdf* package (pymupdf4llm, pymupdf_layout),
unless the file is on the frozen list of importers that existed when the ADR was written. The frozen list can only
shrink: an entry that no longer imports PyMuPDF must be removed from it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import agpl_boundary as guard

REPO = Path(__file__).resolve().parents[1]
ADR = REPO / "docs" / "adr" / "0001-pymupdf-agpl-eval-tooling-only.md"


@pytest.mark.parametrize("source, module", [
    ("import fitz\n", "fitz"),
    ("import pymupdf\n", "pymupdf"),
    ("import pymupdf as fitz\n", "pymupdf"),
    ("import os, fitz\n", "fitz"),
    ("from pymupdf import Document\n", "pymupdf"),
    ("from fitz.utils import getColor\n", "fitz.utils"),
    ("import pymupdf4llm\n", "pymupdf4llm"),
    ("from pymupdf4llm.helpers import document_layout\n", "pymupdf4llm.helpers"),
    ("import pymupdf.layout\n", "pymupdf.layout"),
    ("def f():\n    import fitz\n    return fitz\n", "fitz"),
    ("try:\n    import pymupdf\nexcept ImportError:\n    pymupdf = None\n", "pymupdf"),
    ("import importlib\nm = importlib.import_module('fitz')\n", "fitz"),
    ("from importlib import import_module\nm = import_module('pymupdf.layout')\n", "pymupdf.layout"),
    ("m = __import__('pymupdf')\n", "pymupdf"),
])
def test_detects_every_import_form(source, module):
    assert [m for _, m in guard.agpl_imports(source)] == [module]


@pytest.mark.parametrize("source", [
    "import fitzgerald\n",
    "import mupdf_tools_of_ours\n",
    "from . import fitz\n",  # a local module, not the library
    "# import fitz\nNOTE = 'import pymupdf'\n",
    "import importlib\nm = importlib.import_module(name)\n",
])
def test_ignores_lookalikes_comments_and_strings(source):
    assert guard.agpl_imports(source) == []


def test_unparseable_file_is_reported_not_skipped(tmp_path):
    (tmp_path / "broken.py").write_text("import fitz\ndef (:\n", encoding="utf-8")
    violations = guard.scan(tmp_path, ["broken.py"])
    assert violations == {"broken.py": [(0, "<syntax error: cannot check>")]}


def test_eval_tooling_is_allowed_and_everything_else_is_not(tmp_path):
    for rel in ("eval/extract_pages.py", "eval/tests/test_x.py", "app.py", "matn_summarization/new.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("import pymupdf\n", encoding="utf-8")
    files = ["eval/extract_pages.py", "eval/tests/test_x.py", "app.py", "matn_summarization/new.py"]
    assert sorted(guard.scan(tmp_path, files)) == ["app.py", "matn_summarization/new.py"]


@pytest.fixture(scope="module")
def repo_violations():
    """One scan of the repository shared by the tests below (git ls-files + parsing every file is the slow part)."""
    return guard.scan(REPO, guard.python_files(REPO))


def test_no_new_pymupdf_import_outside_eval_tooling(repo_violations):
    violations = repo_violations
    new = {path: hits for path, hits in violations.items() if path not in guard.FROZEN}
    assert not new, ("ADR-0001: PyMuPDF (AGPL-3.0) is allowed in eval/ only until legal review decides. "
                     f"New imports: {new}")


def test_frozen_list_only_shrinks(repo_violations):
    violations = repo_violations
    gone = sorted(path for path in guard.FROZEN if path not in violations)
    assert not gone, f"these files no longer import PyMuPDF; remove them from FROZEN and from the ADR: {gone}"


def test_adr_lists_every_frozen_importer():
    text = ADR.read_text(encoding="utf-8")
    assert "eval/" in text and "Status" in text
    missing = [path for path in guard.FROZEN if f"`{path}`" not in text]
    assert not missing, f"ADR-0001 must list every frozen importer: {missing}"
