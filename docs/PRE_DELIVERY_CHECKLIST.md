# Pre-delivery checklist

Owner decision, 2026-10-02: speed first on the development copy, which uses public documents only. The safeguards
below were removed, disabled, or deferred, and each one must be re-enabled and checked before the system is handed
to the ministry. Tick an item only with evidence (a commit, a test, or a report under `reports/`).

## Removed or disabled on 2026-10-02

- [ ] **Restricted-input and sealed-split access guards.** Re-enable the delivery safeguards and prove each rule with recorded evidence.
- [ ] **Fast-suite timing budget** (`checks/fast_budget.py`, `checks/test_fast_budget.py`). Decide whether delivery
      needs it. Pre-commit still runs the fast tests, with no time limit.
- [ ] **Engineering rules** in `ENGINEERING_RULES.md`: review the delivery safeguards and verify their enforcement.

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

- [ ] R-lite.3 Docling sidecar: package the separate pinned isolated environment and Heron
  weights offline with licenses/hashes; verify explicit artifacts path, no downloads,
  two-process determinism and CPU delivery cost (ADR 0006). Main runtime stays free of
  Docling and Torch.

## Batch 2 — offline sidecar package proof (2026-10-13)

- [x] Development Ubuntu/Python3.12 CPU package proof: **Docling102/102 pins** and
  **reranker34/34 pins**, official PyPI / PyTorch CPU index only; common exact pins
  reused with SHA provenance. Packages: `/home/asmaa/matn-delivery/wheelhouse-docling/`
  and `/home/asmaa/matn-delivery/wheelhouse-rerank/`. Exact freezes:
  `/home/asmaa/matn-delivery/docling.freeze.txt` and `rerank.freeze.txt`. Every wheel
  size/SHA/source/spec is in `reports/batch2-offline-delivery-manifest.json`; external
  mirror `/home/asmaa/matn-delivery/manifest.json`. No binary/font files in this repo.
- [x] Heron copy: `/home/asmaa/matn-delivery/models/heron/8f39ad3c0b4c58e9c2d2c84a38465abf757272d8/docling-project--docling-layout-heron/`;
  six files with source/copy hashes. Reranker copy:
  `/home/asmaa/matn-delivery/models/reranker/e61197ed45024b0ed8a2d74b80b4d909f1255473/Qwen--Qwen3-Reranker-0.6B/`;
  twelve files with pinned hashes, including the Apache2.0-declaring README.
- [x] Fresh `/home/asmaa/matn-delivery/verify-docling/` and `verify-rerank/` installed
  offline under `checks.egress_guard.block_egress`; freezes byte-match accepted pins.
  Install commands (from repo root, after `source scripts/dev_environment.sh`):
  `~/matn-delivery/verify-docling/bin/python out/batch2/offline-pip.py install --no-index --find-links ~/matn-delivery/wheelhouse-docling --no-deps --only-binary=:all: --no-compile --retries 0 -r ~/matn-delivery/docling.freeze.txt`;
  same command with `verify-rerank`, `wheelhouse-rerank`, `rerank.freeze.txt` for reranker.
  Helper source SHA and full original command arrays are in the manifest. Original
  creation commands used `.venv/bin/python -m venv` on each previously absent path.
- [x] Fresh Docling one arXiv dev page byte-matches full-label reference subset:
  `5140c8a9d15c684f287c569ab517333d89f6e1faa5bef40b22194fdca2639bb3`.
  Fresh reranker one fictional query (20 passages, same first two reference
  microbatches) byte-matches:
  `0b3c8942496a806277d65e19d3469948eadd0a025c488504d5095443d985b3d6`.
  Exact offline sidecar command arrays and copied-model paths are in the manifest;
  requests/reference/output/logs under `out/batch2/completion/packaging/`.
- [ ] Repeat fresh installation, license review, native binary/network policy and
  CPU/GPU cost measurement on the delivery machine. This laptop proof is CPU only;
  the Python-socket guard is not an OS firewall. No package/model item is DEFERRED
  in this run. Main runtime/requirements/lock/project wheelhouse remain unchanged.
