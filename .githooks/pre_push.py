"""Matn pre-push check G4: before anything leaves the machine,

1. every pushed commit from the rule-15 baseline onward must carry a valid `Agent:` trailer (the G5 rule, re-checked
   here so that a commit made without the commit-msg hook is still caught);
2. the FULL test suite (fast and slow tests) must pass.

Runs on every push, whatever the pushed commits touch, so a slow test that pre-commit (G2) skipped still gates the
push. The suite runs on the working tree, like G2. Exit code != 0 aborts the push; the reason goes to stderr.
"""
from __future__ import annotations

import os
import subprocess
import sys

from commit_msg import agent_problems
from pre_commit import run_tests

# CLAUDE.md rule 15 was committed in 34d50be: commits from it onward must carry the Agent trailer.
AGENT_TRAILER_SINCE = "34d50be"
ZERO = "0" * 40


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def commits_to_check(local_sha: str, remote_sha: str, since: str) -> list[str]:
    """Pushed commits (not yet on the remote) that are the baseline or newer; all pushed ones if it is unknown."""
    args = ["rev-list", local_sha]
    if remote_sha != ZERO:
        args.append(f"^{remote_sha}")  # already on the remote
    if _git("cat-file", "-e", f"{since}^{{commit}}").returncode == 0:
        parents = _git("rev-list", "--parents", "-n", "1", since).stdout.split()[1:]
        args += [f"^{p}" for p in parents]  # older than the baseline (a root baseline has no parents)
    return [sha for sha in _git(*args).stdout.split() if sha]


def trailer_failures(ref_lines: list[str], since: str) -> list[str]:
    failures = []
    for line in ref_lines:
        parts = line.split()
        if len(parts) != 4 or parts[1] == ZERO:  # malformed, or a branch deletion
            continue
        for sha in commits_to_check(parts[1], parts[3], since):
            message = _git("show", "-s", "--format=%B", sha).stdout
            for problem in agent_problems(message):
                failures.append(f"{sha[:7]}: {problem}")
    return failures


def main() -> int:
    ref_lines = sys.stdin.read().splitlines()  # git sends the pushed refs on stdin
    since = os.environ.get("MATN_G5_SINCE") or AGENT_TRAILER_SINCE  # env: test-only override of the baseline
    failures = trailer_failures(ref_lines, since)
    if failures:
        sys.stderr.write("[G4] push blocked: commits without a valid Agent trailer\n  " + "\n  ".join(failures) + "\n")
        return 1
    return run_tests("G4")


if __name__ == "__main__":
    sys.exit(main())
