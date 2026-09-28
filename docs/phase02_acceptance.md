# Phase 02 real-document acceptance

## Decision

`PHASE_02_VERIFIED_FOR_SUPPORTED_PROFILE`

This gate covers deterministic document structure and source-scoped selection;
it does not start summarization, Ollama, RAG, vector storage, agents, OCR, or
PowerPoint.

## Source and review method

- Local document: *Towards Execution-Grounded Automated AI Research*,
  arXiv:2601.14525v1, 42 pages.
- SHA-256: `ad9f9d0d152930510045d485eebb695ab15b8f775e9bfd63313355c591a675d7`.
- PDF outline/bookmarks: absent (`[]`).
- Full raw and structured Phase 01 runs covered PDF pages 1–42.
- Ground truth was written after direct visual review of representative PDF
  renders and before running the Phase 02 evaluator.
- Real PDF, renders, corrections, ground truth, stores, selections, and reports
  remain ignored and are not committed.

Visual review covered Abstract; Sections 1, 2, 2.1, 2.2, 3, and 5;
References; Appendix A; and Appendix A.1. It confirmed multiple mid-page starts
and ends, including Sections 2, 2.1, 2.2, 3, 5, References, and Appendix A.1.

## Observed index

The reviewed store contains 42 page records, 454 page-bounded chunks, 51
heading candidates, and 26 confirmed sections. Twenty-five Markdown headings
inside appendix tables/code examples were manually rejected as non-structural.
All 26 retained sections are confirmed; none of the conflicting or ambiguous
candidates passed silently.

The repeated paper title was proposed by the generic repeated-edge detector on
all 42 pages and then manually confirmed. It remains intact in canonical raw and
structured evidence and is only excluded, with a recorded reason, from
selection text. Varying printed page numbers were not guessed as a repeated
footer. `printed_page` was populated only for visually reviewed pages and is
`null` elsewhere.

## Deterministic metrics

No fuzzy matching, general Accuracy, or LLM judge was used. N/A checks do not
enter a denominator.

| Metric | Result |
|---|---:|
| heading_detection | 10 / 10 |
| heading_level | 10 / 10 |
| parent_relation | 10 / 10 |
| start_boundary | 10 / 10 |
| end_boundary | 10 / 10 |
| chunk_inclusion | 17 / 17 |
| chunk_exclusion | 9 / 9 |
| page_reference_validity | 389 / 389 |

These are check counts over the declared reviewed cases, not a claim about
arbitrary PDF accuracy.

## Selection checks

- `sec-2`: 19 chunks, PDF pages 2–3, includes subsections 2.1 and 2.2, confirmed.
- `sec-2-2`: 7 chunks, PDF page 3 only, confirmed; it excludes the beginning of
  Section 3 on the same page.
- explicit pages `2-3,8`: 40 chunks with citations only to pages 2, 3, and 8;
  the result is labeled `page-scoped`.
- unknown section IDs and malformed/reversed page selectors fail without
  producing a selection.
- proposed/conflicting sections are refused unless the caller passes
  `--allow-unconfirmed`; that choice is recorded as
  `explicitly_allowed_unconfirmed`.

## Supported profile after Phase 02

Verified for:

- the Phase 01 supported profile: local, unencrypted, text-based English PDFs;
  non-rotated single/two-column prose, headings, captions, citations/references,
  simple comparison tables, independent PDF-page mapping, and OCR disabled;
- complete paired raw and structured extraction runs for the same source/pages;
- Markdown headings with conventional numeric or appendix numbering;
- named Abstract, References, Acknowledgment, and Appendix structures;
- human-reviewed corrections for heading false positives and confirmed
  repetitive edge lines;
- page-contained deterministic chunks, mid-page end-exclusive boundaries,
  hierarchy, explicit section IDs, non-contiguous page selection, citations,
  and risk aggregation.

Not supported or not verified:

- arbitrary unknown-document semantic correctness without review;
- OCR/scanned pages, real rotated pages, or real Arabic documents;
- complex-table or equation reconstruction;
- automatic semantic disambiguation of “first two sections”;
- reliable automatic confirmation/removal of headers and footers;
- automatic raw/structured fallback;
- summarization or any LLM-backed downstream phase.

