# ADR 0045 — Select quotes before writing answers

The earlier answer path sometimes lost relevant spans before planning, then discarded correct drafts even when evidence reached the writer. The quote-first path changes retrieval, generation and verification together. [ADR 0046](0046-default-quote-first-answers.md) records the decision to make this path the default.

- Retrieval combines BM25, dense cosine similarity and reciprocal rank fusion. Titles, section context and exact identifiers inform ranking. Older notebooks with incomplete vectors embed a bounded pool of lexical candidates. The packer uses verified paragraph offsets when possible and respects a fixed token budget.
- A structured call proposes quotes. Code binds whitespace-normalized matches to the original text and assigns quote IDs and PDF locators. The writer receives validated quotes and writes short sentences with those IDs. Section headings remain available to retrieval. The generation prompt spends its space on source passages.
- A sentence needs entailment support from at least one cited quote and must preserve cited numbers. Each failed sentence is retracted on its own. The earlier checks and the separate relevance score remain available in the receipt. When no direct quote supports a reply, validated background may appear under Related information.
- A single quote must support the whole sentence. Combining facts across quotes can leave a valid claim without a sufficient individual premise. The relevance score is advisory and supported background can still be off-question.

Removing section paths from the quote prompt and allowing up to 32 passages inside the same 2,304-token budget improved evidence reach in a development packing probe. At least one key span reached the prompt for 33 of 57 cases, up from 27. All key spans reached the prompt for 21 of 57 cases, up from 17. Paired runs and the challenge set measured answer quality and latency. [Results and methodology](../results.md)
