# Matn - local PDF evidence store and grounded summarization

Current verified gates:

- `PHASE_01_VERIFIED_FOR_SUPPORTED_PROFILE`
- `PHASE_02_VERIFIED_FOR_REVIEW_ASSISTED_SUPPORTED_PROFILE`
- `PHASE_03_IMPLEMENTED_AND_LOCALLY_EVALUATED_PENDING_HUMAN_REVIEW`
- `PHASE_04A_MVP_IMPLEMENTED_AND_VISUALLY_VERIFIED`

Phase 04A adds a local English presentation MVP. It does not change the Phase
03B review status above and does not imply approval of Arabic output.

## Phase 04A English presentation MVP

### Launch the book demo

The prepared primary sample is Chapter 2 of *Build a Large Language Model (From
Scratch)* by Sebastian Raschka. It opens without an inference call during the
demo. From this checkout, run:

```powershell
cd C:\Users\asmaa\Documents\notebooklm\matn
.\.venv\Scripts\python.exe -m streamlit run .\app.py
```

The application opens at `http://localhost:8501`. It uses a wide, English-only
interface and exposes only the Phase 04A workflow.

### Primary prepared sample

1. Leave `Sample book chapter` selected.
2. Click `Create presentation`.
3. Review `Overview`, `Presentation`, and `Sources`.
4. Download the PowerPoint. The deck plan remains under `Advanced processing details`.

This route loads the pre-reviewed 10-slide book presentation immediately and
makes zero model calls while opening it. The preparation run used only local
`qwen3.5:9b` at `http://127.0.0.1:11434`; the cold run used seven map calls and
the warm replay used seven cache hits. Final artifacts are under
`output/book-demo/`.

### Upload a PDF

1. Select `Upload a PDF`.
2. Upload a text-based PDF.
3. Enter a physical 1-based PDF page range.
4. Confirm the CPU-time notice, then click `Create presentation`.
5. Review the result before downloading it.

Live generation contacts only `http://127.0.0.1:11434` and uses
`qwen3.5:9b`. CPU-only generation can take a long time, especially on a cold
model. A cache hit and cache miss are reported explicitly. There is no cloud
fallback. A failed live run leaves the validated cached demo unchanged.

### Local-only statement and MVP limitations

- Inference endpoints must resolve to loopback; non-loopback endpoints fail
  closed.
- The prepared book sample performs no inference while opening and uses physical
  PDF pages 43–49 (printed pages 21–27).
- Uploaded PDFs must contain extractable text. OCR and scanned/image-only PDFs
  are outside this MVP.
- Live Local Generation uses bounded sentence claims from the selected text and
  one local structured planning call. It does not claim human semantic review.
- The UI is English-only. Arabic, chat, agents, authentication, databases,
  cloud deployment, and arbitrary theme controls are intentionally absent.
- Phase 03B remains
  `PHASE_03_IMPLEMENTED_AND_LOCALLY_EVALUATED_PENDING_HUMAN_REVIEW`.
- The previous research-paper presentation remains available as the automatic
  fallback under `output/phase04a-english-demo/`.

Phase 03B adds sentence-aware boundary reconciliation, a lossless English
evidence inventory with ordered multi-span provenance, a frozen canonical
semantic plan, coherent summaries, deterministic citations and review
packages, and controlled Arabic rendering of that exact plan. Arabic output is
checked by both structural parity and reusable high-risk semantic-relation
rules; those automated gates are not semantic support or language-quality
approval. The phase therefore remains pending independent human review.

## Phase 03 quick start (Windows PowerShell)

Keep the PDF, reviewed store, selection, glossary, cache, and generated run under
ignored `documents/` and `output/` paths.

```powershell
.\.venv\Scripts\python.exe .\summarize_selection.py `
  --selection ".\output\phase02-final-sec-2-2.json" `
  --document-store ".\output\phase02-store-final\document-store.json" `
  --pdf ".\documents\2601.14525v1.pdf" `
  --language en `
  --audience "junior AI engineer" `
  --length long `
  --model "qwen3.5:9b" `
  --strategy hierarchical `
  --num-predict 1536 `
  --cache ".\output\.phase03b-map-cache" `
  --out ".\output\summary-en"
```

Arabic is never an independent summarization run. Render it from the frozen
English plan:

```powershell
.\.venv\Scripts\python.exe .\summarize_selection.py `
  --selection ".\output\phase02-final-sec-2-2.json" `
  --document-store ".\output\phase02-store-final\document-store.json" `
  --pdf ".\documents\2601.14525v1.pdf" `
  --language ar `
  --audience "مهندس ذكاء اصطناعي مبتدئ" `
  --length long `
  --glossary ".\examples\terminology.example.json" `
  --semantic-plan ".\output\summary-en\semantic-plan.json" `
  --model "qwen3.5:9b" `
  --strategy hierarchical `
  --num-predict 512 `
  --out ".\output\summary-ar"
```

If an Arabic rendering fails its semantic gate, publication is atomic: one
constrained repair is allowed, then the run fails and writes a rejected
human-review artifact. `--rejected-render` can revalidate that artifact against
the same frozen plan; `--translation-memory` can reuse exact accepted claim
translations only when model, glossary, and render-prompt identities match.

The CLI requires the original PDF and store so it can reject changed source
files and identity mismatches before inference. It refuses non-loopback Ollama
URLs and existing output paths. Normal runs use `num_ctx=4096`, temperature 0,
`stream=false`, and `think=false`; the local model must advertise thinking
control. A direct baseline is available with `--strategy direct`.

Evaluate deterministic citation/quote metrics, optionally adding a separate
human review file for semantic metrics:

```powershell
.\.venv\Scripts\python.exe .\evaluate_summary.py `
  --checklist ".\documents\phase03\evaluation-checklist.json" `
  --run ".\output\summary-run" `
  --out ".\output\summary-evaluation.json"
```

See `docs/phase03_design.md`, `docs/phase03b_coverage_audit.md`, and
`docs/phase03b_acceptance.md` for contracts, measurements, failures, metrics,
and review gates.

Phase 02 adds deterministic document structure, reviewed section indexing, and
page/section-scoped source selection. It does **not** summarize content and does
not use an LLM, Ollama, RAG, a vector database, agents, OCR, or PowerPoint.

## Phase 02 quick start (Windows PowerShell)

Start with completed raw and structured Phase 01 runs that cover the same PDF
pages. A full-document index should use full-document runs.

```powershell
cd C:\path\to\matn
.\.venv\Scripts\python.exe .\inspect_pdf.py `
  --pdf ".\documents\paper.pdf" --pages "1-42" `
  --extractor raw --out ".\output\paper-raw"
.\.venv\Scripts\python.exe .\inspect_pdf.py `
  --pdf ".\documents\paper.pdf" --pages "1-42" `
  --extractor structured --out ".\output\paper-structured"
```

Build a baseline index. Heading-only evidence remains `proposed` and cannot be
selected as confirmed without an explicit flag.

```powershell
.\.venv\Scripts\python.exe .\build_document_index.py `
  --pdf ".\documents\paper.pdf" `
  --raw-run ".\output\paper-raw" `
  --structured-run ".\output\paper-structured" `
  --out ".\output\paper-store"
```

For reviewed documents, pass a local correction file. Keep real-document
corrections and generated stores in ignored paths such as `documents/` and
`output/`.

```powershell
.\.venv\Scripts\python.exe .\build_document_index.py `
  --pdf ".\documents\paper.pdf" `
  --raw-run ".\output\paper-raw" `
  --structured-run ".\output\paper-structured" `
  --manual-corrections ".\documents\paper-corrections.json" `
  --out ".\output\paper-store-reviewed"
```

List IDs before selecting. This avoids silently deciding whether “the first two
sections” includes Abstract or subsections.

```powershell
.\.venv\Scripts\python.exe .\select_source.py `
  --document-store ".\output\paper-store-reviewed" --list-sections
```

Create a section-scoped selection. End-exclusive section anchors prevent text
from the next same/higher-level section entering the result.

```powershell
.\.venv\Scripts\python.exe .\select_source.py `
  --document-store ".\output\paper-store-reviewed" `
  --sections "sec-2,sec-3" --out ".\output\selection-sections.json"
```

Create a page-scoped selection. Every extracted block on the explicit PDF pages
is included; non-contiguous pages remain non-contiguous.

```powershell
.\.venv\Scripts\python.exe .\select_source.py `
  --document-store ".\output\paper-store-reviewed" `
  --pages "2-5,8" --out ".\output\selection-pages.json"
```

Use `--allow-unconfirmed` only when intentionally selecting `proposed` or
conflicting evidence. The selection records that decision and emits a warning.
Source content is written to `--out`, never printed by default.

Run the deterministic evaluator with reviewed local ground truth, then the full
regression suite:

```powershell
.\.venv\Scripts\python.exe .\evaluate_document_index.py `
  --document-store ".\output\paper-store-reviewed" `
  --expectations ".\documents\paper-ground-truth.json" `
  --out ".\output\paper-index-evaluation.json"
.\.venv\Scripts\python.exe -m pytest -q
```

### Numbering and evidence semantics

- `pdf_page` is the physical 1-based page position in the PDF.
- `page_label` is optional PDF metadata and may be non-numeric.
- `printed_page` is populated only by a human-reviewed correction; otherwise it
  is `null`.
- Page-scoped selection includes whole requested pages. Section-scoped selection
  starts at the heading anchor and ends immediately before the next heading at
  the same or a higher level.
- `proposed` means the evidence has not passed the confirmation gate.
  `confirmed` means outline and extracted heading agree, or a human explicitly
  confirmed it. Conflicts never become confirmed silently.
- Repeated edge lines are candidates only. Nothing is removed from raw or
  structured evidence. Only manually confirmed repetitive headers/footers are
  excluded from selection text, with the excluded lines and reason retained.
- The section index is a local evidence index, not a semantic guarantee for an
  unknown PDF. Raw text and the original PDF remain evidence alongside the
  structured Markdown.

Schemas are in `schemas/document-store.schema.json` and
`schemas/source-selection.schema.json`. Design and acceptance details are in
`docs/phase02_design.md` and `docs/phase02_acceptance.md`.

## Phase 01 extraction baseline

Matn currently provides two local, page-preserving extraction paths:

- `raw`: PyMuPDF `Page.get_text("text", sort=False)` for diagnostic text.
- `structured`: PyMuPDF4LLM Markdown with `pymupdf_layout` enabled and OCR
  explicitly disabled (`use_ocr=False`, `force_ocr=False`).

No LLM, Ollama, OCR, Docling, upload, or network call is used at runtime. Every
selected PDF page has its own output file and manifest record. A run is first
written to an owned hidden staging directory and only published by a same-volume
directory rename after every requested page and the manifest have completed.

Current phase status: `PHASE_01_VERIFIED_FOR_SUPPORTED_PROFILE`. Phase 01C used
a local 42-page English research PDF with 18 visually preselected pages and
private, pre-authored expectations. The supported profile and exclusions are
documented in `docs/phase01c_acceptance.md`.

## Windows setup

```powershell
cd C:\path\to\matn
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
```

Tested versions are pinned in `requirements.lock.txt`. The primary versions are:

- Python 3.11.9
- PyMuPDF 1.28.2
- PyMuPDF4LLM 1.28.2
- pymupdf-layout 1.28.2
- pytest 9.1.1
- jsonschema 4.26.0

## Extraction

The output path must not already exist. Page numbers entered by users are
1-based and can be contiguous or non-contiguous.

Raw diagnostic extraction:

```powershell
.\.venv\Scripts\python.exe .\inspect_pdf.py `
  --pdf "C:\local\book.pdf" `
  --pages "2-4,7" `
  --extractor raw `
  --out ".\output\book-raw"
```

Structured Markdown extraction:

```powershell
.\.venv\Scripts\python.exe .\inspect_pdf.py `
  --pdf "C:\local\book.pdf" `
  --pages "2-4,7" `
  --extractor structured `
  --out ".\output\book-structured"
```

PDF content is not printed by default. `--preview-chars N` is an explicit local
opt-in for debugging and may expose content in terminal logs.

Exit codes:

- `0`: completed and atomically published.
- `2`: invalid input or page selection.
- `3`: non-PDF, corrupt, or password-protected input.
- `4`: output conflict or publication failure.
- `5`: page extraction failed; no final output is published.
- `10`: unexpected failure; no final output is published.

## Deterministic evaluation harness

The expectations file uses exact checks only: required snippets, required
numbers/units, forbidden snippets, and optional order pairs. Each page declares
which checks apply. `not_applicable` checks never enter a denominator. No fuzzy
matching, general Accuracy, LLM judge, or inference about untested page content
is used.

```powershell
.\.venv\Scripts\python.exe .\evaluate_extractors.py `
  --pdf ".\tmp\samples\representative.pdf" `
  --pages "1-10" `
  --expectations ".\tests\expectations\representative.json" `
  --out ".\output\representative-evaluation"
```

The output contains `raw/`, `structured/`, `expectations.json`, `report.json`,
and `report.md`. JSON structures are documented in `schemas/` and validated by
the automated tests.

## Tests and fixture generation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

```powershell
.\.venv\Scripts\python.exe .\tests\make_sample_pdfs.py `
  --out ".\tmp\pdfs\samples" `
  --include-representative
```

The representative PDF is generated locally and intentionally remains ignored
by Git. See `tests/FIXTURES.md` for coverage and font provenance.

## Offline installation preparation

While online, download the locked Windows/Python 3.11 wheels once:

```powershell
.\scripts\prepare_offline.ps1
```

On the offline machine or after disconnecting, install without an index:

```powershell
.\scripts\install_offline.ps1
.\.venv-offline\Scripts\python.exe -m pytest -q
```

The scripts refuse to overwrite an existing wheelhouse or virtual environment.
Wheels and virtual environments are ignored by Git. Current status is
`OFFLINE_INSTALL_PREPARED`; physical network disconnection was not available in
the implementation environment, so runtime status is
`OFFLINE_RUNTIME_NOT_VERIFIED`.

## Real-document evaluation and structured benchmark

Keep real PDFs, expectations quoting them, and outputs under ignored paths such
as `documents/` and `output/`.

```powershell
.\.venv\Scripts\python.exe .\evaluate_extractors.py --pdf "C:\local\document.pdf" --pages "2-8" --expectations "C:\local\document.expectations.json" --out ".\output\real-document-evaluation"
```

The report keeps unaltered exact checks separate from canonical checks. The
canonical comparison uses Unicode NFKC and collapses repeated whitespace; it
does not remove bidi controls or visually reorder text.

Compare one-call-per-page and one batched PyMuPDF4LLM call with a warm-up, three
runs per strategy, medians, chunk mapping, exact output hashes, and Windows
working-set sampling:

```powershell
.\.venv\Scripts\python.exe .\benchmark_structured.py --pdf "C:\local\document.pdf" --pages "2-8" --out ".\output\structured-benchmark"
```

Phase 01C retained per-page structured extraction as the default. Batched calls
preserved content checks and mapping on the tested document, but changed heading
depth on some pages and did not show a stable timing advantage across repeated
benchmark sessions under the observed machine load.

## Known limitations

- `no_text` does not mean blank or scanned; image/drawing counts are only signals.
- `text_present` does not establish completeness or correctness.
- PyMuPDF4LLM 1.28.2 with layout enabled returned no text for the synthetic
  rotated page even though raw PyMuPDF extracted it.
- The real acceptance PDF had no rotated pages; real rotation behavior remains
  untested.
- Mixed Arabic/English bidirectional text can change spacing/order; the synthetic
  `123 kg` exact check fails in both extractors on that mixed line.
- Raw PyMuPDF can expose Arabic presentation-form code points; the test verifies
  UTF-8 decoding and NFKC equivalence, while structured output returns base Arabic.
- On the real paper, dense multi-column tables and mathematical notation showed
  cell interleaving, broken grouped headers, or symbol corruption. They are not
  in the supported profile. Repeated running headers/footers are retained.
- No OCR, scanned/image-only real document, encrypted PDF, real Arabic document,
  or offline network-disconnection run is claimed by Phase 01C.

Official API references:

- https://pymupdf.readthedocs.io/en/latest/recipes-text.html
- https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html
- https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/
