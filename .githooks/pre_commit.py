"""Matn pre-commit checks (see CLAUDE.md).

G1  reject staged paths in a forbidden category (venvs, node_modules, model files, caches, run outputs, PDFs/PPTX,
    eval page text, audit working files, the commercial book or anything derived from it) and files over 5 MB.
G2  when any staged file is Python, run the FAST tests (pytest -m "not slow") of the suites that exist in this
    repository; reject on failure. Slow tests are listed in the root conftest.py and run on push (G4, pre_push.py).
Exit code != 0 aborts the commit; the reason goes to stderr.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
FORBIDDEN = [
    (r"(^|/)(\.venv[^/]*|venv|env|\.conda)/", "virtual environment"),
    (r"(^|/)node_modules(/|$)", "node_modules"),
    (r"\.(gguf|safetensors|onnx|pt|pth|ckpt|bin)$|(^|/)(models|\.ollama)/", "model file"),
    (r"(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.cache)/|\.py[cod]$|(^|/)[^/]*-cache/", "cache"),
    (r"^(output|outputs|runs|tmp)/", "run output"),
    (r"^(data|documents|wheelhouse)/", "local data directory"),
    (r"\.(pdf|pptx)$", "PDF/PPTX (documents and generated decks stay local)"),
    (r"^eval/pages/", "extracted page text (regenerated from pinned PDFs)"),
    (r"^audit/(scratch|logs)/", "audit working files"),
    (r"z-library|raschka|build a large language model|book-demo|pre-demo-backup|(^|/)_quarantine|(^|/)\.codex-",
     "commercial book or derived material"),
    (r"(^|/)\.env(\.|$)|\.(pem|key)$|(^|/)\.streamlit/secrets\.toml$", "secret"),
]
TEST_DIRS = ["tests", "eval/tests", ".claude/hooks", ".githooks"]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def run_tests(tag: str, *pytest_args: str) -> int:
    """Run pytest over the TEST_DIRS that exist; on failure print the tail under `tag` and return 1."""
    root = Path(git("rev-parse", "--show-toplevel").strip())
    dirs = [d for d in TEST_DIRS if (root / d).is_dir()]
    if not dirs:
        return 0
    result = subprocess.run([sys.executable, "-B", "-m", "pytest", *dirs, "-q", "-p", "no:cacheprovider", "-x",
                             *pytest_args], cwd=root, capture_output=True, text=True)
    if result.returncode not in (0, 5):  # 5 = no tests selected (e.g. every test is slow)
        tail = "\n".join(result.stdout.strip().splitlines()[-15:])
        sys.stderr.write(f"[{tag}] blocked: tests failed ({' '.join(dirs)} {' '.join(pytest_args)})\n{tail}\n")
        return 1
    return 0


def main() -> int:
    staged = [p for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0") if p]
    problems = []
    for path in staged:
        low = path.replace("\\", "/").lower()
        for pattern, label in FORBIDDEN:
            if re.search(pattern, low):
                problems.append(f"{path}: {label}")
                break
        else:
            size = int(git("cat-file", "-s", f":{path}").strip() or 0)
            if size > MAX_BYTES:
                problems.append(f"{path}: {size} bytes > 5 MB")
    if problems:
        sys.stderr.write("[G1] commit blocked, forbidden staged paths:\n" + "\n".join(f"  - {p}" for p in problems) + "\n")
        return 1
    if any(p.endswith(".py") for p in staged):
        return run_tests("G2", "-m", "not slow")
    return 0


if __name__ == "__main__":
    sys.exit(main())
