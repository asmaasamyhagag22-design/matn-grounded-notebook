from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .evidence import canonical_text
from .terminology import validate_arabic_terminology


NUMBER_TOKEN_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?%?(?=(?:[BMK]\b)|[^\w.]|$)")
UNIT_RE = re.compile(r"\b(?:minutes?|seconds?|hours?|GPUs?|tokens?|times?|files?|MB|GB|B|M|K)\b", re.IGNORECASE)
NUMBER_WITH_UNIT_RE = re.compile(
    r"(?<![\w.])(?P<value>\d+(?:\.\d+)?%?)\s*(?P<unit>minutes?|seconds?|hours?|GPUs?|tokens?|times?|files?|MB|GB|B|M|K)\b",
    re.IGNORECASE,
)

ARABIC_DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩٫", "0123456789.")
ARABIC_UNITS: dict[str, re.Pattern[str]] = {
    "minute": re.compile(r"(?:دقيقة|دقائق|دقيقت(?:ان|ين))"),
    "second": re.compile(r"(?:ثانية|ثوان|ثانيت(?:ان|ين))"),
    "hour": re.compile(r"(?:ساعة|ساعات|ساعت(?:ان|ين))"),
    "gpu": re.compile(r"(?:GPU|GPUs|وحد(?:ة|ات) معالجة رسومات)"),
    "token": re.compile(r"(?:token|tokens|رمز|رموز|رمز(?:ان|ين))"),
    "time": re.compile(r"(?:مرة|مرات|مرت(?:ان|ين))"),
    "file": re.compile(r"(?:ملف|ملفات|ملف(?:ان|ين))"),
    "mb": re.compile(r"MB\b", re.IGNORECASE),
    "gb": re.compile(r"GB\b", re.IGNORECASE),
    "b": re.compile(r"(?:B\b|مليار)"),
    "m": re.compile(r"(?:M\b|مليون)"),
    "k": re.compile(r"(?:K\b|ألف)"),
}

QUALIFIER_PATTERNS: dict[str, re.Pattern[str]] = {
    "maximum": re.compile(r"\b(?:maximum|max|at most)\b", re.IGNORECASE),
    "average": re.compile(r"\baverage\b", re.IGNORECASE),
    "minimum": re.compile(r"\b(?:minimum|min|at least)\b", re.IGNORECASE),
    "fixed": re.compile(r"\bfixed\b", re.IGNORECASE),
    "only": re.compile(r"\bonly\b", re.IGNORECASE),
    "first": re.compile(r"\bfirst\b", re.IGNORECASE),
    "high": re.compile(r"\bhigh\b", re.IGNORECASE),
    "most": re.compile(r"\bmost\b", re.IGNORECASE),
}

ARABIC_QUALIFIERS: dict[str, re.Pattern[str]] = {
    "maximum": re.compile(r"(?:أقصى|القصوى|بحد أقصى|حد أقصى|أعلى)"),
    "average": re.compile(r"متوسط"),
    "minimum": re.compile(r"(?:أدنى|بحد أدنى|حد أدنى)"),
    "fixed": re.compile(r"ثابت"),
    "only": re.compile(r"فقط"),
    "first": re.compile(r"(?:أول|الأول)"),
    "high": re.compile(r"(?:مرتفع|عال(?:ية|ي)?)"),
    "most": re.compile(r"معظم"),
}

NEGATION_EN = re.compile(r"\b(?:no|not|cannot|can't|do not|does not|without|prevent|avoid|failed|fails|failure|halts?)\b", re.IGNORECASE)
NEGATION_AR = re.compile(r"(?:لا يمكن|ولا|لم |لن |\bلا\b|\bليس\b|\bغير\b|\bدون\b|منع|تجن[ّ]?ب|\bيفشل\b|\bفشل\b|\bيتوقف\b|\bيوقف\b)")

CONDITIONS_EN = {
    "if": re.compile(r"\bif\b", re.IGNORECASE),
    "once": re.compile(r"\bonce\b", re.IGNORECASE),
    "when": re.compile(r"\bwhen\b", re.IGNORECASE),
}
CONDITIONS_AR = {
    "if": re.compile(r"\bإذا\b"),
    "once": re.compile(r"(?:بمجرد|حالما)"),
    "when": re.compile(r"(?:عندما|حين|عند)"),
}

# Reusable translation-risk rules. These describe domain concepts, not any
# document's expected answers. Preferred/forbidden expressions may be extended
# by a glossary without weakening these built-in safety checks.
SEMANTIC_RULES = (
    {
        "name": "codebase_not_database", "source": r"\bcodebases?\b",
        "required_any": (r"(?:قاعدة|قواعد) (?:ال)?شيفرة", r"مستودع الشيفرة"),
        "forbidden": (r"قاعدة البيانات", r"قواعد البيانات"),
    },
    {
        "name": "baseline_codebase_preserved", "source": r"\bbaseline codebase\b",
        "required_any": (
            r"قاعدة(?: الشيفرة)?[^.،؛]{0,24}مرجعي",
            r"قاعدة(?: الشيفرة)?[^.،؛]{0,24}(?:ال)?أساسي",
        ),
        "forbidden": (),
    },
    {
        "name": "baseline_metric_not_basic", "source": r"\bbaseline\s+(?:accuracy|loss)\b",
        "required_any": (r"خط الأساس", r"القيمة المرجعية"),
        "forbidden": (r"(?:الدقة|الخسارة)[^.،؛]{0,16}(?:ال)?أساسي",),
    },
    {
        "name": "cloud_bucket_is_storage_container", "source": r"\bcloud bucket\b",
        "required_any": (r"حاوية تخزين سحابية", r"مستودع تخزين سحابي"),
        "forbidden": (r"إلى سحابة(?:\s|[.،؛])", r"سلة سحابية"),
    },
    {
        "name": "cloud_bucket_submission", "source": r"\bsubmitted to a cloud bucket\b",
        "required_any": (r"(?:ت[ُ]?رفع|يرفع|رفع|إرسال|تقديم)[^.،؛]{0,64}حاوية تخزين سحابية",),
        "forbidden": (),
    },
    {
        "name": "patched_codebase_state", "source": r"\bpatched codebase\b",
        "required_any": (r"بعد تطبيق التعديل", r"المعد[ّ]?لة", r"المصح[ّ]?حة"),
        "forbidden": (),
    },
    {
        "name": "zip_artifact_preserved", "source": r"\.zip file\b",
        "required_any": (r"\.zip",),
        "forbidden": (),
    },
    {
        "name": "scheduling_interval_not_cpu_clock", "source": r"\bclock frequency\b",
        "required_any": (r"فواصل زمنية", r"وتيرة زمنية", r"دوري(?:ة|اً)"),
        "forbidden": (r"تردد ساعة",),
    },
    {
        "name": "apply_diff_not_repair_diff", "source": r"\b(?:diff file|code diff).*\bpatch(?:ed)?\b|\bpatch(?:ed)?\b.*\b(?:diff file|code diff)\b",
        "required_any": (r"تطبيق", r"دمج"),
        "forbidden": (r"إصلاح ملف الفروقات", r"ملف فروقات[^.،؛]*إصلاحه"),
    },
    {
        "name": "ideator_generates_ideas", "source": r"\bideator model\b",
        "required_any": (r"نموذج توليد الأفكار", r"نموذج اقتراح الأفكار"),
        "forbidden": (r"نموذج الفكرة",),
    },
    {
        "name": "parallel_generation_relation", "source": r"\bsample\s+\d+\s+code diff files in parallel\b",
        "required_any": (r"يول[ّ]?د", r"توليد", r"ينتج", r"إنشاء", r"أخذ عينات"),
        "forbidden": (),
    },
    {
        "name": "gpu_compute_cluster", "source": r"\bcluster with GPU\b",
        "required_any": (r"(?:عنقود|مجموعة) (?:ال)?حوسبة", r"مجموعة حاسوبية"),
        "forbidden": (r"العنقودية",),
    },
    {
        "name": "accuracy_not_precision", "source": r"\baccuracy\b",
        "required_any": (r"(?:ال)?دقة",),
        "forbidden": (r"الإحكام",),
    },
    {
        "name": "fine_tuning_not_proofreading", "source": r"\bfinetunes?\b|\bfine-tun(?:e|es|ing)\b",
        "required_any": (r"ضبط[^.،؛]*دقيق", r"[يت]ضبط"),
        "forbidden": (r"تدقيق نموذج",),
    },
)

ARABIC_GRAMMAR_RISKS = (
    r"إذا نجحت تنفيذ", r"إذا فشلت التنفيذ", r"بحد أقصى\s+\d+\s+مرات",
    r"تستقبل[^.،؛]+وتخصيص الموارد", r"قاعدة الكود المصلحة", r"المنف[ّ]?ذ الأفكار",
    r"\bلنمثلة\b", r"نكر[ّ]?ر هذه عملية",
)

ROLE_ANCHORS = {
    "implementer": (r"\bimplementer\b", r"(?:ال)?منف[ّ]?ذ"),
    "scheduler": (r"\bscheduler\b", r"(?:ال)?م[ُ]?جدو[ِّ]?ل"),
    "worker": (r"\bworker\b", r"(?:ال)?عامل"),
    "user": (r"\buser\b", r"(?:ال)?مستخدم"),
}
RELATION_ANCHORS = {
    "generate": (r"\b(?:generate|generates|generated)\b", r"(?:يول[ّ]?د|توليد|ينشئ|إنشاء|ينتج|إنتاج)"),
    "apply": (r"\b(?:apply|applies|patched into|patch into)\b", r"(?:يطب[ّ]?ق|تطبيق|يدمج|دمج)"),
    "allocate": (r"\b(?:allocate|allocates)\b", r"(?:يخص[ّ]?ص|تخصيص|يوز[ّ]?ع|توزيع)"),
    "download": (r"\bdownloads?\b", r"(?:ينز[ّ]?ل|ت[ُ]?نز[ّ]?ل|تنزيل|يحم[ّ]?ل|تحميل|يجلب|استرجاع)"),
    "upload": (r"\buploads?\b", r"(?:يرفع|رفع|يحم[ّ]?ل|تحميل|يودع|إرسال)"),
    "halt": (r"\bhalts?\b", r"(?:يتوقف|يوقف)"),
}
OBJECT_ANCHORS = {
    "resources": (r"\bresources?\b", r"(?:ال)?موارد"),
    "results": (r"\bresults?\b", r"(?:ال)?نتائج"),
    "logs": (r"\blogs?\b", r"(?:ال)?سجل(?:ات)?"),
    "experiment": (r"\bexperiments?\b", r"(?:ال)?تج(?:ربة|ارب)"),
}


def semantic_anchors(text: str) -> dict[str, list[str]]:
    return {
        "numeric_values": sorted(set(NUMBER_TOKEN_RE.findall(text))),
        "units": sorted({match.group(0).casefold() for match in UNIT_RE.finditer(text)}),
        "numeric_items": [
            {"value": match.group("value"), "unit": match.group("unit").casefold()}
            for match in NUMBER_WITH_UNIT_RE.finditer(text)
        ],
        "qualifiers": sorted(name for name, pattern in QUALIFIER_PATTERNS.items() if pattern.search(text)),
        "negation_present": bool(NEGATION_EN.search(text)),
        "conditions": sorted(name for name, pattern in CONDITIONS_EN.items() if pattern.search(text)),
    }


def validate_arabic_semantics(claim_id: str, english: str, arabic: str) -> list[str]:
    # Harakat are orthographic, not semantic. Strip them for relation matching
    # so fully vocalized forms such as المُنفِّذ do not become false negatives.
    arabic = re.sub(r"[\u064b-\u065f\u0670]", "", arabic)
    failures: list[str] = []
    for rule in SEMANTIC_RULES:
        if not re.search(rule["source"], english, re.IGNORECASE):
            continue
        if rule["required_any"] and not any(re.search(pattern, arabic) for pattern in rule["required_any"]):
            failures.append(f"{claim_id}:{rule['name']}:preferred_relation_missing")
        for forbidden in rule["forbidden"]:
            if re.search(forbidden, arabic):
                failures.append(f"{claim_id}:{rule['name']}:forbidden_translation")
    anchors = semantic_anchors(english)
    for condition in anchors["conditions"]:
        if not CONDITIONS_AR[condition].search(arabic):
            failures.append(f"{claim_id}:condition_{condition}_missing")
    for pattern in ARABIC_GRAMMAR_RISKS:
        if re.search(pattern, arabic):
            failures.append(f"{claim_id}:arabic_grammar_risk")
    for name, (source, target) in ROLE_ANCHORS.items():
        if re.search(source, english, re.IGNORECASE) and not re.search(target, arabic):
            failures.append(f"{claim_id}:subject_{name}_missing")
    for name, (source, target) in RELATION_ANCHORS.items():
        if re.search(source, english, re.IGNORECASE) and not re.search(target, arabic):
            failures.append(f"{claim_id}:relation_{name}_missing")
    for name, (source, target) in OBJECT_ANCHORS.items():
        if re.search(source, english, re.IGNORECASE) and not re.search(target, arabic):
            failures.append(f"{claim_id}:object_{name}_missing")
    return failures


def _citation_signature(summary: dict[str, Any]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = {}
    for point in summary["summary_points"]:
        pages = sorted({item["pdf_page"] for item in point.get("citations", [])})
        for claim_id in point["claim_ids"]:
            result[claim_id] = pages
    return result


def _canonical_decimal(value: str) -> Decimal | None:
    normalized = value.translate(ARABIC_DIGIT_TRANSLATION).rstrip("%")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _unit_key(unit: str) -> str:
    value = unit.casefold()
    if value.startswith("minute"):
        return "minute"
    if value.startswith("second"):
        return "second"
    if value.startswith("hour"):
        return "hour"
    if value.startswith("gpu"):
        return "gpu"
    if value.startswith("token"):
        return "token"
    if value.startswith("time"):
        return "time"
    if value.startswith("file"):
        return "file"
    return value


def _arabic_preserves_number(value: str, rendered: str, rendered_numbers: set[str]) -> bool:
    expected = _canonical_decimal(value)
    if expected is not None and any(_canonical_decimal(candidate) == expected for candidate in rendered_numbers):
        return True
    if expected == Decimal(2) and re.search(r"(?:مرتين|مرتان|اثنتين|اثنان|اثنين|كلا|كلتا)", rendered):
        return True
    return False


def _arabic_preserves_numeric_item(value: str, unit: str, rendered: str, rendered_numbers: set[str]) -> tuple[bool, bool]:
    key = _unit_key(unit)
    unit_pattern = ARABIC_UNITS.get(key)
    unit_ok = bool(unit_pattern and unit_pattern.search(rendered))
    if key == "time" and _canonical_decimal(value) == Decimal(2) and re.search(r"مرت(?:ان|ين)", rendered):
        return True, True
    return _arabic_preserves_number(value, rendered, rendered_numbers), unit_ok


def validate_english_arabic_parity(
    english: dict[str, Any],
    arabic: dict[str, Any],
    selected_claims: list[dict[str, Any]],
    glossary: dict[str, Any],
) -> dict[str, Any]:
    expected_ids = set(english["selected_claim_ids"])
    arabic_ids = {claim_id for point in arabic["summary_points"] for claim_id in point["claim_ids"]}
    english_ids = {claim_id for point in english["summary_points"] for claim_id in point["claim_ids"]}
    claim_map = {claim["claim_id"]: claim for claim in selected_claims}
    arabic_points = arabic.get("claim_renderings") or {
        claim_id: point["point_text"]
        for point in arabic["summary_points"]
        for claim_id in point["claim_ids"]
    }
    numeric_failures: list[str] = []
    unit_failures: list[str] = []
    qualifier_failures: list[str] = []
    negation_failures: list[str] = []
    semantic_failures: list[str] = []
    for claim_id in sorted(expected_ids):
        anchors = semantic_anchors(claim_map[claim_id]["claim_text"])
        rendered = canonical_text(arabic_points.get(claim_id, ""))
        rendered_ascii = rendered.translate(ARABIC_DIGIT_TRANSLATION)
        rendered_numbers = set(NUMBER_TOKEN_RE.findall(rendered_ascii))
        for value in anchors["numeric_values"]:
            if not _arabic_preserves_number(value, rendered, rendered_numbers):
                numeric_failures.append(f"{claim_id}:{value}")
        for item in anchors["numeric_items"]:
            number_ok, unit_ok = _arabic_preserves_numeric_item(item["value"], item["unit"], rendered, rendered_numbers)
            if not number_ok and f"{claim_id}:{item['value']}" not in numeric_failures:
                numeric_failures.append(f"{claim_id}:{item['value']}")
            if not unit_ok:
                unit_failures.append(f"{claim_id}:{item['unit']}")
        for qualifier in anchors["qualifiers"]:
            if not ARABIC_QUALIFIERS[qualifier].search(rendered):
                qualifier_failures.append(f"{claim_id}:{qualifier}")
        if anchors["negation_present"] and not NEGATION_AR.search(rendered):
            negation_failures.append(claim_id)
        semantic_failures.extend(validate_arabic_semantics(claim_id, claim_map[claim_id]["claim_text"], rendered))
    terminology_failures = validate_arabic_terminology(arabic["summary_points"], selected_claims, glossary)
    english_limitations = {claim_id for item in english["limitations"] for claim_id in item["claim_ids"]}
    arabic_limitations = {claim_id for item in arabic["limitations"] for claim_id in item["claim_ids"]}
    checks = {
        "selected_claim_id_set_equality": expected_ids == english_ids == arabic_ids,
        "numeric_value_equality": not numeric_failures,
        "unit_equality": not unit_failures,
        "citation_equality": _citation_signature(english) == _citation_signature(arabic),
        "required_terminology_coverage": not terminology_failures,
        "limitation_coverage": english_limitations == arabic_limitations,
        "qualifier_preservation": not qualifier_failures,
        "negation_preservation": not negation_failures,
        "semantic_relation_preservation": not semantic_failures,
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "failures": {
            "numeric_values": numeric_failures,
            "units": unit_failures,
            "terminology": terminology_failures,
            "qualifiers": qualifier_failures,
            "negations": negation_failures,
            "semantic_relations": semantic_failures,
        },
        "semantic_risk_assessment": "automated_gate_only_human_semantic_status_unreviewed",
    }
