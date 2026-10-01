"""Budget for the pre-commit fast subset (G2): it must stay at or under 15 s on this machine.

The integration test runs the exact G2 code path (`run_tests` from .githooks/pre_commit.py with -m "not slow") and
fails with the measured time in its message. It is slow itself, so it runs on push (G4), not inside the subset it
measures. MATN_FAST_BUDGET_S overrides the budget, e.g. on a slower or faster machine.
"""
from __future__ import annotations

import pytest

import fast_budget


def test_budget_message_names_the_measured_time_when_over_budget():
    message = fast_budget.over_budget(16.24, 15.0)
    assert message is not None
    assert "16.2 s" in message and "15.0 s" in message


@pytest.mark.parametrize("seconds", [0.0, 7.3, 15.0])
def test_within_budget_has_no_message(seconds):
    assert fast_budget.over_budget(seconds, 15.0) is None


def test_budget_comes_from_env_or_defaults_to_15(monkeypatch):
    monkeypatch.delenv("MATN_FAST_BUDGET_S", raising=False)
    assert fast_budget.budget_seconds() == 15.0
    monkeypatch.setenv("MATN_FAST_BUDGET_S", "9.5")
    assert fast_budget.budget_seconds() == 9.5


def test_measuring_inside_a_measured_run_refuses_instead_of_recursing(monkeypatch):
    monkeypatch.setenv(fast_budget.RUNNING_ENV, "1")
    with pytest.raises(RuntimeError, match="SLOW"):
        fast_budget.measure_fast_subset()


def test_fast_subset_fits_the_budget_on_this_machine():
    seconds, exit_code = fast_budget.measure_fast_subset()
    assert exit_code == 0, f"the fast subset itself failed (exit {exit_code}) after {seconds:.1f} s"
    message = fast_budget.over_budget(seconds, fast_budget.budget_seconds())
    assert message is None, message
