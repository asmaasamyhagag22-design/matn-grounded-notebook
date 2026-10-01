"""ADR-0002 boundary: pdftotext (Xpdf, GPL) may be referenced by eval tooling only.

pdftotext is a command-line program, not a library, so there is no import to parse. Any mention counts instead,
case-insensitively: a subprocess call, a path, an environment variable (MATN_PDFTOTEXT) or a comment. Checked files are
code files that a commit could contain (tracked, or untracked and not ignored): Python, shell, PowerShell and batch
scripts, plus the suffix-less git hook scripts in .githooks/. Allowed: eval/ and this guard with its test.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

PATTERN = re.compile(r"pdftotext", re.IGNORECASE)
ALLOWED_PREFIXES = ("eval/",)
ALLOWED_FILES = {"checks/gpl_cli_boundary.py", "checks/test_gpl_cli_boundary.py"}
CODE_SUFFIXES = {".py", ".sh", ".ps1", ".psm1", ".bat", ".cmd"}


def references(source: str) -> list[tuple[int, str]]:
    """(line number, matched text) for every mention of pdftotext."""
    return [(source.count("\n", 0, m.start()) + 1, m.group(0)) for m in PATTERN.finditer(source)]


def _is_code(rel: str) -> bool:
    path = Path(rel)
    return path.suffix.lower() in CODE_SUFFIXES or (rel.startswith(".githooks/") and path.suffix == "")


def code_files(repo: Path) -> list[str]:
    """Tracked plus untracked-but-not-ignored code files, repo-relative POSIX paths."""
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                         cwd=repo, capture_output=True, text=True, check=True).stdout
    return sorted({p for p in out.split("\0") if p and _is_code(p) and (repo / p).is_file()})


def scan(repo: Path, files: list[str]) -> dict[str, list[tuple[int, str]]]:
    """Violations by file: mentions of pdftotext in code files outside the allowed paths."""
    violations = {}
    for rel in files:
        if rel.startswith(ALLOWED_PREFIXES) or rel in ALLOWED_FILES or not _is_code(rel):
            continue
        hits = references((repo / rel).read_text(encoding="utf-8", errors="replace"))
        if hits:
            violations[rel] = hits
    return violations
