# Phase 01 audit

## Status

`PHASE_01_VERIFIED_FOR_SUPPORTED_PROFILE`

Phase 01C added a precommitted, visually reviewed real-document acceptance run.
The narrow supported profile and explicit exclusions are in
`docs/phase01c_acceptance.md`; this is not a claim of arbitrary-PDF support.

## Findings and resolutions

| Category | Before | Resolution / current evidence |
|---|---|---|
| correctness | 1-based inclusive ranges were converted centrally and correctly. Only contiguous ranges were accepted. | Central `PageSelection` now supports contiguous and non-contiguous pages, rejects duplicates, and is covered by mapping tests. |
| data integrity | Page files were written directly to the final directory. A middle-page failure could leave partial files and a manifest could be written with failed pages. | Each run writes to an owned hidden staging directory. Any page failure removes verified-owned staging and publishes no final directory. Publication is a same-parent rename after schema checks and manifest completion. |
| data integrity | An existing empty output directory was accepted, which conflicts with atomic directory publication. | Every existing output path is rejected. No output is silently replaced. |
| security-privacy | The first 300 extracted characters were printed by default and the manifest stored the full source path. Raw exception messages could include paths or content. | Content preview defaults to zero and requires explicit opt-in. Manifest records only `file_name`. User-facing failures expose exception types, not traceback, source content, or internal exception text. |
| reproducibility | Manifest lacked source size, run ID, explicit extractor block, layout version, page labels, drawings, and a complete timing contract. | Manifest schema v2 records all required provenance, extractor settings/versions, page metadata/signals, UTC timestamps, timing unit/clock/scope, and independent page records. |
| reproducibility | Only direct requirements were pinned. | Direct requirements plus a full tested lock are present. Wheelhouse preparation and `--no-index --find-links` installation scripts were executed successfully. |
| testing | No Arabic, columns, table, rotated page, mixed image/text, non-contiguous mapping, schema, determinism, or injected middle-page failure tests. | The suite now covers these risks, validates both JSON schemas, and checks that failure publishes nothing. |
| documentation | Only raw extraction and basic setup were described. | README documents both extractors, evaluation semantics, exit codes, offline workflow/status, real-document command, and known observed failures. |

## Observed synthetic evaluation

Exact matching only; `not_applicable` is excluded from denominators.

| Metric | Raw | Structured |
|---|---:|---:|
| required exact snippets | 13 / 16 | 15 / 16 |
| required numbers and units | 8 / 9 | 8 / 9 |
| forbidden snippets | 13 / 13 | 13 / 13 |
| expected order pairs | 4 / 5 | 5 / 5 |

These are check counts, not general Accuracy. Passing snippets do not validate
the rest of a page.

## Phase 01C and constrained checks

- Real-document evaluation: `RUN` on 18 visually preselected pages from a local
  42-page research paper; outputs and expectations remain ignored.
- Per-page versus batched strategy: `RUN`; per-page remains default because
  performance direction was not stable and Markdown heading depth differed.
- Physical network-disconnection test: `NOT_RUN`.
- Offline status: `OFFLINE_INSTALL_PREPARED` and
  `OFFLINE_RUNTIME_NOT_VERIFIED`.
- The wheelhouse was downloaded, installed into a new `.venv-offline` using
  `--no-index`, and the full suite passed there. This does not prove runtime
  behavior with the network adapter physically disconnected.
