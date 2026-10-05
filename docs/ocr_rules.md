# OCR rules (Step 4c close-out). Re-frozen before holdout-2.

Frozen on 2026-10-05, before any OCR result was measured. `eval/tests/test_ocr_rules_frozen.py` holds the sha256 of
this file, `matn_reading/ocr/ocr_rules.json`, `matn_reading/ocr/rapidocr_settings.json`,
`matn_reading/ocr/consensus.py`, `matn_reading/ocr/numbers.py` and `matn_reading/ocr/consistency.py`. Changing
any of them needs its own commit with the owner's approval. The single planned exception is
`confidence_bar` (§4): it is calibrated on dev-tune and frozen in its own commit **before** dev-check is measured.
The owner approved close-out changes on Oct 6: dev-check is now seen. Nothing changes after holdout-2 results are opened. The digital rules (`docs/reading_eval_rules.md`) stay as they are; its §2
number tokenizer and normalization are reused here unchanged.

## 1. Readers

- **Reader 1:** PP-OCRv5 mobile det + rec (ONNX conversion of the pinned Paddle models), RapidOCR 3.9.2 on onnxruntime
  1.30.0, CPU, in `.venv-ocr-rapid`, settings `matn_reading/ocr/rapidocr_settings.json`. It loads only from
  `models/ocr/rapidocr/` after a sha256 check, runs under `block_egress()`, has the classifier off, and
  `text_score` 0 (no line is dropped for low confidence).
- **Reader 2:** GLM-OCR `glm-ocr:bf16` via Ollama on 127.0.0.1 (no-proxy opener). Prompt `Text Recognition:`,
  `num_ctx` 16384, `temperature` 0, `seed` 0, `num_predict` 128, stop at the first newline, one call per **whole
  line** (the reader-1 line box plus 8 px), never per number and never a whole page. Results are cached by the sha256 of
  the crop bytes plus model and options. A failed or empty read is never cached.

## 2. Page images

Render the CropBox at 300 DPI with pypdfium2, then deskew (projection profile, ±4°, 0.25° coarse and 0.02° fine
steps), then noise-adaptive denoise. Estimate RMS residual on flat-neighbor pixels (neighbor range < 30).
Below **2.0**, do not filter; at/above 2.0, a light 3×3 bilateral filter (range sigma 16, spatial sigma 1),
with isolated one-pixel impulse repair. Connected punctuation remains intact. `applied` records whether the
caller enabled the denoise stage; `filtered` records whether the image was actually filtered.
Threshold 2.0 was selected on **19 dev-tune pages only**, with GAO p12 excluded, by highest exact number accuracy,
then lower median CER, then higher threshold. Grid 2/2.5/4/6/8. Full paired results (20 pages retained) and evidence:
`reports/step4c-denoise-selection.json`. No holdout-2 or seen-check results were used.

## 3. Consensus (no silent choice between readers)

- Both lines are normalized with N1, N3, N5 and N7 only, then tokenized with the frozen reader tokenizer
  (`matn_reading/ocr/numbers.py`, identical to `eval.reading.metrics`). The two token sequences are aligned in reading
  order (longest common subsequence).
- A reader-1 number is **accepted** only when reader 2 has the identical token at the aligned place.
  `1,240` vs `1240`, and `3.2` vs `3.20`, are disagreements.
- Otherwise it is `uncertain_number`. The flag keeps reader 1's token, reader 2's competing token (or none), reader 2's
  whole line, and the saved crop. Reader 2 never replaces reader 1's value.
- A number that only reader 2 sees flags the line as `possible_drop`. A failed second read flags every number on
  the line (`second_read_failed`).

## 4. Which lines get a second read, and the confidence bar

- Targets are configurable for the harness/ablations. The production default is **all** on both laptop and GPU; even a score of exactly 1.0 gets a second read. The frozen confidence bar remains 1.0.
  A line is second-read when any of its numbers is targeted, and then the consensus verdict applies to every number
  on that line.
  - `low_confidence`: the number's reader-1 word score is below `confidence_bar`;
  - `table`: the line lies in a table: at least 2 consecutive rows, each with at least 2 gap-separated cells,
    at least one of them numeric;
  - `kpi`: the word holds `%`, `$`, `€` or `£`; or the next word is a scale unit (million, billion, trillion,
    percent, bn, mn); or the line is at least 1.5× the page's median line height;
  - `summary`: the line overlaps a region the caller marks as a summary candidate (Steps 5-8 pass these).
- A number on a line that is not second-read is accepted on reader 1 alone only when its score is at least the bar.
  Below the bar it is flagged `low_confidence`. Any non-number word below the bar is flagged `low_confidence`.
- **Calibration (dev-tune only, GAO p12 excluded).** Run the full preprocessing and reader 1. A number is a candidate
  error when it is not correct by the §6 matching. The bar is the smallest value on the grid 0.50, 0.51, …, 0.99,
  0.995, 0.999, 1.0 such that every wrong reader-1 number **outside** table/KPI lines has a score below it. Those
  are exactly the numbers that would otherwise be accepted on reader 1 alone. The value is written into
  `ocr_rules.json` and frozen in its own commit before dev-check is measured.

## 5. Free internal checks and the OCR layer

- Table totals and text-vs-table repeats: `matn_reading/ocr/consistency.py` (docstring = the rule). Every number
  involved in a mismatch is flagged.
- On a scanned page with an embedded OCR layer (render mode 3), every reader-1 number is compared with the layer's
  words under it (overlap ≥ 0.3 of the smaller box). A number that is not among the layer's tokens is flagged
  `ocr_layer_disagreement`. A layer number with no reader-1 number on it is flagged `possible_drop`.
- An inked page (more than 0.5% of pixels darker than 128) where reader 1 finds no text is flagged `ocr_no_text`
  as a whole.

## 6. Measurement on synthetic scans (Part 3)

- **Pages:** the 31 pages of `eval/reading/synthetic/pages.json`, split by `eval/reading/dev_split.json` (20
  dev-tune, 11 dev-check). Image = 300-DPI pypdfium2 render, then `eval.reading.degrade.degrade` with
  `page_seed(doc_id, page_index)`.
- **Ground truth:** the page's own text layer as read by `matn_reading` (pdfplumber). It includes every visible
  word of every block (prose, headings, tables, figure text, headers, footers, footnotes) plus footnote markers as
  their own words; `hidden`/`uncertain` text is excluded because it is not painted. Boxes are scaled to 300 DPI and
  rotated by the degradation angle plus the applied deskew angle (`eval.reading.degrade.rotate_bbox`), so they sit
  where the processed image shows them.
- **Numbers:** `eval.reading.metrics.score_numbers` with boxes. Reader-1 number tokens carry their own boxes (the
  word box split by character position) and their flag. Regions flagged `possible_drop` or `ocr_no_text` count as
  flagged regions.
  - **Silent error** = wrong or inserted and not flagged (target 0). **Silent drop** = missing and not flagged.
  - **Flag rate** = flagged reader-1 number tokens / all reader-1 number tokens.
  - **False-alarm rate** = flagged tokens that reader 1 read correctly / all flagged tokens. A token is correct
    when it equals a token of the ground-truth word it overlaps most (overlap ≥ 0.3 of the smaller box).
  - **Agreement rate** = second-read tokens that both readers agree on / all second-read tokens.
  - **Review burden** = flagged numbers per page.
- **CER/WER:** the frozen §1 normalization, summed over lines matched by IoU ≥ 0.5 (ground-truth lines vs reader-1
  lines in the same frame).
- **Time per page:** preprocessing + reader 1 + every second-read call. A cached call counts the seconds recorded
  when it ran. Reported with and without second reads.
- **Ablations**, each on the same pages: `full` (deskew + denoise + laptop second reads), `no_deskew`, `no_denoise`,
  and `reader1_alone` (no second reads; the bar still flags low confidence).
- **Current gate:** 0 reader-attributed silent number errors on **holdout-2**, after visually adjudicating every raw
  silent error. Report raw counts alongside adjudication, flag rate and false-alarm share of flags. Never tune on
  holdout-2; a failure is BLOCKED-ON-OWNER. The 20 tune/11 seen-check pages are diagnostics, not the current gate.
  The 30 holdout-2 pages/seeds were committed in f4d87a1 before any close-out code, stratified by dev document and
  digital-metadata page type and disjoint from all 31 prior OCR synthetic pages. They were previously measured
  digitally in 4b; this is an OCR holdout, not independent documents.
- **Real scans:** measured only after `eval.reading.real.verify` confirms the sha256. Results, flags and time are
  reported, with no gate, until the owner's hand-verified ground truth exists (`status: verified`).


## 7. Close-out semantic regions and orientation (approved Oct 6, frozen before holdout-2)

`matn_reading/ocr/closeout_rules.json` pins the PP-DocLayoutV2 ONNX path, bytes and full hash. rapid-layout 1.2.1,
confidence threshold **0.5**, local CPU provider, egress guard. Missing/bad models refuse the worker startup.
Classify words with **>=0.5 of their own area** covered by a region; captions take precedence over an enclosing
image, then the smaller region. `chart`/`image` text becomes `figure_text`; `header`/`footer`/images and page
`number` become page furniture. `figure_title`/`table_title` remain captions, footnotes remain footnotes.
`figure_text`/`marginalia` map to the existing Block type `figure` and are outside prose; their numbers are flagged.
No new contract enum/version. Production tables and text-table checks operate only on detected `table` regions;
code columns are never promoted by the old gap heuristic. Protocol-less injected unit-test readers alone retain
that heuristic to exercise the existing table arithmetic tests.

Orientation: polygon baseline angle **>=15 degrees**, or vertical aspect ratio **>1.8**, or `vertical_text` class.
Use the long polygon side for clearly vertical regions, baseline for ordinary lines (short upright digits are
not rotated just because a glyph is taller than wide). Rotate the padded crop upright, read it again with reader 1,
then reader 2. Keep reader 1's original value; accept a number only if the post-rotation sequences exactly agree
and preserve the original numeric sequence. Otherwise `rotation_uncertain` / `uncertain_number`. Reader-2-only
numbers become `possible_drop`. A vertical region missed by the OCR detector still gets this re-read. Rotated
stamps in the outer **8%** side margins become marginalia, even if readers agree.
If that side strip contains rotated marginalia, horizontal-looking text fragments entirely within the same
strip are also marginalia (the detector can split a vertical stamp into tall letters and one short digit).
Explicit captions/tables/figure/furniture roles and body text outside that strip keep their classification.
This correction was identified on dev-tune arXiv p0 and re-frozen before any holdout-2 read.

Distinct detector lines whose numeric token boxes overlap by **>=0.5 of the smaller area** flag both tokens as
`uncertain_number`, reason `overlapping_number_detections`, even if both second reads agree. Values and detections
are preserved; there is no silent deduplication or replacement. This addresses dev-tune WB p10's duplicate final
`1` from `FY2020/21`. It does not change numeric normalization, raw matching, or the all-number second-read rule.
The additional consistency rule was re-frozen before any holdout-2 result, using dev-tune evidence only.

Multi-page one-command reading cross-checks furniture by repetition within the outer **8%** top/bottom margins:
normalized digits, at least **2** distinct pages and **>=50%** of input pages. Single-page benchmark results use
the layout classes; the repetition cross-check is covered by its multi-page regression test.

All original numeric normalization, matching thresholds and raw scoring remain unchanged. Semantic exclusions
count as flagged tokens in the historical flag-rate definition. The reported false-alarm share includes correct
reads excluded for legitimate layout reasons; role counts are shown separately so this is not mistaken for
uncertainty-review burden. Real GT remains owner-only. True real false alarms need signed full-page review;
`real.measure` reports both false-alarm share among flags and false-positive rate on correct reads.
