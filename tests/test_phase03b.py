from __future__ import annotations

from pathlib import Path

import pytest

from matn_summarization.budget import ContextBudgeter, SourceUnit, partition_units
from matn_summarization.evidence import deduplicate_claims
from matn_summarization.inventory import (
    classify_claim_risk, completeness_metadata, normalize_technical_text,
    reconcile_model_claims, reconcile_source_statements, source_fallback_claims,
)
from matn_summarization.parity import validate_arabic_semantics, validate_english_arabic_parity
from matn_summarization.pipeline import _apply_glossary_first_use, _provenance_metadata, _summary_from_plan, render_markdown
from matn_summarization.planning import build_semantic_plan, order_claims_with_antecedents, rewrite_orphan_anaphora
from matn_summarization.prompts import map_prompt
from matn_summarization.review import build_claims_review, render_claims_review
from matn_summarization.terminology import validate_arabic_terminology
from evaluate_summary import evaluate


def make_claim(claim_id: str, text: str, *, numbers=None, terms=None, limitation=None, topic="topic", importance="core", status="unreviewed"):
    return {
        "local_claim_id": claim_id, "claim_id": claim_id, "claim_text": text, "topic": topic,
        "importance": importance, "evidence": [{"source_chunk_id": "chunk-1", "short_quote": "source quote words"}],
        "numbers_and_units": numbers or [], "technical_terms": terms or [],
        "limitation_or_uncertainty": limitation, "content_risk_flags": [],
        "review_status": status, "extraction_method": "model",
    }


def test_nonempty_chunk_without_claims_is_reported():
    units = [SourceUnit("chunk-1", "chunk-1", "A factual sentence.", None, 1, 0, 19)]
    metadata = completeness_metadata(units, [])
    assert metadata["processed_chunk_ids"] == ["chunk-1"]
    assert metadata["chunks_without_claims"] == ["chunk-1"]


def test_multiple_claims_can_come_from_one_chunk():
    text = "Alpha is one. Beta is two."
    units = [SourceUnit("chunk-1", "chunk-1", text, None, 1, 0, len(text))]
    claims = source_fallback_claims(units)
    assert len(claims) == 2
    assert {item["evidence"][0]["source_chunk_id"] for item in claims} == {"chunk-1"}


def test_distinct_numbers_are_not_deduplicated():
    kept, removed = deduplicate_claims([
        make_claim("c1", "The budget applies.", numbers=["10 minutes"]),
        make_claim("c2", "The budget applies.", numbers=["25 minutes"]),
    ])
    assert len(kept) == 2 and removed == []


def test_accuracy_and_precision_stay_distinct():
    kept, _ = deduplicate_claims([
        make_claim("c1", "The metric is reported.", terms=["Accuracy"]),
        make_claim("c2", "The metric is reported.", terms=["Precision"]),
    ])
    assert len(kept) == 2


def test_maximum_and_average_stay_distinct():
    kept, _ = deduplicate_claims([
        make_claim("c1", "Validation accuracy is used.", terms=["maximum accuracy"]),
        make_claim("c2", "Validation accuracy is used.", terms=["average accuracy"]),
    ])
    assert len(kept) == 2


def test_multiple_architecture_roles_stay_distinct():
    kept, _ = deduplicate_claims([
        make_claim("c1", "The component runs jobs.", terms=["Implementer"]),
        make_claim("c2", "The component runs jobs.", terms=["Scheduler"]),
        make_claim("c3", "The component runs jobs.", terms=["Worker"]),
    ])
    assert len(kept) == 3


def test_validation_and_training_loss_stay_distinct():
    kept, _ = deduplicate_claims([
        make_claim("c1", "The loss is reported.", terms=["validation loss"]),
        make_claim("c2", "The loss is reported.", terms=["training loss"]),
    ])
    assert len(kept) == 2


def test_execution_budget_and_training_time_stay_distinct():
    kept, _ = deduplicate_claims([
        make_claim("c1", "The time is reported.", terms=["execution budget"]),
        make_claim("c2", "The time is reported.", terms=["training time"]),
    ])
    assert len(kept) == 2


def test_limitations_are_not_replaced_by_none_found():
    claim = make_claim("c1", "A grounded fact.")
    plan = build_semantic_plan([claim], "long")
    summary = _summary_from_plan([claim], plan, "en")
    assert summary["limitations"] == []
    assert "no specific limitations" not in str(summary).casefold()


def test_synthesis_reports_omitted_claim_ids_and_warns_for_core_drop():
    claims = [make_claim(f"c{i}", f"Fact {i}.") for i in range(7)]
    plan = build_semantic_plan(claims, "short")
    assert len(plan["omitted_claim_ids"]) == 2
    assert all(item in plan["omission_reason"] for item in plan["omitted_claim_ids"])
    assert plan["coverage_warnings"]


def test_comprehensive_request_does_not_silently_drop_high_importance_claims():
    claims = [make_claim(f"c{i}", f"Fact {i}.") for i in range(12)]
    plan = build_semantic_plan(claims, "long", comprehensive=True)
    assert plan["selected_claim_ids"] == [item["claim_id"] for item in claims]
    assert plan["omitted_claim_ids"] == []


def test_raw_picture_text_is_always_excluded_and_verified_reciprocal_can_be_included():
    reciprocal = make_claim(
        "src-src-010",
        "The proxy reward is the reciprocal of validation loss (1 / loss).",
        status="human_review_required",
    )
    picture = make_claim(
        "src-src-036",
        "<!-- Start of picture text --> 0.60.50.40.3 <!-- End of picture text -->",
        status="visually_verified",
    )
    picture["content_risk_flags"] = ["contains_picture_region"]
    plan = build_semantic_plan(
        [reciprocal, picture],
        "long",
        visually_verified_claim_ids={"src-src-010", "src-src-036"},
    )
    assert plan["selected_claim_ids"] == ["src-src-010"]
    assert plan["omission_reason"]["src-src-036"] == "excluded_raw_picture_text"


def test_english_arabic_use_same_semantic_claim_plan_and_preserve_anchors():
    claim = make_claim("c1", "The maximum budget is fixed at 25 minutes and cannot change.", numbers=["25 minutes"], terms=["budget"], limitation="cannot change")
    plan = build_semantic_plan([claim], "long")
    en = _summary_from_plan([claim], plan, "en")
    ar = _summary_from_plan([claim], plan, "ar", {"c1": "الميزانية القصوى ثابتة عند 25 دقيقة ولا يمكن تغييرها."})
    for summary in (en, ar):
        summary["summary_points"][0]["citations"] = [{"pdf_page": 1}]
    result = validate_english_arabic_parity(en, ar, [claim], {"terms": {}})
    assert result["status"] == "pass"


def test_first_arabic_occurrence_includes_configured_english_term():
    claims = [make_claim("c1", "Accuracy is the metric.", terms=["Accuracy"])]
    glossary = {"terms": {"Accuracy": "الدقة (Accuracy)"}}
    assert validate_arabic_terminology([{"point_text": "الدقة هي المقياس."}], claims, glossary) == ["Accuracy"]
    assert validate_arabic_terminology([{"point_text": "الدقة (Accuracy) هي المقياس."}], claims, glossary) == []


def test_failed_terminology_validation_cannot_be_a_successful_parity_result():
    claim = make_claim("c1", "Accuracy is the metric.", terms=["Accuracy"])
    plan = build_semantic_plan([claim], "long")
    en = _summary_from_plan([claim], plan, "en")
    ar = _summary_from_plan([claim], plan, "ar", {"c1": "الدقة هي المقياس."})
    for summary in (en, ar):
        summary["summary_points"][0]["citations"] = [{"pdf_page": 1}]
    parity = validate_english_arabic_parity(en, ar, [claim], {"terms": {"Accuracy": "الدقة (Accuracy)"}})
    assert parity["status"] == "fail"
    assert parity["checks"]["required_terminology_coverage"] is False


def test_risky_figure_value_requires_review_status():
    claim = make_claim("c1", "Figure 2 reports 0.480.", numbers=["0.480"])
    result = classify_claim_risk(claim, {"chunk-1": ["extraction_order_risk"]}, {"chunk-1": "Figure 2: value 0.480"}, set())
    assert result["review_status"] == "human_review_required"
    verified = classify_claim_risk(claim, {"chunk-1": ["extraction_order_risk"]}, {"chunk-1": "Figure 2: value 0.480"}, {"chunk-1"})
    assert verified["review_status"] == "visually_verified"


def test_smaller_batching_respects_4096_context_with_headroom():
    budgeter = ContextBudgeter(4096, 1024, 512, 0.3)
    units = [SourceUnit(f"u{i}", f"c{i}", "x" * 800, None, 1, 0, 800) for i in range(8)]
    schema = '{"type":"object"}'
    def fits(items):
        if sum(len(item.text) for item in items) > 2600:
            return False
        try:
            budgeter.assert_fits(map_prompt(items), schema)
            return True
        except Exception:
            return False
    batches = partition_units(units, fits, max_units=6)
    assert len(batches) >= 3
    assert all(budgeter.assert_fits(map_prompt(batch), schema)["unused_context_headroom"] >= 0 for batch in batches)


def test_production_summarization_does_not_read_evaluation_checklist():
    root = Path(__file__).resolve().parents[1] / "matn_summarization"
    production = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "evaluation-checklist" not in production
    assert "model_from_source_inspection" not in production


def test_required_coverage_and_generated_correctness_are_separate_metrics():
    claim = make_claim("c1", "The value is 10.", numbers=["10"])
    summary = _summary_from_plan([claim], build_semantic_plan([claim], "long"), "en")
    report = evaluate(
        {"selection_chunk_ids": ["chunk-1"], "items": [{"id": "N1", "category": "number"}]},
        {"summary": summary, "claims": [claim], "evidence_audit": [{"exact_quote_match": True, "canonical_quote_match": True}]},
        {"reviewed_by_human": False, "checklist_decisions": {"N1": "pass"}, "claim_support": {}},
    )
    assert report["metrics"]["required_numeric_coverage"]["display"] == "1 / 1"
    assert report["metrics"]["generated_numeric_correctness"]["display"] == "N/A"
    assert "numeric_fidelity" not in report["metrics"]


def source_chunk(chunk_id, text, page=1):
    return {"chunk_id": chunk_id, "selection_text": text, "pdf_page": page, "content_risk_flags": []}


def test_sentence_split_across_chunks_is_reconciled_with_all_provenance():
    statements, unresolved = reconcile_source_statements([
        source_chunk("c1", "The service accepts natural language"),
        source_chunk("c2", "ideas and returns benchmark results."),
    ])
    claims = source_fallback_claims(statements=statements)
    assert unresolved == []
    assert claims[0]["claim_text"] == "The service accepts natural language ideas and returns benchmark results."
    assert [item["source_chunk_id"] for item in claims[0]["evidence"]] == ["c1", "c2"]
    assert [item["pdf_page"] for item in claims[0]["evidence"]] == [1, 1]


def test_sentence_split_across_pages_preserves_both_pages():
    statements, unresolved = reconcile_source_statements([
        source_chunk("c1", "The metric is reported in order", 2),
        source_chunk("c2", "to compare it with the baseline.", 3),
    ])
    claim = source_fallback_claims(statements=statements)[0]
    assert unresolved == []
    assert [item["pdf_page"] for item in claim["evidence"]] == [2, 3]


def test_complete_unrelated_sentences_are_not_merged_and_false_positive_is_prevented():
    statements, unresolved = reconcile_source_statements([
        source_chunk("c1", "The first experiment finished."),
        source_chunk("c2", "The second experiment used another dataset."),
    ])
    assert unresolved == []
    assert [item.text for item in statements] == ["The first experiment finished.", "The second experiment used another dataset."]
    assert all(len(item.evidence_spans) == 1 for item in statements)


def test_unresolved_fragment_fails_closed_and_model_fragments_reconcile():
    statements, unresolved = reconcile_source_statements([source_chunk("c1", "The operation continues in")])
    assert statements == [] and unresolved[0].review_reason == "unresolved_trailing_fragment"
    left = make_claim("m1", "The operation continues in")
    right = make_claim("m2", "the isolated environment.")
    merged, model_unresolved = reconcile_model_claims([left, right])
    assert model_unresolved == []
    assert merged[0]["claim_text"] == "The operation continues in the isolated environment."


def test_complete_evidence_span_is_not_truncated_to_short_quote():
    long_sentence = "The coordinator accepts a request, validates every constraint, allocates the required resources, starts the worker, records complete logs, and returns the final result to the caller."
    claim = make_claim("c1", long_sentence)
    claim["evidence"] = [{"source_chunk_id": "chunk-1", "short_quote": "The coordinator accepts a request", "exact_text": long_sentence, "start_offset": 0, "end_offset": len(long_sentence), "pdf_page": 4}]
    summary = _summary_from_plan([claim], build_semantic_plan([claim], "long"), "en")
    review = build_claims_review(summary, [claim], {"chunks": [source_chunk("chunk-1", long_sentence, 4)]})
    assert review["points"][0]["evidence"][0]["complete_evidence_span"] == long_sentence


def test_formula_and_technical_tokens_are_normalized_conservatively():
    source = "Reward is reciprocal to ( _loss_ <u>1</u><sup>) during RL</sup> for Qwen2.5Math-1.5B and selfexecution."
    normalized, notes = normalize_technical_text(source)
    assert "(1 / loss)" in normalized
    assert "Qwen2.5-Math-1.5B" in normalized
    assert "self-execution" in normalized
    assert "normalized_malformed_reciprocal_math" in notes


@pytest.mark.parametrize(
    ("english", "bad_arabic", "failure"),
    [
        ("The codebase is downloaded.", "تُنزل قاعدة البيانات.", "codebase_not_database"),
        ("Under a set clock frequency, it runs.", "يعمل تحت تردد ساعة محدد.", "scheduling_interval_not_cpu_clock"),
        ("The diff file can be patched into the codebase.", "يمكن إصلاح ملف الفروقات في قاعدة الشيفرة.", "apply_diff_not_repair_diff"),
        ("The ideator model proposes changes.", "يقترح نموذج الفكرة تغييرات.", "ideator_generates_ideas"),
        ("Accuracy is reported.", "يُبلّغ الإحكام.", "accuracy_not_precision"),
    ],
)
def test_semantic_gate_reproduces_high_risk_translation_failures(english, bad_arabic, failure):
    assert any(failure in item for item in validate_arabic_semantics("c1", english, bad_arabic))


def test_semantic_gate_accepts_preferred_high_risk_relations():
    assert validate_arabic_semantics("c1", "The codebase is downloaded.", "تُنزل قاعدة الشيفرة البرمجية.") == []
    assert validate_arabic_semantics("c2", "Under a set clock frequency, it runs.", "يعمل على فواصل زمنية محددة.") == []
    assert validate_arabic_semantics("c3", "The implementer uses a baseline codebase.", "يستخدم المُنفِّذ قاعدة شيفرة مرجعية.") == []


def test_parity_gate_preserves_maximum_average_negation_and_condition():
    claim = make_claim("c1", "If execution does not fail, maximum Accuracy is not average Accuracy.", terms=["Accuracy", "maximum", "average"])
    plan = build_semantic_plan([claim], "long")
    english = _summary_from_plan([claim], plan, "en")
    arabic = _summary_from_plan([claim], plan, "ar", {"c1": "الدقة المتوسطة ناجحة."})
    for summary in (english, arabic):
        summary["summary_points"][0]["citations"] = [{"pdf_page": 1}]
    parity = validate_english_arabic_parity(english, arabic, [claim], {"terms": {}})
    assert parity["checks"]["qualifier_preservation"] is False
    assert parity["checks"]["negation_preservation"] is False
    assert parity["checks"]["semantic_relation_preservation"] is False


def test_user_summary_groups_claims_and_uses_operational_heading_without_duplication():
    claims = [
        make_claim("c1", "The API accepts ideas and returns results."),
        make_claim("c2", "The worker halts if execution fails.", limitation="The worker halts if execution fails."),
    ]
    summary = _summary_from_plan(claims, build_semantic_plan(claims, "long"), "ar", {
        "c1": "تستقبل الواجهة الأفكار وتعيد النتائج.",
        "c2": "يتوقف العامل إذا فشل التنفيذ.",
    })
    for point in summary["summary_points"]:
        point["citations"] = [{"display": "[PDF p. 1]", "pdf_page": 1}]
    summary["coverage_status"] = {"limited_by_table_extraction": False, "limited_by_equation_extraction": False, "limited_by_picture_content": False}
    rendered = render_markdown(summary, "ar")
    assert "## حدود التشغيل وآليات التعامل مع الفشل" in rendered
    assert rendered.count("يتوقف العامل إذا فشل التنفيذ.") == 1


def _parity_for(english_text: str, arabic_text: str, *, numbers=None):
    claim = make_claim("c1", english_text, numbers=numbers or [])
    plan = build_semantic_plan([claim], "long")
    english = _summary_from_plan([claim], plan, "en")
    arabic = _summary_from_plan([claim], plan, "ar", {"c1": arabic_text})
    for value in (english, arabic):
        value["summary_points"][0]["citations"] = [{"pdf_page": 1}]
    return validate_english_arabic_parity(english, arabic, [claim], {"terms": {}})


@pytest.mark.parametrize(
    ("english", "bad_arabic", "good_arabic", "failure"),
    [
        (
            "The environment contains a baseline codebase.",
            "تحتوي البيئة على مستودع الشيفرة.",
            "تحتوي البيئة على قاعدة شيفرة مرجعية.",
            "baseline_codebase_preserved",
        ),
        (
            "The patched codebase is submitted to a cloud bucket as a .zip file.",
            "تُقدّم قاعدة الشيفرة المعدلة إلى سحابة في ملف .zip.",
            "تُرفع قاعدة الشيفرة بعد تطبيق التعديل إلى حاوية تخزين سحابية في ملف .zip.",
            "cloud_bucket_is_storage_container",
        ),
        (
            "The baseline accuracy is 0.480 and the baseline loss is 3.255.",
            "الدقة الأساسية 0.480 والخسارة الأساسية 3.255.",
            "دقة خط الأساس 0.480 وخسارة خط الأساس 3.255.",
            "baseline_metric_not_basic",
        ),
    ],
)
def test_confirmed_arabic_semantic_defects_are_reusable_rules(english, bad_arabic, good_arabic, failure):
    assert any(failure in item for item in validate_arabic_semantics("c1", english, bad_arabic))
    assert not any(failure in item for item in validate_arabic_semantics("c1", english, good_arabic))


def test_source_conditioned_arabic_normalization_repairs_the_three_confirmed_classes():
    claims = [
        make_claim("p2", "The environment contains a baseline codebase."),
        make_claim("p26", "The patched codebase is then submitted to a cloud bucket as a .zip file."),
        make_claim("p34", "The baseline accuracy is 0.480 and the baseline loss is 3.255."),
    ]
    plan = {"selected_claim_ids": ["p2", "p26", "p34"]}
    rendered = _apply_glossary_first_use({
        "p2": "تحتوي البيئة على مستودع الشيفرة (codebase).",
        "p26": "يتم تقديم قاعدة الشيفرة البرمجية المُعدّلة إلى سحابة على شكل ملف .zip.",
        "p34": "الدقة الأساسية 0.480 والخسارة (Loss) الأساسية 3.255.",
    }, claims, plan, {"terms": {}})
    assert "قاعدة شيفرة مرجعية" in rendered["p2"]
    assert rendered["p26"].startswith("تُرفع") and "حاوية تخزين سحابية" in rendered["p26"]
    assert "دقة خط الأساس" in rendered["p34"] and "خسارة خط الأساس" in rendered["p34"]


def test_source_conditioned_arabic_normalization_repairs_reusable_relation_risks():
    claims = [
        make_claim("codebase", "The implementer patches the codebase."),
        make_claim("ideator", "The ideator model generates ideas."),
        make_claim("tuning", "The algorithm fine-tunes a model."),
        make_claim("patched", "The patched codebase is submitted to a cloud bucket."),
        make_claim("cadence", "Under a set clock frequency, the scheduler downloads codebases."),
    ]
    plan = {"selected_claim_ids": [item["claim_id"] for item in claims]}
    rendered = _apply_glossary_first_use({
        "codebase": "يطبّق المُنفِّذ التعديل على قاعدة شفروية.",
        "ideator": "يولّد نموذج الفكرة أفكارًا.",
        "tuning": "تقوم الخوارزمية بتدريب دقيق لنموذج.",
        "patched": "يتم رفع قاعدة الشيفرة الأساسية (codebase) المُصلحة إلى حاوية تخزين سحابية.",
        "cadence": "تحت تردد ساعة محدد، ينزّل المجدول قواعد الشيفرة.",
    }, claims, plan, {"terms": {}})
    assert "قاعدة الشيفرة" in rendered["codebase"]
    assert "نموذج توليد الأفكار" in rendered["ideator"]
    assert "ضبطًا دقيقًا" in rendered["tuning"]
    assert "بعد تطبيق التعديل" in rendered["patched"]
    assert "فواصل زمنية محددة" in rendered["cadence"]
    for claim in claims:
        assert validate_arabic_semantics(claim["claim_id"], claim["claim_text"], rendered[claim["claim_id"]]) == []


def test_arabic_naturalness_normalizer_repairs_recurring_grammar_classes():
    claims = [
        make_claim("review", "We repeat this sequential self-review at most two times.", numbers=["2 times"]),
        make_claim("inference", "We use this inference function during final validation."),
        make_claim("job", "The scheduler prepares a job configuration to submit."),
        make_claim("benchmark", "The output is each idea's benchmark performance."),
    ]
    plan = {"selected_claim_ids": [item["claim_id"] for item in claims]}
    rendered = _apply_glossary_first_use({
        "review": "نكرّر هذا المراجعة الذاتية المتسلسلة بحد أقصى مرتين.",
        "inference": "نستخدم هذه دالة الاستدلال أثناء التحقق النهائي.",
        "job": "يعد تكوين مهمة ليتم تقديمها.",
        "benchmark": "المخرج هو أداء benchmark لكل فكرة.",
    }, claims, plan, {"terms": {}})
    assert rendered["review"].startswith("نكرّر عملية المراجعة الذاتية المتسلسلة هذه")
    assert "دالة الاستدلال هذه" in rendered["inference"]
    assert rendered["job"] == "يجهّز إعداد المهمة لإرساله."
    assert "أداء كل فكرة على الاختبار المعياري" in rendered["benchmark"]


def test_arabic_dual_numeric_equivalence_and_maximum_qualifier():
    assert _parity_for("The process runs 2 times.", "تعمل العملية مرتين.", numbers=["2 times"])["status"] == "pass"
    assert _parity_for("The process runs a maximum of 2 times.", "تعمل العملية بحد أقصى مرتين.", numbers=["2 times"])["status"] == "pass"


def test_numeric_equivalence_rejects_wrong_value_unit_and_lost_qualifier():
    wrong_value = _parity_for("The process runs 2 times.", "تعمل العملية ثلاث مرات.", numbers=["2 times"])
    wrong_unit = _parity_for("The process runs 2 minutes.", "تعمل العملية ثانيتين.", numbers=["2 minutes"])
    lost_maximum = _parity_for("The process runs a maximum of 2 times.", "تعمل العملية مرتين.", numbers=["2 times"])
    average_for_maximum = _parity_for("The maximum is 2 times.", "المتوسط مرتان.", numbers=["2 times"])
    assert wrong_value["checks"]["numeric_value_equality"] is False
    assert wrong_unit["checks"]["unit_equality"] is False
    assert lost_maximum["checks"]["qualifier_preservation"] is False
    assert average_for_maximum["checks"]["qualifier_preservation"] is False
    assert all(item["status"] == "fail" for item in (wrong_value, wrong_unit, lost_maximum, average_for_maximum))


def test_decimal_trailing_zero_normalization_is_value_equivalent():
    parity = _parity_for("The score is 0.480.", "تبلغ النتيجة 0.48.", numbers=["0.480"])
    assert parity["checks"]["numeric_value_equality"] is True


def test_aggregate_parity_cannot_pass_with_mandatory_internal_failure():
    parity = _parity_for("The process runs 2 minutes.", "تعمل العملية ثانيتين.", numbers=["2 minutes"])
    assert parity["checks"]["unit_equality"] is False
    assert parity["status"] == "fail"


def test_antecedent_and_dependent_split_sections_are_grouped_antecedent_first():
    antecedent = make_claim("a", "We implement an inference function that predicts one token.", limitation="avoid leakage")
    dependent = make_claim("b", "We use this inference function during final validation.")
    summary = _summary_from_plan([antecedent, dependent], build_semantic_plan([antecedent, dependent], "long"), "en")
    point = next(item for item in summary["summary_points"] if set(item["claim_ids"]) == {"a", "b"})
    assert point["claim_ids"] == ["a", "b"]
    assert point["point_text"].index("implement an inference function") < point["point_text"].index("use this inference function")


def test_dependency_reorder_places_late_antecedent_first():
    dependent = make_claim("b", "We use this method during validation.")
    antecedent = make_claim("a", "We define a method for validation.")
    ordered, dependencies = order_claims_with_antecedents([dependent, antecedent])
    assert [item["claim_id"] for item in ordered] == ["a", "b"]
    assert dependencies == {"b": "a"}


def test_orphan_anaphora_is_rewritten_with_explicit_noun_phrase():
    assert rewrite_orphan_anaphora("We use this inference function.", "We use this inference function.", "en") == "We use the inference function."
    assert rewrite_orphan_anaphora("نستخدم هذه الدالة للتحقق.", "We use this inference function.", "ar") == "نستخدم دالة الاستنتاج للتحقق."


def test_review_cards_expose_normalization_and_bilingual_checks():
    claim = make_claim("c1", "Reward is (1 / loss).")
    claim["normalization_notes"] = ["normalized_malformed_reciprocal_math"]
    claim["evidence"] = [{
        "source_chunk_id": "chunk-1", "short_quote": "Reward is reciprocal",
        "exact_text": "Reward is reciprocal to ( _loss_ <u>1</u><sup>)</sup>.",
        "pdf_page": 2,
    }]
    summary = _summary_from_plan([claim], build_semantic_plan([claim], "long"), "ar", {"c1": "المكافأة هي (1 / loss)."})
    summary["parity_validation"] = _parity_for("Reward is (1 / loss).", "المكافأة هي (1 / loss).")
    selection = {"chunks": [{"chunk_id": "chunk-1", "selection_text": claim["evidence"][0]["exact_text"], "pdf_page": 2, "content_risk_flags": []}]}
    review = build_claims_review(summary, [claim], selection, english_summary=_summary_from_plan([claim], build_semantic_plan([claim], "long"), "en"))
    point = review["points"][0]
    assert point["normalization"]["raw_extracted_text"] == [claim["evidence"][0]["exact_text"]]
    assert point["normalization"]["notes"][0]["normalization_type"] == "normalized_malformed_reciprocal_math"
    assert point["human_semantic_status"] == "unreviewed"
    markdown = render_claims_review(review)
    assert "| ID |" not in markdown
    assert '<div dir="ltr">' in markdown and '<div dir="rtl">' in markdown
    assert "Semantic relations / negation" in markdown


def test_provenance_excludes_calibration_and_distinguishes_generation_replay_and_deterministic():
    calibration = {"kind": "calibration", "actual_prompt_eval_count": 10, "total_duration": 100}
    render = {"kind": "render-ar-1", "actual_prompt_eval_count": 20, "total_duration": 200}
    generated = _provenance_metadata([calibration, render], cache_hits=0, cache_misses=0, bypass_result_cache=True, bypass_map_cache=True, translation_memory_reused=0, rejected_render_used=False)
    replay = _provenance_metadata([calibration], cache_hits=0, cache_misses=0, bypass_result_cache=False, bypass_map_cache=False, translation_memory_reused=3, rejected_render_used=False)
    deterministic = _provenance_metadata([calibration], cache_hits=0, cache_misses=1, bypass_result_cache=False, bypass_map_cache=False, translation_memory_reused=0, rejected_render_used=False)
    assert generated["model_calls_total"] == 1 and generated["calibration_calls"] == 1
    assert generated["model_render_calls"] == 1 and generated["provenance_classification"] == "cold"
    assert replay["generation_mode"] == "translation_memory_replay" and replay["cold_or_warm"] == "replay"
    assert deterministic["generation_mode"] == "deterministic_assembly" and deterministic["cold_or_warm"] == "deterministic"


def test_structured_term_inventory_aggregates_claim_ids_without_weakening_schema_limit():
    claims = [make_claim(f"c{i}", f"Fact {i} uses a shared term.", terms=["shared term"]) for i in range(120)]
    summary = _summary_from_plan(claims, build_semantic_plan(claims, "long"), "en")
    assert summary["key_terms"] == [{
        "term": "shared term",
        "explanation": "Term preserved from the semantic plan.",
        "claim_ids": [f"c{i}" for i in range(120)],
    }]
