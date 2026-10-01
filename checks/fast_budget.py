"""Time budget for the pre-commit fast subset (G2, `pytest -m "not slow"`).

measure_fast_subset() calls the same `run_tests` that .githooks/pre_commit.py uses for G2, so the measured command is
exactly what a commit runs. The budget is 15 s on the Windows laptop (Step 0 amendment); MATN_FAST_BUDGET_S overrides it.
"""
from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BUDGET_SECONDS = 15.0
RUNNING_ENV = "MATN_FAST_BUDGET_RUNNING"


def budget_seconds() -> float:
    return float(os.environ.get("MATN_FAST_BUDGET_S") or DEFAULT_BUDGET_SECONDS)


def over_budget(seconds: float, budget: float) -> str | None:
    """A failure message with the measured time when `seconds` exceeds `budget`, else None."""
    if seconds <= budget:
        return None
    return (f"pre-commit fast subset took {seconds:.1f} s, over the {budget:.1f} s budget: move slow tests to SLOW "
            f"in conftest.py or make them faster (never delete or weaken them)")


def _pre_commit_module():
    spec = importlib.util.spec_from_file_location("matn_pre_commit", REPO / ".githooks" / "pre_commit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def measure_fast_subset() -> tuple[float, int]:
    """(wall seconds, exit code) of the G2 test run, started from the repository root.

    The child run inherits RUNNING_ENV; a measuring test that is wrongly in the fast subset then refuses instead of
    starting the subset again inside itself (endless recursion).
    """
    if os.environ.get(RUNNING_ENV) == "1":
        raise RuntimeError("the fast-budget test ran inside the fast subset: list it in SLOW in conftest.py")
    run_tests = _pre_commit_module().run_tests
    cwd = os.getcwd()
    os.chdir(REPO)
    os.environ[RUNNING_ENV] = "1"
    try:
        start = time.perf_counter()
        exit_code = run_tests("budget", "-m", "not slow")
        return time.perf_counter() - start, exit_code
    finally:
        del os.environ[RUNNING_ENV]
        os.chdir(cwd)
