"""reports/step4c-ocr.md from out/reading/ocr/<config>/<subset>.json (Egyptian Arabic; terms in English)."""
from __future__ import annotations

import json
from pathlib import Path
from statistics import median

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "out" / "reading" / "ocr"
CONFIG_ORDER = ("full", "no_deskew", "no_denoise", "reader1_alone")
SUBSETS = ("dev_tune", "dev_check")


def _load(config: str, subset: str) -> dict | None:
    path = OUT / config / f"{subset}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _ratio(a: float, b: float) -> str:
    return "n/a" if not b else f"{a / b:.4f}"


def aggregate(pages: list[dict]) -> dict:
    total = lambda key: sum(p["numbers"][key] for p in pages)  # noqa: E731
    flagged = sum(p["flagged_tokens"] for p in pages)
    n = max(len(pages), 1)
    return {
        "pages": len(pages),
        "cer": _ratio(sum(p["cer"]["char_edits"] for p in pages), sum(p["cer"]["chars"] for p in pages)),
        "wer": _ratio(sum(p["cer"]["word_edits"] for p in pages), sum(p["cer"]["words"] for p in pages)),
        "median_page_cer": f"{median(p['cer']['char_edits'] / max(p['cer']['chars'], 1) for p in pages):.4f}" if pages else "n/a",
        "numbers": total("total"),
        "accuracy": _ratio(total("correct"), total("total")),
        "unflagged_accuracy": _ratio(total("unflagged_correct"), total("unflagged_total")),
        "silent_errors": total("silent_errors"), "silent_drops": total("silent_drops"),
        "flag_rate": _ratio(flagged, sum(p["reader1_tokens"] for p in pages)),
        "false_alarm_rate": _ratio(sum(p["false_alarms"] for p in pages), flagged),
        "agreement_rate": _ratio(sum(p["agreed_tokens"] for p in pages), sum(p["second_read_tokens"] for p in pages)),
        "flags_per_page": f"{flagged / n:.1f}",
        "s_without": f"{sum(p['timing']['without_second_reads'] for p in pages) / n:.1f}",
        "s_with": f"{sum(p['timing']['with_second_reads'] for p in pages) / n:.1f}",
    }


COLUMNS = [("pages", "pages"), ("cer", "CER"), ("median_page_cer", "median page CER (diagnostic)"), ("wer", "WER"), ("numbers", "أرقام GT"), ("accuracy", "exact accuracy"),
           ("silent_errors", "**silent errors**"), ("silent_drops", "silent drops"), ("flag_rate", "flag rate"),
           ("false_alarm_rate", "false-alarm rate"), ("agreement_rate", "agreement r1/r2"),
           ("flags_per_page", "flags/page"), ("s_without", "s/page من غير second reads"),
           ("s_with", "s/page بالـ second reads")]


def _table(rows: list[tuple[str, dict]], first: str) -> list[str]:
    lines = [f"| {first} | " + " | ".join(title for _, title in COLUMNS) + " |",
             "|---|" + "---:|" * len(COLUMNS)]
    lines += [f"| {name} | " + " | ".join(str(agg[key]) for key, _ in COLUMNS) + " |" for name, agg in rows]
    return lines


def write_report(path: Path = REPO / "reports" / "step4c-ocr.md") -> Path:
    lines = ["# Step 4c — قراءة الصفحات الممسوحة (OCR)", "",
             "القواعد متجمّدة في `docs/ocr_rules.md` قبل أول قياس. Reader 1 = PP-OCRv5 mobile عن طريق RapidOCR على "
             "onnxruntime (CPU). Reader 2 = GLM-OCR على Ollama، سطر بسطر للأرقام المستهدفة بس. page type هنا = "
             "`synthetic_scan` (truth مضبوطة) و`real_scan` (من غير gate لحد ما الـ GT اليدوي يتعمل).", ""]
    calibration = OUT / "calibration" / "bar.json"
    if calibration.is_file():
        c = json.loads(calibration.read_text(encoding="utf-8"))
        lines += ["## الـ confidence bar (dev-tune بس، من غير GAO p12)", "",
                  f"- الـ bar = **{c['bar']}** على {c['pages']} صفحة و{c['tokens']} رقم من reader 1.",
                  f"- أرقام غلط برّه الجداول/KPI: {c['wrong_outside_table_kpi']} (أعلى confidence فيهم "
                  f"{c['max_wrong_score']}). نسبة الأرقام تحت الـ bar: {c['below_bar_share']}.", ""]
    full = {subset: _load("full", subset) for subset in SUBSETS}
    if all(full.values()):
        tune, check = (aggregate(full[s]["pages"]) for s in SUBSETS)
        passed = tune["silent_errors"] == 0 and check["silent_errors"] == 0
        verdict = "**عدّى**" if passed else ("**overfitting**: dev-tune عدّى وdev-check لأ" if tune["silent_errors"] == 0
                                              else "**ما عدّاش**")
        lines += ["## الـ gate", "", f"- silent number errors: dev-tune **{tune['silent_errors']}**، dev-check "
                  f"**{check['silent_errors']}** → {verdict}.", ""]
    lines += ["## المقاييس (synthetic_scan)", ""]
    rows = []
    for config in CONFIG_ORDER:
        for subset in SUBSETS:
            data = _load(config, subset)
            if data:
                rows.append((f"{config} / {subset}", aggregate(data["pages"])))
    lines += _table(rows, "config / subset") + [""]
    if all(full.values()):
        kinds = sorted({k for s in SUBSETS for p in full[s]["pages"] for k in p["kinds"]})
        lines += ["## حسب نوع الصفحة (full، الـ subsetين مع بعض)", ""]
        both = [p for s in SUBSETS for p in full[s]["pages"]]
        lines += _table([(kind, aggregate([p for p in both if kind in p["kinds"]])) for kind in kinds], "kind") + [""]
        silent = [(p, d) for p in both for d in p["number_problems"]
                  if d["status"] in ("wrong", "inserted") and not d["flagged"]]
        drops = [(p, d) for p in both for d in p["number_problems"] if d["status"] == "missing" and not d["flagged"]]
        lines += ["## كل silent error (full)", ""]
        lines += [f"- {p['subset']} {p['doc_id']} p{p['page_index']}: {d['status']} expected `{d['expected']}` got "
                  f"`{d['got']}` at {[round(v, 1) for v in d['where']]}" for p, d in silent] or ["- مفيش."]
        lines += ["", f"## silent drops (full): {len(drops)}", ""]
        lines += [f"- {p['subset']} {p['doc_id']} p{p['page_index']}: expected `{d['expected']}` at "
                  f"{[round(v, 1) for v in d['where']]}" for p, d in drops[:40]] or ["- مفيش."]
        lines += [""]
    if all(full.values()):
        lines += ["## قيمة الـ consensus وحساسية الـ bar (من نفس بيانات full؛ تحليل، مش قاعدة)", "",
                  "| subset | أرقام reader 1 | غلط عند reader 1 | الـ consensus مسكها | الاتنين اتفقوا على الغلط | "
                  "silent لو reader 1 لوحده بـ bar 0.90 | 0.95 | 0.99 | 0.999 |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for subset in SUBSETS:
            tokens = [t for p in full[subset]["pages"] for t in p["tokens"]]
            wrong = [t for t in tokens if not t["correct"]]
            caught = sum(t["flagged"] for t in wrong)
            agreed_wrong = sum(t["status"] == "agreed" for t in wrong)
            at = [sum(t["score"] >= bar for t in wrong) for bar in (0.90, 0.95, 0.99, 0.999)]
            lines.append(f"| {subset} | {len(tokens)} | {len(wrong)} | {caught} | {agreed_wrong} | " +
                         " | ".join(str(a) for a in at) + " |")
        lines += ["", "\"غلط عند reader 1\" = مش مطابق للـ truth بالـ matching في `docs/ocr_rules.md` §6، "
                  "وده بيشمل الـ reference artifacts.", ""]
    real = _load("full", "real")
    if real:
        lines += ["## Real scans (full؛ من غير gate)", "",
                  "| doc | page | route | أرقام reader 1 | flagged | second-read | agreed | layer مقارن | layer مختلف | "
                  "mean confidence | s/page |", "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for p in real["pages"]:
            if "skipped" in p:
                lines.append(f"| {p['doc_key']} | - | skipped: {p['skipped'][:80]} | | | | | | | | |")
                continue
            lines.append(f"| {p['doc_key']} | {p['page_index']} | {p['route']} | {p['reader1_tokens']} | "
                         f"{p['flagged_tokens']} | {p['second_read_tokens']} | {p['agreed_tokens']} | "
                         f"{p['layer_compared']} | {p['layer_disagreements']} | {p['mean_confidence']} | "
                         f"{p['timing']['with_second_reads']} |")
        lines += [""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
