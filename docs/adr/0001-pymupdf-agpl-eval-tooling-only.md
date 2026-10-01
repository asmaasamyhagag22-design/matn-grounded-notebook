# ADR-0001: PyMuPDF is allowed in eval tooling only, pending legal review

- **Status:** Accepted as an interim rule, 2026-10-01. Open until legal review decides; then superseded by ADR-000N.
- **Raised by:** senior reviewer (Step 0 amendment 2).
- **Enforced by:** `checks/test_agpl_boundary.py` (runs in pre-commit G2 and pre-push G4).

## Context

Matn is delivered to a government client. Its PDF stack is PyMuPDF. The installed METADATA (`.venv`, read
2026-10-01) gives the same license for all three distributions:

| Distribution | Version | License (METADATA) |
|---|---|---|
| `pymupdf` (import `pymupdf`, legacy alias `fitz`) | 1.28.2 | Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License |
| `pymupdf4llm` | 1.28.2 | Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License |
| `pymupdf-layout` | 1.28.2 | same, plus classifier `License :: Other/Proprietary License` |

AGPL-3.0 obligations can reach the source code of the program that links the library, including when users interact
with it over a network (section 13). Matn is a local Streamlit app today, and the client's distribution and hosting
model has not been reviewed. Whether AGPL is acceptable, or a commercial license is needed, is a legal question. This
ADR does not answer it.

## Decision

1. **Allowed:** PyMuPDF (`fitz`, `pymupdf`, any `pymupdf*` package) may be imported in **eval tooling only**: files
   under `eval/`. Eval tooling builds and checks the evaluation reference. It does not ship to the client.
2. **Not allowed:** no other code may add an import of these packages until legal review decides. "Other code"
   includes pipeline modules, the app, root scripts and tests.
3. **Existing importers are frozen, not approved.** When this ADR was written, 8 files outside `eval/` already
   imported PyMuPDF. The pipeline was built on it before the license question came up. These imports are a **known
   violation pending legal review**. They are recorded in `FROZEN` in `checks/agpl_boundary.py` and listed below.
   Removing them means rewriting the pipeline's PDF layer, which is outside Step 0's approved scope. The list may
   only shrink.

| Frozen importer | Kind | Uses |
|---|---|---|
| `document_store.py` | pipeline | `pymupdf.open` for page text |
| `inspect_pdf.py` | pipeline | `pymupdf` + `pymupdf4llm.to_markdown` |
| `matn_presentation/assets.py` | pipeline | `fitz.open` / `Matrix` / `Rect` for page images |
| `matn_presentation/live.py` | pipeline | `fitz.open` |
| `benchmark_structured.py` | root benchmark script | `pymupdf` + `pymupdf4llm` |
| `tests/make_sample_pdfs.py` | test fixtures | builds the sample PDFs |
| `tests/test_document_store.py` | test | tests pipeline code |
| `tests/test_inspect_pdf.py` | test | tests pipeline code |

## Enforcement

`checks/test_agpl_boundary.py` parses every tracked or untracked-but-not-ignored `.py` file with `ast` and fails if:
- a file outside `eval/` that is not frozen imports PyMuPDF. All import forms count: `import`, `from … import`,
  imports inside functions or `try`, `importlib.import_module("…")` and `__import__("…")` with a literal name;
- a frozen file no longer imports it. Remove it from `FROZEN` and from the table above;
- a frozen file is missing from this ADR.

Blind spots: a module name built at runtime (`import_module(name)`), and code outside the repository.

## Consequences

- Eval tooling keeps PyMuPDF, so gold quotes are verified against PyMuPDF text. To make sure the gold does not depend
  on one extractor's quirks, `eval/gold/MANIFEST.json` records the extractor and its version, and
  `eval/cross_check.py` re-verifies quotes with a second extractor (Step 0 amendment 3).
- That second extractor is `pdftotext` 4.06 from Xpdf (Glyph & Cog). It was already on the machine, bundled with Git
  for Windows at `/mingw64/bin`; nothing was installed. Xpdf is distributed under the GPL. No license file was found
  on this machine, so this needs the same legal check. It runs only as a subprocess from eval tooling.
- The questions for legal review: (a) can the client deliverable use PyMuPDF under AGPL-3.0? (b) if not, buy the
  Artifex commercial license or replace the PDF layer? (c) does eval-only use of PyMuPDF and pdftotext need anything?
- If the answer to (a) is "no", the frozen pipeline modules need a replacement library before delivery.
