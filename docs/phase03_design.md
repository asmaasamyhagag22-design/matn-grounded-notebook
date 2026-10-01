# Phase 03/03B design: canonical grounded summarization

## Scope and status

Phase 03B turns a confirmed Phase 02 selection into a complete canonical English
summary and, optionally, an Arabic rendering of the same frozen semantic plan.
It does not add UI, slides, PowerPoint, agents, embeddings, RAG, vector storage,
fine-tuning, or open-ended document QA.

The maximum pre-human-review state is
`PHASE_03_IMPLEMENTED_AND_LOCALLY_EVALUATED_PENDING_HUMAN_REVIEW`.

## Data flow

```text
confirmed selection + document store + original PDF
  -> identity, source-file, and boundary validation
  -> language-independent English evidence inventory
  -> quote validation and extraction-risk classification
  -> deterministic deduplication
  -> content selection with explicit omissions
  -> frozen semantic-plan.json (SHA-256 protected)
  -> canonical English summary + review package
  -> Arabic rendering of the frozen plan only
  -> deterministic English/Arabic parity validation
  -> one bounded Arabic repair if needed
  -> atomic publication or safe failure
```

The evaluation checklist is outside this flow. Only `evaluate_summary.py` reads
it after a completed run.

## Trust and evidence

Before extraction, the CLI validates the selection/store schemas, confirmed
status, document identity, PDF hash, selected chunk text, source files, and
offsets. Unknown or outside-selection evidence is rejected. Page citations are
resolved by code from the Phase 02 store; a renderer never invents pages.

Every claim has a selected chunk ID and a short exact or NFKC+whitespace-
canonical quote. Quote occurrence is not semantic support. Review status begins
as `unreviewed`; only a reviewer may assign supported, partially supported, or
unsupported.

The default extractor is deterministic and lossless at source-statement level.
It records numbers, terms, limitations, processed chunks, chunks with/without
claims, skipped chunks/reasons, and candidates. Optional local-model enrichment
is available with `--model-map-enrichment`, but publication completeness never
depends on it. Raw picture-text claims are inventory-visible and excluded from
the semantic plan pending review. Figure/table numeric claims require
`human_review_required`, `visually_verified`, or explicit exclusion.

## Content selection

The semantic plan lists:

- available, selected, and omitted claim IDs;
- one omission reason per omitted claim;
- source-topic, numeric, terminology, and limitation coverage;
- coverage warnings;
- the complete accepted claims with evidence and risk status.

A long/comprehensive request selects every safe claim. A shorter request that
omits a core claim gets an explicit insufficient-length warning. The plan never
creates facts and never generates a “no limitations” statement from extraction
silence.

## English and Arabic

English is the canonical factual baseline. Its summary points are deterministic
renderings of the selected claims. The plan is deep-copied and SHA-256 hashed;
Arabic refuses a missing, changed, wrong-document, or wrong-selection plan.

Arabic receives only selected claim IDs/text plus frozen numbers, terms, and
limitations. It cannot select, add, or remove evidence. Each bounded render
response must return exactly the supplied IDs in order. The parity gate checks:

- selected claim-ID set equality;
- numeric-value and structured unit inventory equality;
- citation-page equality;
- configured first-use Arabic/English terminology;
- limitation claim-set equality;
- qualifier preservation;
- negation preservation.

Numeric comparison is semantic but conservative. ASCII and Arabic-Indic digits
are canonicalized, decimal values are compared numerically, and trailing-zero
format differences such as `0.480` versus `0.48` are accepted as the same
value. Units, bounds, and qualifiers are checked independently and remain
mandatory. Arabic dual forms such as `مرتان` and `مرتين` represent the value
two together with the unit “times”; arbitrary number words are not treated as
equivalent. A changed unit or loss of `maximum`, `minimum`, `average`, or
negation makes aggregate parity fail.

The renderer keeps source order within a thematic group. Before grouping, it
detects demonstrative references such as “this function”, “this method”, and
“this configuration”, keeps a selected antecedent and dependent in the same
section, and orders the antecedent first. If the antecedent is not present in
the selected plan, the renderer replaces the demonstrative with an explicit
technical noun phrase instead of emitting an orphaned reference.

Failure allows one constrained repair of affected claims, followed by the same
validation. A second failure publishes nothing. Human review separately assesses
factual faithfulness, number/qualifier preservation, terminology, natural Arabic,
first-use English display, and bidi/Markdown readability.

## Generation provenance and local-only execution

Run metadata schema version 4 derives provenance from request telemetry. A
calibration call is reported separately and never counts as map, synthesis,
render, repair, or total generation work. `cold`, `warm`, `replay`,
`deterministic`, and `mixed` classifications are derived from actual model
calls, map-cache hits, translation-memory reuse, and rejected-render reuse. A
requested cold run fails if a required model stage has zero calls or if any
cached/replayed content is used.

The CLI exposes independent controls for result-cache bypass, map-cache bypass,
translation-memory disabling, rejected-render disabling, required model stages,
required Arabic rendering, and strict cold execution. Output directories must
be new. Ollama base URLs and every recorded inference host must be loopback;
there is no cloud fallback. Offline metadata distinguishes verified
application-level local-only enforcement from unverified physical network
disconnection.

## Context and output control

All Ollama calls use `num_ctx=4096`, temperature 0, `stream=false`, and
`think=false`. The accepted English inventory uses at most two units/700 source
characters per preflight batch, a 512-token safety margin, and a recorded 1,536-
token reserve. Each record contains estimated prompt tokens, actual prompt count
(zero for deterministic extraction), eval count, done reason, requested reserve,
and unused headroom.

Any model `done_reason` other than `stop`, context overrun, invalid JSON after
one structural repair, evidence failure, plan mismatch, terminology failure, or
parity failure is terminal. Final directories are published by same-volume
atomic rename from an owned staging directory.

## Output package

Each run contains at least:

- `summary.md` and `summary.json`;
- `semantic-plan.json`;
- `claims.json` and `evidence-inventory.json`;
- `claims-review.json` / `claims-review.md`;
- `coverage-report.json` / `coverage-report.md`;
- `evidence-audit.json`, `request.json`, and `run-metadata.json`.

The Markdown review package includes point/claim IDs, claim text, PDF page,
chunk, quote, source context before/after, risk flags, semantic support status,
and reviewer note without printing source text to console logs.
