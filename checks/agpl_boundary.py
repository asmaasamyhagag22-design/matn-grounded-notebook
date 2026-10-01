"""ADR-0001 boundary: where PyMuPDF (AGPL-3.0 or Artifex commercial) may be imported.

Allowed: eval tooling (eval/). Everything else is checked. Detection parses each file with `ast`, so comments and
strings do not count, and catches `import`, `from ... import`, imports inside functions or try blocks,
`importlib.import_module("...")` and `__import__("...")` with a literal name. Covered packages: fitz, pymupdf and every
pymupdf* distribution (pymupdf4llm, pymupdf_layout), all under the same dual license.

FROZEN holds the importers that existed when ADR-0001 was written (2026-10-01). They are a known violation pending
legal review, not an approval; the list may only shrink (see checks/test_agpl_boundary.py).
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

AGPL_ROOT = re.compile(r"^(fitz|pymupdf\w*)$")
ALLOWED_PREFIXES = ("eval/",)
FROZEN = {
    "document_store.py": "pipeline: pymupdf.open for page text",
    "inspect_pdf.py": "pipeline: PDF inspection, pymupdf + pymupdf4llm.to_markdown",
    "matn_presentation/assets.py": "pipeline: fitz.open/Matrix/Rect for page images",
    "matn_presentation/live.py": "pipeline: fitz.open",
    "benchmark_structured.py": "root benchmark script: pymupdf + pymupdf4llm",
    "tests/make_sample_pdfs.py": "test fixtures: builds sample PDFs",
    "tests/test_document_store.py": "test of pipeline code",
    "tests/test_inspect_pdf.py": "test of pipeline code",
}


def _is_agpl(module: str) -> bool:
    return bool(AGPL_ROOT.match(module.split(".")[0]))


def agpl_imports(source: str) -> list[tuple[int, str]]:
    """(line, module) for every PyMuPDF import in `source`; raises SyntaxError if it does not parse."""
    hits = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            hits += [(node.lineno, alias.name) for alias in node.names if _is_agpl(alias.name)]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module and _is_agpl(node.module):
                hits.append((node.lineno, node.module))
        elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            value = node.args[0].value
            if name in ("import_module", "__import__") and isinstance(value, str) and _is_agpl(value):
                hits.append((node.lineno, value))
    return sorted(hits)


def python_files(repo: Path) -> list[str]:
    """Tracked plus untracked-but-not-ignored .py files (what a commit could contain), repo-relative POSIX paths."""
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.py"],
                         cwd=repo, capture_output=True, text=True, check=True).stdout
    return sorted({p for p in out.split("\0") if p and (repo / p).is_file()})


def scan(repo: Path, files: list[str]) -> dict[str, list[tuple[int, str]]]:
    """Violations by file: PyMuPDF imports outside ALLOWED_PREFIXES (FROZEN entries are included, not excused)."""
    violations = {}
    for rel in files:
        if rel.startswith(ALLOWED_PREFIXES):
            continue
        try:
            hits = agpl_imports((repo / rel).read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            hits = [(0, "<syntax error: cannot check>")]
        if hits:
            violations[rel] = hits
    return violations
