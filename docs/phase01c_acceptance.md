# Phase 01C real-document acceptance

## Decision

`PHASE_01_VERIFIED_FOR_SUPPORTED_PROFILE`

This does not claim that all PDF layouts are supported and does not start Phase
02. The decision applies only to the supported profile below.

## Local document and precommit evidence

- Description: 42-page, text-based English AI research paper with two-column
  prose, vector figures, tables, equations, references, and a code-heavy appendix.
- Visible version: `arXiv:2601.14525v1 [cs.CL] 20 Jan 2026`.
- File size: `1,252,803` bytes.
- SHA-256: `ad9f9d0d152930510045d485eebb695ab15b8f775e9bfd63313355c591a675d7`.
- Visually selected PDF pages: `1-12,14-17,23,37` (18 pages).
- The private expectations file was written before either extractor ran.
- Expectations timestamp: `2026-09-28T02:14:58.0163514+03:00`.
- Expectations SHA-256:
  `2577051bb48153a80c7bd613a6427d6bc4fcb7b2068bf31b88163ddd5aa670a9`.
- The PDF, private expectations, renders, extracted text, and reports remain under
  ignored `documents/`, `tmp/`, and `output/` paths.

The pages cover title/abstract/introduction, the executor diagram, system design,
evolutionary search, a pseudocode algorithm, simple and complex tables, reward
formulas, result plots, diversity collapse, discussion/limitations, dense
references, appendix plots, long table layouts, and late code-diff pages. Every
selected PDF page showed the same printed page number during visual review.
Manifests retain `printed_page=null`; the independently verified values live in
the private expectations rather than being inferred from PDF position.

## Extraction results

All 18 requested pages were `text_present` for both extractors. Mapping was
correct for every record, including non-contiguous pages 14, 23, and 37. No page
was reported as `no_text` or `extraction_error`.

Exact checks:

| Check | Raw PyMuPDF | Structured PyMuPDF4LLM |
|---|---:|---:|
| required exact snippets | 76 / 78 | 77 / 78 |
| required numbers and units | 47 / 49 | 46 / 49 |
| forbidden snippets | 15 / 18 | 15 / 18 |
| expected order pairs | 44 / 48 | 43 / 48 |

Canonical checks use NFKC plus repeated-whitespace collapse only. Bidi controls
are retained and no visual reordering is performed.

| Check | Raw PyMuPDF | Structured PyMuPDF4LLM |
|---|---:|---:|
| required exact snippets | 78 / 78 | 77 / 78 |
| required numbers and units | 49 / 49 | 46 / 49 |
| forbidden snippets | 15 / 18 | 15 / 18 |
| expected order pairs | 45 / 48 | 43 / 48 |

These are deterministic anchor counts, not an Accuracy score. Three forbidden
checks were unsuitable because the tested page itself legitimately referred to
the next figure or table; they remain in the committed-before-extraction result
instead of being edited after inspection. Other exact failures were caused by
line wrapping or Markdown/math markup and were manually classified below.

The first report publication failed safely because the validator treated the
word “accuracy” inside source-derived expectations as a forbidden general metric.
No final directory was published. The validator now rejects an `accuracy` key,
not source text containing that word, and has a regression test.

## Manual visual classification

| Class | Finding |
|---|---|
| content missing | No required prose anchor or selected number was judged silently missing after visual review and canonical checks. This does not prove full-page completeness. |
| content corrupted | Raw text retains line-end hyphenation. Structured text sometimes joins or drops hyphens in compound terms. |
| reading-order error | Raw extraction placed the System Design actors out of the verified Implementer → Scheduler → Worker order. Structured corrected that case. Some figure-band ordering is visually ambiguous and remains reviewable. |
| table-structure error | Raw flattens tables. Structured reconstructed the simple comparison table, but split grouped headers in a wide table and interleaved cells/code in long two-column appendix tables. |
| equation loss | Reciprocal-loss and algorithm/table formulas were fragmented; replacement glyphs appeared in complex notation. Equations are excluded from the supported profile. |
| caption-placement error | Captions were present. Structured figure text entered the Markdown in bounded picture-text blocks; this can interrupt reading flow and needs downstream handling. |
| repeated header/footer | Both paths retained the repeated paper title and printed page number as content. |
| harmless formatting difference | Exact failures from line wraps, emphasis markup, math delimiters, and batched heading-depth changes did not represent missing anchors. |

## Per-page versus batched PyMuPDF4LLM

The installed 1.28.2 API was verified locally: `pages` is a zero-based list,
`page_chunks=True` returns one chunk per selected page, and
`metadata.page_number` is one-based. OCR remained disabled.

One full warm-up was not used; the benchmark performed a clear one-page layout
warm-up, excluded it, then interleaved three runs per strategy. A corrected
Windows working-set run produced:

| Strategy | elapsed runs (s) | median (s) | peak working-set increase runs (bytes) | median (bytes) | `parse_document` calls/run |
|---|---|---:|---|---:|---:|
| per-page | 127.665, 34.186, 29.651 | 34.186 | 261951488, 133357568, 133316608 | 133357568 | 18 |
| batched | 73.491, 52.722, 36.046 | 52.722 | 151670784, 139259904, 140673024 | 140673024 | 1 |

Memory was sampled from `GetProcessMemoryInfo.WorkingSetSize` every 5 ms in the
same process. The measured value is peak increase over the pre-call baseline.
Elapsed time used `time.perf_counter_ns`.

An earlier timing-only run under different concurrent load produced the opposite
median direction: per-page `128.026 s`, batched `109.365 s`. Other active Python
workloads were observed on the machine. Therefore, a stable performance win was
not established and the result must not be generalized beyond this machine and
document.

All six measured outputs were deterministic and all chunk mappings were valid.
Per-page and batched content checks were identical. Seven pages differed byte for
byte only because batched context changed Markdown heading depth. Per-page remains
the default because correctness is acceptable but the timing advantage was not
stable and the output was not byte-identical.

## Rotation, fallback, and canonical decision

- All 18 selected real pages had rotation metadata `0`; real rotation fallback
  was not exercised.
- The synthetic rotated page still yields structured `no_text` while raw succeeds.
- No fallback was added. The real structured pages were non-empty, and the
  serious table/equation problems cannot be detected safely by text length. A
  length-only fallback would hide corruption rather than diagnose it.
- No document-specific rule was added.
- Canonical comparison was added for the existing Arabic fixture and for
  whitespace-only comparison. It never replaces or hides exact results.

## Supported profile

Verified on this machine for:

- local, unencrypted, text-based PDFs;
- English academic prose;
- unrotated pages;
- single- and two-column prose, headings, citations/references, figure captions,
  and a simple comparison table;
- explicit 1-based PDF-page mapping to separate per-page files and manifests;
- raw diagnostic text and per-page structured Markdown with OCR disabled.

Not supported or not verified by this gate:

- OCR, scanned/image-only documents, or extracting information embedded only in
  figures;
- dense/wide/multi-row tables, code-heavy table cells, or faithful equation
  reconstruction;
- rotated real-document pages;
- real Arabic, mixed Arabic/English bidi, or other real languages;
- removing repeated headers/footers;
- physical network-disconnection runtime verification.

The remaining limitations are explicit and outside this supported profile, so
Phase 01 is verified only for the profile above—not complete for arbitrary PDFs.
