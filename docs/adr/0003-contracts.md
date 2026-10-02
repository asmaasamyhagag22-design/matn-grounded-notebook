# ADR-0003: Standalone, versioned provenance contracts

- **Status:** Accepted, 2026-10-02.
- **Scope:** `matn_contracts/` and `schemas/contracts/`; no existing pipeline wiring.

## Context

The current pipeline uses several dictionaries and sequential claim identifiers. Page references survive in some
paths, but PDF position, extractor identity, and visibility do not consistently cross stage boundaries. Model output
can also carry unverified numbers. Step 1 needs a stable contract boundary before those stages are migrated.

## Decision

### Coordinates

All `bbox` values are `(x0, y0, x1, y1)` in PDF points, with a top-left origin after page rotation is normalized.
They must satisfy `x0 < x1` and `y0 < y1`. Identity material quantizes each coordinate to 0.1 point with decimal
`ROUND_HALF_UP`; negative zero is serialized as `0.0`. Raw coordinates remain floats in the models. This convention
matches later reading-order and highlighting work without depending on a renderer's pixel resolution.

### Deterministic IDs

- `doc_id` remains `sha256-<64 lowercase hex>` for registry compatibility.
- `block_id` is `{doc_id}:p{page_index:04d}:<16 hex>`. Its digest covers a canonical JSON list containing `doc_id`,
  zero-based `page_index`, quantized bbox strings, and the raw extracted text.
- `table_id` uses the same readable prefix and hashes `doc_id`, page, and quantized bbox.
- `section_id` hashes `doc_id`, the ordered heading path, and the first ordered block ID.
- `fact_id` hashes the first evidence block ID and an NFKC-normalized, whitespace-collapsed, case-folded statement.
- Canonical material uses `json.dumps(..., separators=(",", ":"), ensure_ascii=False)` and SHA-256; public short
  hashes are the first 16 lowercase hexadecimal characters.

Raw block text is never normalized for identity. The 16-character suffix balances compact references with
determinism; the full document digest and readable page prefix remain present on block/table IDs. Sequential IDs
were rejected because insertion or reordering changes every later reference. Random UUIDs were rejected because
equal inputs would not reproduce equal artifacts.

LLM-facing evidence uses section-local `block_ref` values (`b1`, `b2`, …), never full block IDs. Code supplies the
mapping, rejects an unknown reference, and writes the real block ID. This avoids repeatedly spending prompt tokens
on long IDs and reduces copy errors by a 9B model.

### Domain and draft split

Domain models hold complete provenance and code-owned state. Draft models expose only fields the model may choose.
In particular, a model cannot write `fact_id`, `status`, `reject_reasons`, evidence offsets, `doc_id`, or full
`block_id`. Conversion raises errors rather than swallowing them, assigns deterministic IDs, and sets facts to
`raw`. Pydantic's exported draft schemas are the schemas intended for Ollama's `format` parameter.

For number facts, the model chooses `label`, `value_as_written`, and nullable `unit` as strings. Conversion accepts
`value_as_written` only when it exactly equals a numeric token in an evidence quote, requires a non-null unit to
appear in that same quote, and derives `page_label` from the mapped block. KPI and chart plans contain references,
not copied numeric data. Chart columns are zero-based indices because the table contract already has stable ordered
columns; names can be duplicated or absent.

### Importance, status, and vocabularies

`Importance` is exactly `{1, 2, 3}` and follows the gold schema: `3` means headline/must appear, `2` important, and
`1` supporting. Reversing this direction was rejected because it would silently invert the evaluation contract.

Fact kinds are exactly the gold vocabulary `purpose`, `finding`, `target`, `recommendation`, `caveat`, and
`definition`, plus the domain-only `number`. Fact status is `raw`, `verified`, or `rejected`. Reject reasons are the
closed set in `RejectReason`, including `evidence_hidden`, `evidence_in_figure`, and `spelled_number_mismatch`.
Block, visibility, extraction-route, sentence, slide, and chart vocabularies are closed enums. Open strings were
rejected because spelling drift would become pipeline branching logic.

### Versioning and schemas

Every public domain and draft model is frozen, forbids extra fields, and carries `schema_version=1`. Nested models
also carry the version so a serialized value can be validated independently. Every public model has a committed
JSON Schema under `schemas/contracts/`; a registry test and exact snapshot test make additions and changes visible.
Hand-written schemas were rejected because they can drift from runtime validation.

Collections in domain models are tuples to preserve immutability and stable ordering. Cross-object rules that need
the fact collection, notably “KPI references only number facts,” live in `validate_deck_plan_against_facts` rather
than pretending one `Slide` can validate external objects.

## Consequences

- Later stages must adapt their 1-based pages, missing bbox/table data, keyword-built sections, and the live path
  that bypasses the store; Step 1 intentionally does not migrate them.
- A schema change is a reviewed file diff and must consider a `schema_version` increment.
- Full provenance costs more serialized space, while short draft refs keep that cost out of repeated prompts.
- The contracts reject invalid intermediate data early; callers must handle validation errors explicitly.
