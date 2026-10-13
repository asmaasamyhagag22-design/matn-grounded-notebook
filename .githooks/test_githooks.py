"""Tests for the git hooks in .githooks/ (G1 forbidden staged paths, G2 tests on Python commits, G4 full suite).

Each test builds a throwaway git repository in tmp_path that uses this directory as core.hooksPath, so the real
hooks run exactly as git runs them (through git's bundled sh on Windows).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent


def git(repo: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    env = dict(os.environ, MATN_PYTHON=sys.executable, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, env=env, check=check)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", check=True)
    git(tmp_path, "config", "core.hooksPath", HOOKS.as_posix(), check=True)
    git(tmp_path, "config", "core.autocrlf", "false", check=True)
    return tmp_path


GOOD_MSG = "docs: add note\n\nWhy: explains the change for reviewers.\n"


def commit(repo: Path, rel: str, content: bytes | str = "x\n", msg: str = GOOD_MSG) -> subprocess.CompletedProcess:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())
    git(repo, "add", "-f", rel, check=True)
    return git(repo, "commit", "-q", "-m", msg)


# ---------- G1 ----------
@pytest.mark.parametrize("rel", [
    "output/run/summary.json",
    "runs/r1/plan.json",
    ".venv/Lib/site.py.txt",
    "node_modules/x/index.js",
    "models/qwen.gguf",
    "weights.safetensors",
    "eval/incoming/doc.pdf",
    "deck.pptx",
    "design/specimen/specimen.pptx",
    "design/templates.pptx",
    "design/templates/x/deck.pdf",
    "eval/pages/doc/p0000.txt",
    "audit/scratch/x.txt",
    "documents/Build a Large Language Model (Z-Library).pdf",
    "notes/raschka-chapter2.md",
    "tmp/x.txt",
])
def test_g1_blocks_forbidden_paths(repo, rel):
    result = commit(repo, rel)
    assert result.returncode != 0 and "[G1]" in result.stderr, result.stderr


def test_g1_blocks_files_over_5_mb(repo):
    result = commit(repo, "data.json", b"0" * (5 * 1024 * 1024 + 1))
    assert result.returncode != 0 and "[G1]" in result.stderr


def test_g1_allows_pptx_templates_under_design_templates_only(repo):
    assert commit(repo, "design/templates/office/template.pptx", b"PK").returncode == 0
    assert commit(repo, "design/templates/office/dark/template.pptx", b"PK").returncode == 0
    result = commit(repo, "out/design/templates/x.pptx", b"PK")
    assert result.returncode != 0 and "[G1]" in result.stderr


def test_g1_allows_normal_files(repo):
    result = commit(repo, "eval/gold/dev/doc.json", "{}\n")
    assert result.returncode == 0, result.stderr


# ---------- G2 ----------
def test_g2_blocks_python_commit_when_tests_fail(repo):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
    result = commit(repo, "tool.py", "print('x')\n")
    assert result.returncode != 0 and "[G2]" in result.stderr, result.stderr


def test_g2_allows_python_commit_when_tests_pass(repo):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    result = commit(repo, "tool.py", "print('x')\n")
    assert result.returncode == 0, result.stderr


SLOW_FAILING_TESTS = ("import pytest\n\n\ndef test_fast():\n    assert True\n\n\n"
                      "@pytest.mark.slow\ndef test_slow_fails():\n    assert False\n")


def test_g2_runs_only_fast_tests(repo):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text(SLOW_FAILING_TESTS, encoding="utf-8")
    result = commit(repo, "tool.py", "print('x')\n")
    assert result.returncode == 0, result.stderr


# ---------- G4 (pre-push: full suite) ----------
@pytest.fixture()
def remote(tmp_path_factory) -> Path:
    # A local bare repository outside the work tree: the push never leaves the machine.
    bare = tmp_path_factory.mktemp("remote") / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True)
    return bare


def push(repo: Path, remote: Path) -> subprocess.CompletedProcess:
    return git(repo, "push", "-q", remote.as_posix(), "HEAD:refs/heads/main")


def test_g4_blocks_push_when_a_slow_test_fails(repo, remote):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text(SLOW_FAILING_TESTS, encoding="utf-8")
    assert commit(repo, "tool.py", "print('x')\n").returncode == 0  # pre-commit skips the slow test
    result = push(repo, remote)
    assert result.returncode != 0 and "[G4]" in result.stderr, result.stderr


def test_g4_blocks_push_without_python_changes_in_the_pushed_commits(repo, remote):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
    assert commit(repo, "a.md").returncode == 0  # no .py staged: G2 does not run
    result = push(repo, remote)
    assert result.returncode != 0 and "[G4]" in result.stderr, result.stderr


def test_g4_allows_push_when_all_tests_pass(repo, remote):
    (repo / "tests").mkdir()
    (repo / "tests" / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    assert commit(repo, "tool.py", "print('x')\n").returncode == 0
    result = push(repo, remote)
    assert result.returncode == 0, result.stderr


def test_hooks_run_every_test_directory_of_this_repository():
    sys.path.insert(0, str(HOOKS))
    import pre_commit
    repo_root = HOOKS.parent
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*test_*.py"],
                         cwd=repo_root, capture_output=True, text=True, check=True).stdout.split()
    dirs = {Path(p).parent.as_posix() for p in out if not p.startswith("audit/")}
    covered = {d for d in dirs if any(d == t or d.startswith(t + "/") for t in pre_commit.TEST_DIRS)}
    assert dirs == covered, f"test directories missing from TEST_DIRS: {sorted(dirs - covered)}"


