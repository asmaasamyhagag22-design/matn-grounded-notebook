# Phase 04A acceptance record

Date: 2026-09-30

Status: `PHASE_04A_MVP_IMPLEMENTED_AND_VISUALLY_VERIFIED`

Phase 03B remains
`PHASE_03_IMPLEMENTED_AND_LOCALLY_EVALUATED_PENDING_HUMAN_REVIEW`.
Starting Phase 04A does not imply human approval of Phase 03B or Arabic output.

## Accepted scope

- Fixed demonstration source: `documents/2601.14525v1.pdf`.
- Source scope: Section 2, physical 1-based PDF pages 2–3.
- English-only Streamlit interface with validated cached and live local modes.
- Versioned claim-to-bullet `deck-plan.json`, fail-closed validation, and a
  deterministic 16:9 PowerPoint renderer.
- Ten-slide academic deck, direct Figure 2 crop, visible page/claim citations,
  downloadable PowerPoint, and downloadable plan.

## Evidence corrections

- `src-src-036` is always blocked because it is raw picture-region
  transcription. It is recorded as omitted and appears in no deck bullet.
- `src-src-010` is used on the pre-training slide after visual verification of
  the printed reciprocal reward `1/loss` on physical PDF page 2.
- Figure 2 is a direct page-3 crop containing its axes, legends, subplot labels,
  and caption. No OCR or reconstructed picture text is used. The presented
  caption facts come only from `src-src-037`, `src-src-038`, and `src-src-039`.

## Validation evidence

- Deck schema and provenance validator: pass.
- Every factual bullet has accepted claim IDs and code-derived PDF pages.
- All 39 source claims are used or have a deterministic omission reason.
- Validated Demo Mode records zero model-generation calls and disables cloud
  fallback.
- PowerPoint reopened successfully through `python-pptx`.
- Geometry validation reports zero out-of-bounds shapes and zero visible-object
  overlaps.
- Microsoft PowerPoint exported all ten slides to PNG. Every slide was inspected
  at full size for clipping, overlap, citation readability, ordering, spacing,
  and Figure 2 fidelity.
- Streamlit was inspected at a 1440x900 desktop viewport in Validated Demo Mode,
  the Slides preview, Run details, and Live Local Generation warning state.
- Focused Phase 04A plus Phase 03B regression run: 55 passed.
- Full repository regression suite: 109 passed in 44.54 seconds.

## Deliverables

- `app.py`
- `matn_presentation/`
- `schemas/deck-plan.schema.json`
- `tests/test_deck_plan.py`
- `tests/test_presentation_renderer.py`
- `tests/test_demo_mode.py`
- `tests/test_live_presentation.py`
- `output/phase04a-english-demo/deck-plan.json`
- `output/phase04a-english-demo/matn-phase04a-english-demo.pptx`
- `output/phase04a-english-demo/assets/figure-2-page-3.png`
- `output/phase04a-english-demo/slide-previews/`

## Known limitations

- Live CPU inference was covered with a deterministic fake local client in
  automated tests to avoid a long cold model run during implementation. The
  production path uses the existing loopback-only Ollama client.
- Live upload supports text-based PDFs only and does not OCR images.
- Automated validation and this visual QA do not constitute independent human
  semantic approval of the underlying Phase 03B claims.
