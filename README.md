# Matn Phase 01 - local PDF extraction baseline

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
cd C:\Users\asmaa\Documents\notebooklm\matn
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
