"""Budget for the pre-commit fast subset (G2): it must stay at or under 15 s on this machine.

The integration test runs the exact G2 code path (`run_tests` from .githooks/pre_commit.py with -m "not slow") and
fails with the measured times in its message. Retry-on-fail (reviewer decision): if the first run is over budget it
is re-run up to 2 more times and judged by the minimum, because interference only ever adds time. The test is slow
itself, so it runs on push (G4), not inside the subset it measures. MATN_FAST_BUDGET_S overrides the budget on
Ubuntu (Linux) only.
"""
from __future__ import annotations

import pytest

import fast_budget


def fake(times, exit_codes=None):
    """A measure() stand-in returning the given times (and exit codes) in order; records the call count."""
    calls = []

    def measure():
        i = len(calls)
        calls.append(i)
        return times[i], (exit_codes or [0] * len(times))[i]

    return measure, calls


def test_one_run_when_the_first_is_within_budget():
    measure, calls = fake([9.8])
    runs, code, message = fast_budget.judge(measure, 15.0)
    assert runs == [9.8] and code == 0 and message is None and len(calls) == 1


def test_over_budget_is_retried_and_judged_by_the_minimum():
    measure, calls = fake([17.3, 10.4])
    runs, code, message = fast_budget.judge(measure, 15.0)
    assert runs == [17.3, 10.4] and message is None and len(calls) == 2


def test_three_runs_over_budget_fail_and_list_every_time():
    measure, calls = fake([16.04, 17.25, 15.51])
    runs, code, message = fast_budget.judge(measure, 15.0)
    assert len(calls) == 3 and message is not None
    assert "16.0 s, 17.2 s, 15.5 s" in message and "minimum 15.5 s" in message and "15.0 s budget" in message


def test_a_failing_test_run_is_not_retried():
    measure, calls = fake([17.0, 9.0], exit_codes=[1, 0])
    runs, code, message = fast_budget.judge(measure, 15.0)
    assert code == 1 and len(calls) == 1


@pytest.mark.parametrize("platform,env,expected", [
    ("linux", None, 15.0), ("linux", "22.5", 22.5),
    ("win32", None, 15.0), ("win32", "22.5", 15.0),  # the override is for Ubuntu only
])
def test_budget_override_applies_on_linux_only(monkeypatch, platform, env, expected):
    monkeypatch.setattr(fast_budget.sys, "platform", platform)
    if env is None:
        monkeypatch.delenv("MATN_FAST_BUDGET_S", raising=False)
    else:
        monkeypatch.setenv("MATN_FAST_BUDGET_S", env)
    assert fast_budget.budget_seconds() == expected


def test_measuring_inside_a_measured_run_refuses_instead_of_recursing(monkeypatch):
    monkeypatch.setenv(fast_budget.RUNNING_ENV, "1")
    with pytest.raises(RuntimeError, match="SLOW"):
        fast_budget.measure_fast_subset()


def test_fast_subset_fits_the_budget_on_this_machine():
    runs, exit_code, message = fast_budget.judge(fast_budget.measure_fast_subset, fast_budget.budget_seconds())
    assert exit_code == 0, f"the fast subset itself failed (exit {exit_code}) after {runs[-1]:.1f} s"
    assert message is None, message
