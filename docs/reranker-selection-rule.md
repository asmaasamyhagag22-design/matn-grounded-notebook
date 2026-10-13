**Reranker selection rule** (pre-registered 2026-10-13, before any reranker metric).

**Candidate R:** the configuration chosen under docs/retrieval-selection-rule.md
(C0 until the WEF freeze), retrieving the top 50, reranked by Qwen3-Reranker-0.6B at a
pinned revision; final top 10. Reranker input is the chunk text WITHOUT context_prefix
(the prefix homogenized vector inputs in the RAG-core diagnosis). Unchanged ordering is
used for any chunk the reranker cannot score; the reranker never adds or removes
candidates.

**Selection data:** only the reachable TUNE questions of the frozen 3-source eval, on the
post-R-lite.3 notebook. The check split is seen and never used for selection.

**Decision:** R replaces the base configuration only if ALL hold:
(a) R's hit@10 exceeds the base by at least 3 tune questions;
(b) R's MRR@10 is not lower than the base;
(c) R passes IX7 survey coverage;
(d) reranker scores are byte-identical across two separate processes.
Report exact discordant counts (McNemar) and CPU latency (p50/p95 per query) without
using them as gates; latency is decided at delivery.

**Confirmation:** after the WEF freeze, R must not trail the base by 2 or more WEF
questions in hit@10; otherwise the base is kept.

**Timing:** the comparison runs only after the WEF freeze and after the C0/C1/C2
decision. Until then, production has no reranker.
