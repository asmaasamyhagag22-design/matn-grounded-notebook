# ADR 0046 — Make quote-first answers the default

Accepted on 11 November 2026. This advances the experimental path in [ADR 0045](0045-answer-path-v3-quote-first.md).

On the same 104 development questions, fully correct answers rose from 7 to 22 out of 81 answerable questions. Across all 104 questions, one reply contained a wrong or unsupported claim in each version, and two replies were off-question in each version. A blind reviewer model scored both versions. The final challenge caught all 176 planted errors and kept all 81 verbatim controls. [Results and methodology](../results.md)

- Quotes can expand to sentence boundaries within the same source chunk. Incomplete related excerpts that run into a separate bullet are dropped. The writer produces direct sentences, each supported by at least one quote.
- MiniCheck scores each cited quote independently. Failed sentences are retracted individually. The number check binds values to their unit or calendar date, and the scope check catches swapped scope modifiers for the same named organisation.
- If a question clearly names one document, its hits get priority. Packing draws from distinct hits within that document under the existing token cap. Ambiguous matches and multi-document questions keep the normal ranking.

The shipped profile selects `v3`. The `v2` path remains selectable. Each v3.1 change has a boolean in [the answer policy](../../matn_app/answer_v3_policy.json) and can be overridden through `v3_components` in a custom profile. [Local setup](../local-setup.md)
