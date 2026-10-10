# Pre-delivery checklist

Owner decision, 2026-10-02: speed first on the development copy, which uses public documents only. The safeguards
below were removed, disabled, or deferred, and each one must be re-enabled and checked before the system is handed
to the ministry. Tick an item only with evidence (a commit, a test, or a report under `reports/`).

## Removed or disabled on 2026-10-02

- [ ] **Claude guard hooks (R1–R5).** They were unregistered in `.claude/settings.json` (the registration is in `f617c96`). The code and tests stay in
      `.claude/hooks/guard.py` and `.claude/hooks/test_guard.py`. Re-register them, then start a new session (hook
      config is read at session start) and prove each rule live.
- [ ] **Fast-suite timing budget** (`checks/fast_budget.py`, `checks/test_fast_budget.py`). Decide whether delivery
      needs it. Pre-commit still runs the fast tests, with no time limit.
- [ ] **The long rule set** in the old `CLAUDE.md` (rules 1–15), restorable from git history. Review which rules the
      delivered system needs.

## Deferred hardening

- [ ] **Network block plus an egress test.** A check that proves the pipeline opens no socket except 127.0.0.1.
- [ ] **Offline install on Ubuntu.** Python 3.12 is selected on both Ubuntu machines. Verify the recorded Linux
      wheelhouse and `--no-index` install on the delivery machine; prepare GPU builds there (audit F-04).
- [ ] **F-03 no-proxy opener** for every Ollama call (`audit/proposed-diffs/`).
- [ ] **Streamlit bound to loopback** (127.0.0.1), with its startup network call disabled.
- [ ] **Ollama:** auto-update off and cloud models disabled (audit F-53).
- [ ] **PyMuPDF AGPL decision** (ADR-0001): accept the AGPL, buy a commercial license, or migrate. Also settle the
      pdftotext license question (ADR-0002).
- [ ] **Logs never contain document content**: hashes and IDs only, with a test that scans the run logs.
- [ ] **A full audit** of the delivered tree, like `audit/AUDIT.md`.
- [ ] **A cross-review of the whole codebase** by an independent agent or person.

## OCR قبل التسليم (Step 4c close-out)

- [ ] **Client Windows Application Control:** allowlisting أو signing للـ OCR binaries (onnxruntime/OpenCV/Paddle)،
      وتجربة على سياسة WDAC/AppLocker الفعلية. تغيير أمان اللابتوب مش حل تسليم.
- [ ] **pymupdf-layout license review:** مراجعة قانونية مستقلة قبل أي استخدام؛ مش dependency في مسار OCR الحالي.
- [ ] **Paddle vs RapidOCR parity على Linux:** نفس صفحات dev ونفس PP-OCRv5 models، مقارنة الأرقام/الصناديق؛
      ONNX conversion لوحده مش دليل تطابق النتائج.
- [ ] **GPU:** قياس PaddleOCR-VL وreader 3 (TeleOCR/OvisOCR2)، مع hashes، egress test، ووقت فعلي؛
      ممنوع تحويل توقع السرعة لنتيجة مقاسة.
- [ ] **Human real-scan GT:** مراجعة كل رقم من الصور والتوقيع في الأداة قبل إعلان real-scan accuracy أو true
      false-alarm rate. إغلاق Step 4c يتطلب إنهاء البنود المحجوبة وقرار gate لو فشل.

## الخطوط قبل التسليم — قرار المالكة 2026-10-10 (لم يُنفّذ بعد)

- [ ] **Microsoft fonts لا يمكن تثبيتها على Ubuntu delivery server.** إعداد MATN_FONT_DIR الذي يقرأ originals
      من Windows read-only هو للتطوير على اللابتوب فقط؛ لا تنقل ملفات الخطوط مع repo أو wheelhouse أو التسليم.
- [ ] **القوالب تحتفظ بالخطوط الموجودة على أجهزة Windows في الوزارة**؛ السيرفر يقيس بخطوط open metric-compatible:
      Carlito بدل Calibri، Caladea بدل Cambria، Gelasio بدل Georgia، Selawik بدل Segoe UI.
- [ ] **Selawik تقريبي:** قِس فرق القياس وأضف safety margin مقاسًا؛ لا تفترض تطابقه التام مع Segoe UI.
- [ ] **أعد بناء قوالب Bahnschrift** بخط له substitute؛ لا تضع fallback غير متحقق منه مكانه.
- [ ] **Specimen fit parity test:** يثبت أن fit/overflow يوافق بين original وsubstitute fonts على specimen،
      ويغطي الأنماط والأحجام والهوامش المستخدمة فعليًا؛ سجّل الأدلة ونتيجة safety margin قبل التسليم.

هذه خطة تسليم مسجلة فقط؛ لا substitutions أو template rebuild أو parity test الآن.
