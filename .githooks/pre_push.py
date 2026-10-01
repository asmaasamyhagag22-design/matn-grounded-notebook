"""Matn pre-push check G4: run the FULL test suite (fast and slow tests) before anything leaves the machine.

Runs on every push, whatever the pushed commits touch, so a slow test that pre-commit (G2) skipped still gates the
push. The suite runs on the working tree, like G2. Exit code != 0 aborts the push; the reason goes to stderr.
"""
from __future__ import annotations

import sys

from pre_commit import run_tests


def main() -> int:
    sys.stdin.read()  # git sends the pushed refs on stdin; drain it so git never sees a broken pipe
    return run_tests("G4")


if __name__ == "__main__":
    sys.exit(main())
