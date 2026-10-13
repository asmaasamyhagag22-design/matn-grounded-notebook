# ADR 0007 — isolated reranker scoring sidecar

Status: eval-only; no production integration or selection decision.
Date: 2026-10-13.

## Decision

Run `eval/reranker_runner.py` as a standalone subprocess in an isolated virtual
environment. Reject imports and the main interpreter. Pin CPU Torch 2.14.1+cpu,
Transformers 5.19.0 and Qwen/Qwen3-Reranker-0.6B revision
`e61197ed45024b0ed8a2d74b80b4d909f1255473` in `eval/reranker_settings.json`.
The original environment is `/home/asmaa/.venvs/matn-rerank`; a fresh offline
installed environment with the same pins may run the delivery proof.

Validate the caller's input SHA256 and every pinned local model file before
scoring. Bind output JSON to input/configuration SHA256, model revision and actual
yes/no token IDs. Set HF/Transformers offline, local-files-only and the existing
process egress guard. Missing/mismatched artifacts fail closed without download.
The main environment consumes no Torch/Transformers imports or dependencies.

Use the pinned model card's Transformers scoring recipe: official instruction,
prefix/suffix, left padding, maximum 8192 tokens, final-token no/yes logits and
exponentiated two-class log-softmax. CPU only, four threads, microbatches of ten;
no generation. Retain one score per input passage in original order. Timing/RSS
are separate from deterministic JSON. These settings precede synthetic inference.

Verify only fictional synthetic questions/passages in two separate processes.
Sanity ranking, byte determinism and CPU costs are build checks; no frozen
questions, survey topics, WEF drafts or retrieval metrics enter this stage.
Candidate R selection remains governed by `docs/reranker-selection-rule.md`, after
the WEF freeze and base configuration decision. Production stays C0 without a
reranker. This sidecar is reversible by a new commit removing its optional runner
and settings; existing structures/indexes are unaffected.

## Licenses and delivery

Installed Torch license expression is Apache-2.0 / LLVM exception, BSD-2/3,
BSL-1.0 and MIT; Transformers installed LICENSE is Apache-2.0. The pinned model
README frontmatter declares Apache-2.0. Installed artifact texts/hashes and the
complete isolated freeze are recorded under `out/batch2/continuation/reranker/`.
These permissive declarations do not replace the delivery license review.

Package wheels and copied pinned model artifacts outside the repository under
`/home/asmaa/matn-delivery/`. Prove fresh offline installation and a synthetic
query byte match. Checklist/manifests record actual success or DEFERRED items;
CPU cost on this laptop is not a delivery-machine performance guarantee.
