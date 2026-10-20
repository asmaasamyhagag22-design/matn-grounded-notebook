# Validation and experiment scope

## Regression coverage

The private development checkout recorded **1,139 passing tests** on 19 October 2026 across application, evaluation, boundary-check, and Git-hook suites. It includes checks for source-span coverage, deterministic retrieval, numerical and entity mismatches, invalid handles, structured-output constraints, memory deferral, and checkpoint reuse.

The public checkout preserves the existing publication adaptations: sealed gold and local source assets are absent; optional integration checks skip when their prerequisites are unavailable. On 19 October 2026, the public checkout passed **1,042 tests**, with **9 prerequisite-based skips**, in **377.78 seconds**, across `tests`, `eval/tests`, `checks`, and `.githooks`. These results must not be substituted for the original experiments.

## Retrieval

The selected configuration is source-scoped hybrid retrieval without context prefixes or a reranker. On the frozen three-source development set, historical hit@10 was **42/57 reachable questions (73.68%)**, or **42/60** when reading-unreachable questions are included. These are retrieval results on that corpus, not general answer accuracy. See the selection rule and [`rag-core.md`](rag-core.md) for definitions and scope.

## Chat experiment snapshot: C1b (19 October 2026)

Operational changes included a fixed 16,384-token context, a 60-minute model-residency request, per-request handle enums, an identical redraft prompt prefix, and a 1.5 GiB available-memory guard. Embedding queries used cached vectors; there were zero cache misses.

| Outcome | Frozen60 | Confirmation |
|---|---:|---:|
| Answer passed the verifier | 2 | 0 |
| Insufficient verified evidence | 18 | 0 |
| Deferred for memory | 40 | 39 |

Twenty-two frozen questions have saved generation responses, including two attempts whose redrafts were memory-deferred. All 99 questions have checkpoints, which does **not** mean that all 99 were generated. At that checkpoint, the resulting 43 candidate sentences were unlabeled and unfrozen.

All returned handles belonged to the request's enum. Sixteen first/redraft pairs had byte-identical prefixes; the median redraft/first prompt-evaluation time ratio was **0.346**, with p95 **0.572**. This comparison includes different suffix lengths and an interrupted run, so it does not establish a causal speedup. For the 22 questions with generation, active total latency p50/p95 was **401.40 / 572.92 seconds**, excluding interruption downtime.

Sampled peak runner RSS was **9.323 GiB**, peak verifier-worker RSS **1.632 GiB**, and peak simultaneous combined RSS **10.300 GiB**. Whole-system available memory fell to **0.088 GiB**. The userspace OOM manager killed the application scope once; the collection resumed from its cache under the original identity and deadline, using an independent transient process and unloading the verifier before generation. No kernel runner OOM was recorded. Remaining questions were deferred according to the guard, rather than retried or replaced.

These are operational and coverage observations. Passing a verifier is not a human support label, and neither these figures nor the regression count establish production readiness.


## CPU runtime profile (20 October 2026)

The optional bounded CPU launcher and its seven regression tests are published with [runtime setup and matched diagnostic measurements](cpu-runtime.md). The new tests pass without model inference. Publication retains the mandatory fast pre-commit and full pre-push checks. The diagnostic measures resource use and latency; it does not score answer support or establish long-run stability. Internal reports, raw responses, labeling packets and the source-containing diagnostic harness remain outside the public copy.
