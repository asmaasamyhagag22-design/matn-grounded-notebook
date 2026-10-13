# ADR 0006 — Docling isolated layout sidecar

Status: provisional production integration, subject to the owner's binding blind audit.
Date: 2026-10-13.

## Decision

Run Docling 2.138.0 in a separate isolated environment as a subprocess. Pin the complete
accepted isolated freeze and Heron revision `8f39ad3c0b4c58e9c2d2c84a38465abf757272d8`.
Use the pipeline flags and layout defaults committed in `0eb5651`: OCR, table structure,
picture classification and all enrichment disabled. Set HF/Transformers offline and
provide an explicit artifacts path. Refuse missing artifacts rather than download them.

The subprocess writes a per-source JSON sidecar bound to source SHA256, configuration
SHA256, model revision and page dimensions. The main environment validates this identity
before using labels. Incomplete or mismatched sidecars fail closed with an error. Missing
sidecars mean not covered; they do not establish that a block is prose or a table.

The main environment consumes JSON only. Its requirements, locks and wheelhouse remain
free of Docling and Torch. Table-role blocks become non-citable figure-role elements only
when picture union share >= 0.5 and table union share < 0.5, using the accepted mapping.
Block IDs, text, bboxes and character offsets stay unchanged. Existing structured cells
cannot override the figure exclusion. real6 has no sidecars and remains not covered.

M2 may use known object regions for the separately pre-registered narrative-body rule.
The sidecar consumer is optional and removal of its stage reverses Docling retyping. Keep
its implementation in one dedicated fix commit so a single new reversing commit can
remove it if the owner's audit fails. Historical r-lite-2 structures remain readable.

## Delivery

Package the isolated runtime and pinned weights separately for offline delivery. Verify
licenses, byte hashes, CPU cost and two-process determinism on the delivery machine.
