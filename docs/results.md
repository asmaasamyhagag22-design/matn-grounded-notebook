# Results and methodology

All measurements run on a 4-core laptop CPU (i7-1065G7), 15 GB RAM, no GPU, with `qwen3.5:9b` (Q4_K_M) through Ollama. Labels come from a blind reviewer model that does not see which variant produced an answer.

## Method

- **Paired comparison.** Every question is run through both versions on the same machine, one job at a time, so timing is not contended.
- **Sealed holdout.** Questions and answer keys are written by a separate model that has not seen the code. Only the SHA-256 is recorded before development; the file is opened once, after the code is frozen.
- **Challenge set.** Planted errors in true source sentences (wrong number, unit, year, entity, scope, dropped negation, neighbouring claim) test whether the checker is too lenient. The unmodified sentences (verbatim controls) test whether it is too strict.
- **Ablations.** Each component sits behind a switch and is measured alone before it is kept.

## Current answer path vs previous version

Paired development benchmark, 104 questions (81 answerable, 23 unanswerable):

| | Previous | Current |
|---|---:|---:|
| Fully correct answers (of 81) | 7 | 22 |
| Partially correct (of 81) | 5 | 6 |
| Replies with a wrong or unsupported sentence (of 104) | 1 | 1 |
| Off-question replies (of 104) | 2 | 2 |
| Unanswerable questions correctly declined (of 23) | 20 | 22 |
| Questions whose key evidence reaches the prompt (of 81) | 41 | 52 |

Sealed holdout, 30 new questions (24 answerable, 6 unanswerable), run once per version:

| | Previous | Current |
|---|---:|---:|
| Fully correct (of 24) | 3 | 7 |
| Partially correct (of 24) | 2 | 4 |
| Wrong or unsupported replies (of 30) | 0 | 0 |
| Unanswerable correctly declined (of 6) | 5 | 5 |
| Median time per answer | 184 s | 189 s |

## Fact-checking challenge set

| Error type | n | Caught |
|---|---:|---:|
| Wrong entity | 38 | 38 |
| Wrong number | 21 | 21 |
| Number word swap | 12 | 12 |
| Wrong year | 9 | 9 |
| Swapped scope | 6 | 6 |
| Dropped negation | 5 | 5 |
| Unit change | 4 | 4 |
| Neighbouring claim | 81 | 81 |
| **Verbatim controls kept** | 81 | 81 |

The original multi-filter pipeline also caught every planted error, but it rejected all 81 verbatim controls as well, which is why it was replaced.

## Where the remaining headroom is

When the answer-key evidence is handed directly to the writer, it drafts a fully correct answer for 52 of 81 questions; the sentence checker currently displays 14 of them. Most of the remaining gap is correct sentences that the entailment model scores low when the answer rephrases the source. Improving that check, and retrieval for questions that don't name their document, are the next steps.

## Component ablations

| Component | Effect measured alone |
|---|---|
| Quotes expanded to full sentences | correct sentences shown 16 → 18, no new errors |
| Number + unit/date check | planted errors caught 172 → 175, no correct sentence rejected |
| Scope check | planted errors caught 172 → 173, no correct sentence rejected |
| Document-aware ranking | evidence reach 26 → 29 on affected questions |
| Document-aware packing | evidence reach 26 → 34, fully correct 4 → 9 on affected questions |
| Simpler writer instructions | fully correct 7 → 11 on the same validated quotes |
| Location boosting, joined-quote checking, multi-part schema | no gain; removed |
