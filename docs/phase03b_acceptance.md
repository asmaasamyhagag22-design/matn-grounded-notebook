# Phase 03B acceptance report

Date: 2026-09-29  
Status: `PHASE_03_IMPLEMENTED_AND_LOCALLY_EVALUATED_PENDING_HUMAN_REVIEW`

This is Phase 03B only. No Phase 04, slide, UI, RAG, embedding, vector
database, agent, fine-tuning, staging, or commit work was performed.

## Implemented design

The accepted path is:

1. Reconcile source statements before map batches, including adjacent chunks,
   extraction-order columns, and page boundaries.
2. Reject unresolved leading or trailing fragments instead of publishing them.
3. Build a language-independent English evidence inventory with ordered,
   multi-span provenance and exact source text.
4. Freeze one canonical semantic plan and render a coherent English summary.
5. Render Arabic from that exact frozen plan; Arabic never selects evidence.
6. Apply deterministic parity plus reusable high-risk semantic relation rules.
7. Permit at most one constrained Arabic repair; otherwise fail atomically and
   write a rejected human-review artifact.
8. Keep every human semantic status `unreviewed` until a person records a
   decision.

The user-facing summary groups atomic claims into thematic paragraphs. The
detailed, per-claim inventory remains in `claims-review.md` and preserves all
contributing spans, chunk IDs, page sets, source order, risk flags, and
normalization notes in machine-readable form.

The unchanged evaluation checklist is read only by `evaluate_summary.py`; no
production prompt or summarization module imports it.

## Baseline versus remediated result

| Measure | Baseline full Section 2 | Remediated full Section 2 |
|---|---:|---:|
| Validated inventory claims | 45 | 39 |
| Selected atomic propositions | 37 | 35 |
| Incomplete selected fragments | 4 | 0 |
| Reconciled multi-span propositions | 0 | 2 |
| Coherent user-facing summary units | 37 | 9 |
| Idea coverage | 6/6 | 6/6 |
| Required numeric coverage | 5/5 | 5/5 |
| Required terminology coverage | 3/3 | 3/3 |
| Required limitations coverage | 4/4 | 4/4 |
| Citation ID / exact quote / canonical quote / boundary validity | 45/45 | 41/41 evidence spans |
| Generated numeric correctness | N/A | N/A |
| Generated terminology correctness | N/A | N/A |
| Citation semantic support | N/A | N/A |
| Unsupported claim rate | N/A | N/A |

The four baseline fragments were two proposition pairs. General sentence-aware
reconciliation now produces two complete claims, including one claim spanning
PDF pages 2 and 3. The accepted inventory reports zero unresolved fragments.

The canonical claim text preserves `1 / loss`, `Qwen2.5-Math-1.5B`, and
`self-execution`. Where extraction text is malformed, the exact extracted text
is retained separately and the normalization is review-visible; uncertain math
is never silently treated as human verified.

## Historical experiment artifacts

Timings below are `wall_clock_ns` from each run's metadata, not shell timing.

| Experiment | Output directory | Result | Time |
|---|---|---|---:|
| Section 2.2 English | `output/phase03b-exp-g2-sec2-2-en` | 20 claims, 19 selected, 6 summary units, 7/7 cache hits | 5.931 s |
| Section 2.2 Arabic | `output/phase03b-exp-h6-sec2-2-ar` | Frozen English plan; 19 exact translations reused and fully revalidated; parity pass | 2.814 s |
| Full Section 2 English | `output/phase03b-exp-i3-sec2-full-en` | 39 claims, 35 selected, 9 summary units, 17/17 cache hits | 3.978 s |
| Full Section 2 Arabic | `output/phase03b-exp-j6-sec2-full-ar` | Same 35 selected claims; deterministic and semantic-risk gates pass | 6.125 s |
| Bypass-cache repeat 1 | `output/phase03b-exp-k1-repeat-en` | 17 misses, deterministic output | 5.116 s |
| Bypass-cache repeat 2 | `output/phase03b-exp-k2-repeat-en` | 17 misses, deterministic output | 8.085 s |

Bypass-cache hashes are identical:

- `summary.json`: `CB635469CA916B95B4DD8A4AFB1614F5321062585448E4B4D064B7409E43F659`
- `semantic-plan.json`: `B39FBDAFEDB6EBE4D088EC19839CAE7E035F7E39C0A56CD74F5015523037BAEE`
- `summary.md`: `9C792ADF8DD6741CE32863D62B31156F6AB1D990C27AA220FBB9309C59DB5CBB`

Earlier truncating or semantically rejected attempts remain diagnostic only;
atomic publication prevented them from replacing accepted output.

## Final remediation artifacts (2026-09-30)

The provenance defect in the historical runs was corrected before these runs.
Timings are `actual_generation_duration_ns`; calibration is counted separately
and never as map or render work.

| Experiment | Output directory | Provenance evidence | Generation time |
|---|---|---|---:|
| Cold English | `output/phase03b-remediation-cold-en-20260929-a9` | `model_generation`; 16 map calls; 17 misses, 0 hits; one visually verified batch assembled deterministically | 5,283.459 s |
| Cold Arabic 1 | `output/phase03b-remediation-cold-ar-20260929-a4` | `model_generation`; 9 render calls; no TM or rejected render | 1,425.055 s |
| Cold Arabic 2 | `output/phase03b-remediation-cold-ar-20260929-a5` | `model_generation`; 9 render calls; no TM or rejected render | 991.443 s |
| Warm English | `output/phase03b-remediation-warm-en-20260930-b1` | `cache_replay`; 17 hits, 0 misses; 0 model calls | 0 model-generation time |
| Arabic replay control | `output/phase03b-remediation-replay-ar-20260930-r1` | `translation_memory_replay`; provenance `replay`; 0 model calls | 0 model-generation time |

Both independent Arabic cold summaries pass every mandatory parity subcheck.
Their `summary.json` files are byte-identical with SHA-256
`035A59E49ED775B5A49E4B128FA84BF8F8594E46441CC35802D601E5C234C9D2`.
Selected claim IDs, numbers, terminology, semantic relations, citations, and
wording are also identical.

## English coverage and evidence checks

The unchanged checklist plus the explicitly non-independent presence review
reports ideas 6/6, required numbers 5/5, required terminology 3/3, and required
limitations 4/4. Citation IDs, exact quotes, canonical quotes, and boundary
purity are 41/41 evidence spans. This does not establish factual support.

The Figure 2 caption values `0.480` and `3.255` were visually compared with PDF
page 3 and retained. Values present only inside high-risk figure/table content
remain omitted. English and Arabic coverage notices state this distinction and
the Arabic summary contains no English coverage paragraph.

## Arabic gates

The full Arabic artifact passes these automated checks:

- selected claim-ID set, numeric values, units, and citations;
- required terminology, limitation, qualifier, and negation preservation;
- subject/action/object/condition semantic-relation rules;
- high-risk distinctions for codebase/database, scheduling interval/clock
  frequency, applying a diff/repairing it, ideator role, parallel diff
  generation, GPU-equipped cluster, maximum/average, and Accuracy/Precision.

The confirmed bad Arabic strings are absent from the final Section 2 and
Section 2.2 summaries. This is an automated risk gate, not proof of translation
quality. Naturalness, factual fidelity, terminology quality, first-use English,
and bidirectional Markdown remain `unreviewed`.

## Schema and cache migration

- Grounded claims schema version 3 adds ordered multi-span evidence, exact
  source text, offsets/pages, and normalization notes while retaining prior
  required fields.
- Summary schema version 3 supports grouped points with multiple claim IDs and
  provenance records.
- Review package version 3 is bilingual, card-based, and evidence-complete.
- Semantic-plan version 2 freezes the grouped structure and exact claim set.
- Map prompt/cache identity moved to `map-v11-complete-claims-quarantine-invalid-enrichment` and
  cache payload schema 3, so only affected entries miss.
- Arabic render/gate/normalization versions are recorded in run metadata.
- Rejected-render and translation-memory reuse are explicit CLI inputs tied to
  the frozen plan and model/glossary/prompt identity, followed by full parity
  revalidation.

## Tests and remaining review work

- `python -m pytest -q tests/test_phase03.py tests/test_phase03b.py`:
  **77 passed**.
- `python -m pytest -q`: **102 passed**.
- `python -m pytest -vv --tb=long`: **102 passed**; the complete output is
  preserved in `pymupdf_recovery_validation.txt`.

Windows Application Control previously blocked PyMuPDF's `_features` DLL and
produced four reproducible failures with correlated Code Integrity Events 3077
and 3089. That historical evidence remains in the diagnosis artifacts. The
same project environment now imports PyMuPDF successfully, no recent block
events were present, and two fresh full-suite runs passed 102 tests. No
security policy was changed by this remediation. See
`docs/phase03b_pymupdf_diagnosis.md`.

Acceptance remains pending because:

1. required independent human semantic and naturalness review has not occurred;
2. browser-level visual bidi inspection could not be completed in the current
   automation surface because local `file:` navigation was blocked. The
   generated Markdown structurally contains explicit RTL/LTR blocks, but that
   is not claimed as visual verification.

No claim is marked `supported`, and the maximum project state remains
`PHASE_03_IMPLEMENTED_AND_LOCALLY_EVALUATED_PENDING_HUMAN_REVIEW`.
