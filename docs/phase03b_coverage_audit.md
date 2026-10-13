# Phase 03B coverage audit (pre-remediation)

Date: 2026-09-28  
Baseline: uncommitted Phase 03 implementation on `1bdbba7`  
Audited run: `output/phase03-acceptance-sec2-en`

## Method and evidence limits

This audit was completed before the Phase 03B implementation was changed. The
unchanged evaluation checklist was used only to locate expected source evidence
and score the output; it was not supplied to a generation prompt.

The baseline hierarchical run put 18 source units (7,514 source characters) in
map batch 1 and only the final Figure 2 caption chunk in batch 2. Batch 1's
preflight total was 4,073 of 4,096 tokens (23 tokens of headroom). The claims
schema imposed `maxItems: 3`, and each map batch returned exactly three claims.
All six returned claims passed quote/boundary validation and no claim was removed
by deduplication. Raw model responses were not persisted, so it is not possible
to distinguish “never generated” from “generated outside the schema-constrained
JSON” after the fact. There is no evidence that validation or deduplication
caused the missing checklist content.

`partial` means that a value or broad concept appeared only as metadata or as an
underspecified claim, not as the required atomic proposition. `N/A` means that a
full-Section-2 Arabic rendering from the same semantic plan did not exist in the
baseline artifacts.

## Expectation trace

| expectation_id | source_chunk_ids | source_pages | source_present | map_generated | validation_accepted | survived_deduplication | included_in_synthesis | rendered_in_english | rendered_in_arabic | loss_stage | evidence | proposed_generic_fix |
|---|---|---:|---|---|---|---|---|---|---|---|---|---|
| C01 | `chk-a9131be726305087`, `chk-0c49fba7086a84f6`, `chk-9f608c45efca897b` | 2, 3 | yes, batch 1 | yes | yes (`b1-c1`, `b1-c3`) | yes | yes | yes | N/A | none for broad requirement | Accepted claims cover input/output; implementation/run detail is abbreviated. Extract atomically per chunk before selection. |
| C02 | `chk-4f9d92a606f186e9` | 2 | yes, batch 1 | yes | yes (`b1-c2`) | yes | yes | yes | N/A | none | Quote and summary contain the environment elements. |
| C03 | `chk-4f9d92a606f186e9` | 2 | yes, batch 1 | no | no claim | N/A | no | no | N/A | map generation | The chunk states open-ended problems, established baselines, and straightforward measurement; none occurs in `claims.json`. Map smaller units without a global three-claim cap and report chunks without claims. |
| C04 | `chk-4f9d92a606f186e9`, `chk-0dee782b95c03512` | 2, 3 | yes, batch 1 | no | no claim | N/A | no | no | N/A | map generation | Both named environments are in source; neither distinction occurs in claims/summary. Extract named distinctions independently of output language. |
| C05 | `chk-4f9d92a606f186e9` | 2 | yes, batch 1 | no | no claim | N/A | no | no | N/A | map generation | `124M`, `GPT-2`, `FineWeb`, `3.28`, and `8 H100` are in the chunk but absent from claims. Extract number candidates with local context, then create supported atomic claims. |
| C06 | `chk-4f9d92a606f186e9` | 2 | yes, batch 1 | no | no claim | N/A | no | no | N/A | map generation | Reciprocal validation loss and the 25-minute budget are in source but absent from claims. Preserve metric/constraint identity during extraction and deduplication. |
| C07 | `chk-4f9d92a606f186e9`, `chk-95b8db32a4489da2` | 2, 3 | yes, batch 1 | no | no claim | N/A | no | no | N/A | map generation | The cross-chunk sentence completes on page 3; the map produced no limitation claim. Use micro-batches with small overlap/adjacency and limitation candidates; never synthesize “none stated.” |
| C08 | `chk-95b8db32a4489da2` | 3 | yes, batch 1 | no | no claim | N/A | no | no | N/A | map generation | Frozen evaluation hyperparameters and one-token prediction are present but absent from claims. Explicitly extract procedures, constraints, caveats, and failure conditions. |
| C09 | `chk-0dee782b95c03512` | 3 | yes, batch 1 | no | no claim | N/A | no | no | N/A | map generation | `Qwen2.5Math-1.5B`, GRPO, and MATH are present but absent from claims. Extract model/benchmark names and numbers before summarization. |
| C10 | `chk-0dee782b95c03512` | 3 | yes, batch 1 | no | no claim | N/A | no | no | N/A | map generation | Maximum validation accuracy is present; average accuracy/Precision are not the stated metric. Preserve metric qualifiers and prevent near-term conflation. |
| C11 | `chk-0dee782b95c03512` | 3 | yes, batch 1 | no | no claim | N/A | no | no | N/A | map generation | Isolated validation code and denied executor access are present but absent from claims. Extract access constraints as limitations. |
| C12 | `chk-5c992f410eb15a5c` | 3 | yes, batch 1 | no | no claim | N/A | no | no | N/A | map generation | Unconstrained scope from tuning through architectures/algorithms is absent from claims. Ensure every nonempty semantic chunk is accounted for. |
| C13 | `chk-9f608c45efca897b` | 3 | yes, batch 1 | partial | no atomic role claim | N/A | partial | partial | N/A | map generation / synthesis selection | A claim describes the API, but Implementer/Scheduler/Worker identities and roles are omitted. Extract roles/relationships separately; do not deduplicate distinct roles. |
| C14 | `chk-a482bb29c860e301` | 3 | yes, batch 1 | partial | no supported atomic claim | N/A | no | no | N/A | map generation | `10 code diff files` appeared only in `numbers_and_units` attached to a claim whose quote/text does not support it. Require each numeric candidate to be tied to a supporting atomic claim and quote. |
| C15 | `chk-a482bb29c860e301` | 3 | yes, batch 1 | partial | no supported atomic claim | N/A | no | no | N/A | map generation | `2 times` appeared only in metadata; revision and first-patchable behavior were not claimed. Extract procedure steps/limits atomically and validate number presence in evidence. |
| C16 | `chk-d077c59d6d622a74` | 3 | yes, batch 1 | no | no claim | N/A | no | no | N/A | map generation | Scheduler behavior is present but absent from claims. Smaller batches plus per-chunk completeness accounting. |
| C17 | `chk-9e39095cfe6563ae` | 3 | yes, batch 1 | no | no claim | N/A | no | no | N/A | map generation | Worker GPU, upload, metadata, and halt behavior are present but absent from claims. Smaller batches plus multiple claims per chunk. |
| C18 | `chk-6a1baf5faaaf1106`, `chk-a5d892c4afa4bc8b`, `chk-fc3cdfb7e3786ed4` | 2, 3 | yes, batch 1/2 | unsafe figure claims generated in batch 2; risk not attached to claims | claims accepted by text match only | yes | unsafe values selected; deterministic coverage flag added later | extraction warning rendered | N/A | risk classification after claim selection | `0.480` and `3.255` were accepted solely from extracted caption text; summary also says table extraction is limited. Mark figure/table values `human_review_required`, `visually_verified`, or excluded before selection; never infer visual verification. |

## Root-cause summary by stage

- **Source batching:** all checklist evidence was present, but nearly the whole
  section was placed in one map batch. The near-limit 4,073/4,096 preflight left
  no operational headroom.
- **Map generation / schema pressure:** this is the primary loss stage. A
  three-item schema cap forced a rich 18-unit batch into three claims. The map
  prompt also mixed extraction with audience, requested length, language, and
  glossary rendering.
- **Validation:** every emitted claim was accepted. Validation checked quote
  occurrence but did not ensure that numbers/terms were supported by the quoted
  evidence or classify figure/table extraction risk.
- **Deduplication:** no baseline claim was removed. The existing deduplicator is
  nevertheless too coarse for future inventories because it lacks explicit
  safeguards for distinct numbers, roles, constraints, metrics, and limitations.
- **Synthesis:** the synthesis saw only six accepted claims and selected five;
  it had no inventory/omission contract. It generated an unsupported “No
  specific limitations...” statement from claims that themselves used “None
  stated in source.”
- **Language rendering:** full Section 2 Arabic parity cannot be audited because
  no Arabic rendering from the English semantic plan exists. Baseline Arabic
  mapping was a separate language-dependent extraction, so parity was not
  structurally guaranteed.
- **Observability:** raw model output and per-batch processed/skipped chunk
  metadata were not stored, preventing a finer retrospective distinction between
  model omission and schema-constrained omission.

## Baseline metric interpretation

The preliminary checklist review remains non-human and reports idea coverage
2/6, required numeric coverage 0/5, required terminology coverage 0/3, and
required limitations coverage 1/4. Generated-number correctness and
generated-terminology correctness are **N/A** until their generated instances
are reviewed. These correctness metrics must not use missing expected items in
their denominators, and N/A must not be converted to zero or included in a
denominator.

## Post-remediation trace (2026-09-29)

The first Phase 03B remediation run exposed four incomplete selected fragments
among 37 entries. They were two split sentences: one across extraction-order
chunks on PDF page 2, and one across PDF pages 2 and 3. The general reconciler
now joins only sentence-compatible leading/trailing fragments while retaining
ordered evidence spans. Complete adjacent sentences remain separate, and an
unresolved fragment aborts publication.

The canonical full-Section-2 run at
`output/phase03b-exp-i3-sec2-full-en` contains 39 validated inventory claims and
selects 35 complete propositions. It reports two multi-span merged claims and
zero unresolved fragments. The user-facing summary groups those 35 claims into
nine thematic units; the review package remains one row per selected claim.

Every checklist expectation C01-C18 is present in the frozen English semantic
plan or its explicit extraction-risk disclosure. The unchanged checklist plus
the non-independent presence decisions produces: ideas 6/6, required numbers
5/5, required terminology 3/3, and required limitations 4/4. Citation IDs,
exact quotes, canonical quotes, and boundary purity are 41/41 evidence spans.
Generated-number correctness, generated-terminology correctness, semantic
citation support, and unsupported-claim rate remain N/A pending human review.

The canonical claim text represents the reciprocal metric as `1 / loss`, and
normalizes the source-supported technical tokens to `Qwen2.5-Math-1.5B` and
`self-execution`. Exact extracted text is preserved independently, including
the malformed math markup, so normalization cannot conceal the source evidence.

The two Figure 2 textual-caption values (`0.480` and `3.255`) were visually
checked on PDF page 3 and retained. Values found only in extraction-risk
figure/table content remain omitted pending visual review. Both English and
Arabic coverage notices make that distinction instead of claiming that every
risky numeric value was omitted.

The primary loss stage was removed by replacing the three-claim,
near-context-limit map with a lossless language-independent inventory plus
sentence-aware reconciliation. Optional model-map enrichment remains available,
but the accepted default does not depend on it. The final 17 deterministic
micro-batches reserve 1,536 tokens and a 512-token safety margin; recorded
preflight headroom is 1,138-1,301 tokens.
