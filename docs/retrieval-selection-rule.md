**Retrieval configuration selection rule** (pre-registered 2026-10-13, before any
post-R-lite.3 retrieval metric).

**Candidates:**
- C0: current, with context_prefix in the embedding input and equal-weight RRF k=60;
- C1: hybrid without context_prefix in the embedding input;
- C2: BM25-only.

Rerankers and contextual-retrieval variants are NOT candidates under this rule; each
needs its own pre-registered rule.

**Selection data:** only the reachable TUNE questions of the frozen 3-source eval, run
on the post-R-lite.3 notebook. The check split is seen and is never used for
selection.

**Metrics:** primary hit@10; secondary MRR@10; tertiary hit@5.

**Decision:** C0 is the incumbent. A candidate X replaces C0 only if ALL of these hold:
(a) X's hit@10 exceeds C0's by at least 3 tune questions;
(b) X's MRR@10 is not lower than C0's;
(c) X passes IX7 survey coverage.
If several candidates qualify, choose the highest hit@10; break ties by higher MRR@10,
then by the simpler configuration (C2, then C1). Report exact discordant counts
(McNemar) without using them as a gate.

**Confirmation:** after the WEF questions are frozen (redraft, different-family screen,
owner review), X must not trail C0 by 2 or more WEF questions in hit@10; otherwise
revert to C0.

**Timing:** the comparison runs only after the WEF freeze. Until then, production stays
C0.
