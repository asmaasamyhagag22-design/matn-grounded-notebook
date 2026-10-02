"""Time budget for the pre-commit fast subset (G2, `pytest -m "not slow"`).

measure_fast_subset() calls the same `run_tests` that .githooks/pre_commit.py uses for G2, so the measured command is
exactly what a commit runs. The budget is 15 s on the Windows laptop (Step 0 amendment); MATN_FAST_BUDGET_S overrides it
on Ubuntu only. judge() retries an over-budget run up to RETRIES times and decides on the minimum.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BUDGET_SECONDS = 15.0
RUNNING_ENV = "MATN_FAST_BUDGET_RUNNING"
RETRIES = 2  # re-runs allowed when the first measurement is over budget (reviewer decision, Step 0 close-out)


def budget_seconds() -> float:
    """15 s; MATN_FAST_BUDGET_S overrides it on Ubuntu (Linux) only, never on the Windows laptop."""
    if sys.platform.startswith("linux") and os.environ.get("MATN_FAST_BUDGET_S"):
        return float(os.environ["MATN_FAST_BUDGET_S"])
    return DEFAULT_BUDGET_SECONDS


def over_budget(runs: list[float], budget: float) -> str | None:
    """A failure message listing every measured run when even the fastest exceeds `budget`, else None."""
    if min(runs) <= budget:
        return None
    times = ", ".join(f"{s:.1f} s" for s in runs)
    return (f"pre-commit fast subset over the {budget:.1f} s budget in every run ({times}; minimum {min(runs):.1f} s): "
            "move slow tests to SLOW in conftest.py or make them faster (never delete or weaken them)")


def judge(measure, budget: float, retries: int = RETRIES) -> tuple[list[float], int, str | None]:
    """Retry-on-fail: re-run up to `retries` more times while over budget, judge by the minimum.

    Interference (other load on the machine) only ever adds time, so the minimum is the fairest estimate. A run whose
    tests fail is not retried: (runs, exit code, message) is returned at once.
    """
    runs: list[float] = []
    for _ in range(1 + retries):
        seconds, exit_code = measure()
        runs.append(seconds)
        if exit_code != 0:
            return runs, exit_code, None
        if seconds <= budget:
            break
    return runs, 0, over_budget(runs, budget)


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
