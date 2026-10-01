"""Repository-wide pytest configuration: which tests are slow.

pre-commit (G2) runs `pytest -m "not slow"`; pre-push (G4) runs everything. Slow tests are listed here by
"<repo-relative file>::<function>" instead of being decorated in place, so the pipeline tests in tests/ stay unchanged.
The list came from `pytest --durations=0` on 2026-10-01: a function is slow when one of its cases takes >= 0.2 s or
all of its cases together take >= 1 s, and every test that starts a subprocess per case (git, sh, the
Claude guard) is slow too, because one Windows process start costs 0.1-0.35 s here.

Two checks keep the list honest:
- an entry whose file was collected but whose function no longer exists stops the run (stale entry);
- an unlisted test that takes longer than SLOW_WARN_SECONDS is named in the terminal summary.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent
SLOW_WARN_SECONDS = 0.5
SLOW = frozenset({
    ".claude/hooks/test_guard.py::test_r1_allows_normal_project_paths",
    ".claude/hooks/test_guard.py::test_r1_blocks_restricted_paths_for_file_tools",
    ".claude/hooks/test_guard.py::test_r2_allows_loopback_and_local_commands",
    ".claude/hooks/test_guard.py::test_r2_override_requires_explicit_env",
    ".claude/hooks/test_guard.py::test_r4_inactive_before_freeze",
    ".claude/hooks/test_guard.py::test_r5_inactive_without_lock",
    ".claude/hooks/test_guard.py::test_r1_blocks_restricted_paths_in_grep_glob_and_shell",
    ".claude/hooks/test_guard.py::test_r2_blocks_network_and_install_commands",
    ".claude/hooks/test_guard.py::test_r3_blocks_web_tools",
    ".claude/hooks/test_guard.py::test_r4_blocks_test_gold_after_freeze_unless_milestone",
    ".claude/hooks/test_guard.py::test_r5_blocks_pipeline_outputs_while_drafting",
    ".claude/hooks/test_guard.py::test_unknown_tool_and_bad_json_do_not_crash",
    "checks/test_fast_budget.py::test_fast_subset_fits_the_budget_on_this_machine",
    ".githooks/test_githooks.py::test_g1_allows_normal_files",
    ".githooks/test_githooks.py::test_g1_blocks_files_over_5_mb",
    ".githooks/test_githooks.py::test_g1_blocks_forbidden_paths",
    ".githooks/test_githooks.py::test_g2_allows_python_commit_when_tests_pass",
    ".githooks/test_githooks.py::test_g2_blocks_python_commit_when_tests_fail",
    ".githooks/test_githooks.py::test_g2_runs_only_fast_tests",
    ".githooks/test_githooks.py::test_g3_allows_subject_plus_body",
    ".githooks/test_githooks.py::test_g3_blocks_messages_without_a_why_body",
    ".githooks/test_githooks.py::test_g4_allows_push_when_all_tests_pass",
    ".githooks/test_githooks.py::test_g4_blocks_push_when_a_slow_test_fails",
    ".githooks/test_githooks.py::test_g4_blocks_push_without_python_changes_in_the_pushed_commits",
    "tests/test_demo_mode.py::test_validated_demo_makes_zero_network_or_model_calls",
    "tests/test_document_store.py::test_noncontiguous_pages_and_bad_selectors",
    "tests/test_inspect_pdf.py::test_blank_and_image_only_share_no_text_but_have_distinct_signals",
    "tests/test_inspect_pdf.py::test_evaluation_harness_emits_schema_valid_json_and_markdown",
    "tests/test_inspect_pdf.py::test_manifest_deterministic_fields_and_text_are_stable",
    "tests/test_inspect_pdf.py::test_raw_extracts_exact_pages_manifest_and_does_not_log_content",
    "tests/test_inspect_pdf.py::test_refuses_every_existing_output_path",
    "tests/test_inspect_pdf.py::test_rejects_invalid_out_of_bounds_or_duplicate_pages",
    "tests/test_inspect_pdf.py::test_rejects_password_missing_and_corrupt_inputs",
    "tests/test_inspect_pdf.py::test_representative_arabic_columns_table_rotation_and_ocr_disabled",
    "tests/test_inspect_pdf.py::test_structured_batched_matches_per_page_and_rejects_bad_mapping",
    "tests/test_inspect_pdf.py::test_structured_preserves_noncontiguous_page_mapping",
    "tests/test_live_presentation.py::test_live_local_cache_miss_then_hit",
    "tests/test_presentation_renderer.py::test_renderer_creates_reopenable_bounded_presentation",
})


def _key(item: pytest.Item) -> str:
    try:
        rel = Path(item.path).resolve().relative_to(REPO).as_posix()
    except ValueError:
        return item.nodeid
    return f"{rel}::{item.originalname if hasattr(item, 'originalname') else item.name}"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    seen = set()
    for item in items:
        key = _key(item)
        seen.add(key)
        if key in SLOW:
            item.add_marker(pytest.mark.slow)
    collected_files = {key.split("::")[0] for key in seen}
    stale = sorted(e for e in SLOW if e.split("::")[0] in collected_files and e not in seen)
    if stale:
        raise pytest.UsageError("conftest.py SLOW lists tests that no longer exist:\n  " + "\n  ".join(stale))


_unlisted_slow: list[tuple[str, float]] = []


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.when == "call" and report.duration > SLOW_WARN_SECONDS and "slow" not in report.keywords:
        _unlisted_slow.append((report.nodeid, report.duration))


def pytest_terminal_summary(terminalreporter) -> None:
    if _unlisted_slow:
        terminalreporter.write_sep("-", f"unlisted tests slower than {SLOW_WARN_SECONDS}s (add to SLOW in conftest.py)")
        for nodeid, seconds in _unlisted_slow:
            terminalreporter.write_line(f"{seconds:.2f}s {nodeid}")
