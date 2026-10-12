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
    "tests/rag/test_embedding_safety.py::test_live_loopback_fixture_ignores_proxy_and_refuses_redirect",
    "tests/rag/test_citability_gates.py::test_two_process_json_determinism",
    "eval/tests/test_gpt_annotation.py::test_closeout_states_complete_only_delegated_model_scope",
    "eval/tests/test_real_sample.py::test_constrained_proportional_quotas_and_seeded_draw",
    "eval/tests/test_real_sample.py::test_sample_measurement_publishes_only_signed_fixture_and_blocks_pending_gao",
    "eval/tests/test_real_review.py::test_review_has_no_selected_answers_and_preserves_template",
    "eval/tests/test_real_review.py::test_signed_synthetic_fixture_measures_true_false_alarms_per_page",
    "tests/reading/ocr/test_closeout.py::test_duplicate_detection_of_a_year_digit_cannot_be_accepted_twice",
    "tests/reading/ocr/test_closeout.py::test_horizontal_fragment_of_vertical_margin_stamp_is_not_accepted",
    "eval/tests/test_closeout_real_layer.py::test_real_runner_passes_embedded_layer_to_reader",
    "eval/tests/test_fetch_sources.py::test_tls_uses_the_certifi_bundle_and_keeps_verification_strict",
    "eval/tests/test_fetch_sources.py::test_https_requests_use_that_context",
    "eval/tests/test_verify_gold.py::test_cross_check_without_filter_checks_every_gold_file",
    "tests/reading/ocr/test_glm.py::test_leading_blank_output_and_spaces_are_trimmed",
    "tests/reading/ocr/test_glm.py::test_a_failed_call_returns_an_error_and_is_not_cached",
    "tests/reading/test_pdf_page.py::test_edge_case_counts_on_a_generated_page",
    "tests/reading/test_read.py::test_block_types_order_and_contract_blocks",
    "tests/reading/test_step4b2_regressions.py::test_giant_display_number_does_not_bridge_two_heading_rows",
    "tests/reading/test_step4b2_regressions.py::test_footnote_body_prefix_is_a_linked_marker_not_a_prose_number",
    "tests/reading/test_step4b2_regressions.py::test_side_heading_within_half_line_leads_its_paragraph",
    "tests/reading/test_step4b2_regressions.py::test_bold_lead_sentence_stays_in_its_paragraph",
    "tests/reading/test_step4b2_regressions.py::test_visibility_splits_outside_cropbox_and_later_image_from_prose",
    "tests/reading/test_step4b2_regressions.py::test_lone_side_heading_beside_a_wide_body_leads_its_paragraph",
    "tests/test_contact_sheet.py::test_contact_sheet_replaces_an_existing_png_atomically",
    "tests/test_creative_templates.py::test_background_art_is_perceptible_while_content_stays_calm",
    "tests/test_creative_templates.py::test_card_and_divider_tokens_are_honored_and_classic_defaults_stay_unchanged",
    "tests/test_template_renderer.py::test_specimen_exercises_every_variant_and_slide_type",
    "tests/reading/ocr/test_closeout.py::test_score_one_still_gets_the_default_second_read",
    "tests/reading/ocr/test_closeout.py::test_undetected_vertical_layout_region_is_rotated_and_second_read",
    "tests/reading/test_closeout_e2e.py::test_generated_image_pdf_real_worker_marks_failed_second_read",
    "tests/reading/test_closeout_e2e.py::test_verified_real_scan_and_powershell_wrapper",
    "tests/reading/ocr/test_closeout.py::test_scan_overlay_preserves_character_pixels_and_keeps_legend",

    "tests/reading/ocr/test_closeout.py::test_scatter_dots_agreed_as_8_are_excluded_from_prose",
    "tests/reading/ocr/test_closeout.py::test_header_footer_and_caption_are_kept_out_of_body_or_preserved",
    "tests/reading/ocr/test_closeout.py::test_code_columns_do_not_trigger_text_table_alarm",
    "tests/reading/ocr/test_closeout.py::test_rotated_stamp_and_axis_agreement_cannot_bypass_orientation",
    "tests/reading/ocr/test_closeout.py::test_scatter_crop_with_agreed_8_is_flagged",
    "tests/reading/ocr/test_closeout.py::test_repeated_margin_furniture_does_not_enter_prose",
    "tests/reading/ocr/test_closeout.py::test_scan_overlay_preserves_character_pixels_and_keeps_legend",
    "tests/reading/ocr/test_preprocess.py::test_deskew_recovers_a_known_rotation",
    "tests/reading/ocr/test_preprocess.py::test_upright_page_needs_no_rotation",
    "tests/reading/ocr/test_preprocess.py::test_every_step_is_recorded_and_can_be_switched_off",
    "tests/reading/ocr/test_preprocess.py::test_denoise_removes_isolated_specks_but_keeps_a_decimal_point",
    "tests/reading/test_cli.py::test_a_digital_pdf_gives_all_four_outputs",
    "tests/reading/test_cli.py::test_a_scanned_page_goes_through_ocr_and_shows_flags_inline",
    "tests/reading/test_cli.py::test_test_split_files_are_refused_unless_milestone",
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
    ".claude/hooks/test_guard.py::test_r3_override_requires_explicit_env",
    ".claude/hooks/test_guard.py::test_r4_blocks_indirect_reads_of_test_gold",
    ".claude/hooks/test_guard.py::test_r4_still_allows_dev_gold_and_scoped_searches",
    ".claude/hooks/test_guard.py::test_r4_indirect_rules_inactive_before_freeze",
    ".claude/hooks/test_guard.py::test_r4_blocks_search_from_the_absolute_repository_root",
    ".githooks/test_githooks.py::test_g1_allows_normal_files",
    ".githooks/test_githooks.py::test_g1_allows_pptx_templates_under_design_templates_only",
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
    ".githooks/test_githooks.py::test_g5_blocks_commits_without_exactly_one_valid_last_agent_trailer",
    ".githooks/test_githooks.py::test_g5_allows_each_allowlisted_agent_as_the_last_trailer",
    ".githooks/test_githooks.py::test_g5_checks_merge_commits_too",
    ".githooks/test_githooks.py::test_g4_blocks_push_of_a_commit_without_a_valid_agent_trailer",
    ".githooks/test_githooks.py::test_g4_checks_only_commits_from_the_baseline_onward",
    "eval/tests/test_verify_gold.py::test_gold_commit_refuses_uncommitted_gold_and_returns_head_when_clean",
    "tests/test_demo_mode.py::test_validated_demo_makes_zero_network_or_model_calls",
    "tests/test_document_store.py::test_noncontiguous_pages_and_bad_selectors",
    "tests/reading/ocr/test_reader1_worker.py::test_worker_reads_a_generated_line_offline_from_local_models",
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
    "tests/test_template_renderer.py::test_overflow_rejects_candidates_then_splits_with_part_titles",
    "tests/test_template_renderer.py::test_the_same_plan_keeps_identical_facts_values_and_sources_in_every_template",
    "tests/test_template_renderer.py::test_no_two_consecutive_content_slides_share_a_variant",
    "tests/test_template_renderer.py::test_selection_is_deterministic",
    "tests/test_template_renderer.py::test_split_slides_never_show_an_empty_card",
    "tests/test_template_renderer.py::test_rejected_facts_unknown_tables_and_invalid_templates_stop_the_render",
    "tests/test_template_renderer.py::test_titles_use_sentence_case_and_balanced_breaks",
    "tests/test_template_renderer.py::test_no_content_slide_uses_more_than_three_content_sizes",
    "tests/test_template_renderer.py::test_cards_hug_their_content_and_share_a_row_height",
    "tests/test_templates.py::test_every_gallery_template_passes_and_carries_its_metadata",
    "tests/test_templates.py::test_dividers_are_full_bleed_theme_color_with_checked_contrast",
    "tests/test_templates.py::test_pattern_and_glow_follow_the_theme_flags",
    "tests/test_templates.py::test_validator_fails_with_a_clear_reason_when_a_required_placeholder_is_missing",
    "tests/test_templates.py::test_validator_rejects_sample_slides_wrong_size_and_odd_fonts",
    "tests/contracts/test_ids.py::test_block_id_is_stable_for_repeated_inputs",
    "tests/test_demo_dashboard.py::test_every_dashboard_page_loads_from_the_cache",
    "tests/test_projector_polish.py::test_art_strength_parameters_default_to_the_old_art_and_strengthen_only_the_edges",
    "tests/test_projector_polish.py::test_layout_bias_prefers_its_variants_among_passing_candidates_and_records_unbiased_totals",
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
