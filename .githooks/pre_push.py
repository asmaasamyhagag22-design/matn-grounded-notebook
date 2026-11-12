"""Matn pre-push check G4: before anything leaves the machine,

1. every new public commit must obey the public trailer policy;
2. the FULL test suite (fast and slow tests) must pass.

Runs on every push, whatever the pushed commits touch, so a slow test that pre-commit (G2) skipped still gates the
push. The suite runs on the working tree, like G2. Exit code != 0 aborts the push; the reason goes to stderr.
"""
from __future__ import annotations

import subprocess
import sys

from commit_msg import trailer_problems
from pre_commit import run_tests

ZERO = "0" * 40


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def commits_to_check(local_sha: str, remote_sha: str) -> list[str]:
    """Commits introduced by this branch update."""
    args = ["rev-list", local_sha]
    if remote_sha != ZERO:
        args.append(f"^{remote_sha}")  # already on the remote
    return [sha for sha in _git(*args).stdout.split() if sha]


def trailer_failures(ref_lines: list[str]) -> list[str]:
    failures = []
    for line in ref_lines:
        parts = line.split()
        if len(parts) != 4 or parts[1] == ZERO:  # malformed, or a branch deletion
            continue
        for sha in commits_to_check(parts[1], parts[3]):
            message = _git("show", "-s", "--format=%B", sha).stdout
            for problem in trailer_problems(message):
                failures.append(f"{sha[:7]}: {problem}")
    return failures


def main() -> int:
    ref_lines = sys.stdin.read().splitlines()  # git sends the pushed refs on stdin
    failures = trailer_failures(ref_lines)
    if failures:
        sys.stderr.write("[G4] push blocked: commits violating the public message convention\n  " + "\n  ".join(failures) + "\n")
        return 1
    return run_tests("G4")


if __name__ == "__main__":
    sys.exit(main())
