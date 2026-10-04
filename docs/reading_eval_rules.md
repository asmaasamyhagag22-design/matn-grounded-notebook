# Reading evaluation rules (Step 4): normalization and gate thresholds. FROZEN.

Frozen on 2026-10-04, before the first measurement. `eval/tests/test_reading_rules_frozen.py` holds the sha256 of
this file and of the normalization table in `eval/reading/metrics.py`. Any change to either fails that test, so a
change has to update the frozen hashes in a commit of its own, with the owner's approval (CLAUDE.md rule 6). Rules
are never changed after a result has been seen in order to move that result.

## 1. Text normalization for CER and WER

Applied the same way to the reference and to the hypothesis, in this order. Implemented in
`eval.reading.metrics.normalize_for_cer`.

| # | Rule | Exact mapping | Why |
|---|---|---|---|
| N1 | Unicode NFC | `unicodedata.normalize("NFC", s)` | the same letter can be encoded two ways; **not NFKC**, which turns `²` into `2` and would invent digits |
| N2 | Ligatures expanded | `ﬀ→ff`, `ﬁ→fi`, `ﬂ→fl`, `ﬃ→ffi`, `ﬄ→ffl`, `ﬅ→st`, `ﬆ→st` | a font ligature is one glyph for two letters |
| N3 | Invisible characters removed | soft hyphen U+00AD; zero-width U+200B, U+200C, U+200D, U+2060; BOM U+FEFF | they print nothing |
| N4 | Quotes unified | `‘ ’ ‚ ‛ ′` → `'`; `“ ” „ ‟ ″ « »` → `"` | typographic, not content |
| N5 | Dashes and minus unified | `‐ ‑ ‒ – — ― −` (U+2010–U+2015, U+2212) → `-` | typographic; the minus sign is folded so `−3.2` and `-3.2` compare equal |
| N6 | Ellipsis | `…` → `...` | one glyph for three |
| N7 | Whitespace | every Unicode whitespace character (incl. NBSP U+00A0, thin U+2009, narrow NBSP U+202F, tabs and newlines) → one space; strip both ends | layout, not content |
| N8 | Case | **kept** | a case error is an error |
| N9 | Line-end hyphenation | **not joined**: CER/WER compare raw line text (`raw_text`, line breaks → space) | hyphen joining is judged separately in the owner review file, so it cannot hide or cause character errors |

**Order independence.** CER and WER are summed over matched regions: blocks for digital pages, lines for OCR. Regions
are matched by IoU ≥ 0.5. Reference text with no match counts as deletions, and hypothesis text with no match counts
as insertions. Reading order is its own metric (§3), so an order error is not also counted as character errors.

## 2. Numbers (exact; the key metric)

- Tokenizer: `matn_contracts.conversion.numeric_tokens`, the same one that verifies number facts against quotes.
  Before tokenizing, only N1, N3, N5 and N7 are applied (minus/dash folding matters for signs). **No other change is
  made to a number.** `1,234` and `1234` are different tokens, and so are `3.2` and `3.20`.
- Matching is by position: when every word has a box, a reference number is matched to the hypothesis word(s) at the
  same place (overlap ≥ 0.3 of the smaller box). Without boxes, the two number sequences are aligned in reading order.
- Statuses: `correct`, `wrong` (a different number at the place), `missing`, `inserted` (a number where the reference
  has none).
- **Silent error** = `wrong` or `inserted` **and not flagged**. **Silent drop** = `missing` and not flagged.
- **Flagged** = the reader marked the word or the region holding it: a figure region, hidden text, a digital-broken
  or scanned page whose text was not passed as clean, or a low-confidence OCR region.
- **Accuracy denominator** = reference numbers outside reader-flagged regions. Flagged numbers are reported
  separately per document, as a count and a share. Flagging everything therefore cannot pass the gate unseen, and the
  owner checks the flagged regions on the overlays.

### Reference for each page type

| Page type | Reference | Why it is independent |
|---|---|---|
| digital | PyMuPDF words (`page.get_text("words")`), eval tooling only (ADR-0001) | a different engine (MuPDF) from the reader (pdfminer + PDFium) |
| synthetic scan | the page's own text layer, read with pdfplumber; word boxes scaled to 300 DPI and moved with the seeded rotation; only text that is visibly painted | the image was made from this layer, so the truth is exact |
| real scan | the owner's hand-verified files in `eval/reading/real/gt/`; a file counts only when `status` is `verified` | a human, from the image |

A real-scan PDF is measured only after `eval.reading.real.verify.require_verified` confirms its sha256.

## 3. Structure metrics

- **TEDS**: Zhong et al. 2020. The tree is `table > tr > td`, and a `td` carries text, colspan and rowspan. Insert and
  delete cost 1. Renaming costs 1 if the tag or a span differs, otherwise the normalized Levenshtein distance of the
  text. TEDS = 1 − TED / max(nodes), with nodes counted below the table root as in the PubTabNet reference implementation.
  Cell text gets the §1 normalization on both sides first. Pinned by `eval/tests/test_reading_teds_reference.py`
  against values computed once with that implementation (5 tables, full and structure-only; all match to 1e-12).
- **Reading order** = 1 − normalized edit distance between the reference block order and the predicted order of the
  matched blocks.
- **Block type** = the share of reference blocks matched by a predicted block of the same type. Unmatched blocks count
  as wrong.
- For digital pages, reading order and block types are measured on the 10 pages the owner confirms in
  `reports/step4-reading-review.md`. Until she confirms them, they are reported as "pending owner confirmation".

## 4. Gate thresholds

### Step 4b (digital reading), all on the 3 dev documents

| Item | Threshold |
|---|---|
| Number accuracy, digital pages (denominator as in §2) | **= 100%** |
| Silent errors, digital pages | **= 0** |
| Silent drops, digital pages | **= 0** |
| Triage reasons | recorded for **100%** of pages |
| Hidden text | `hidden_image`, `hidden_vector`, `hidden_color` and the render-mode-3 OCR layer each have a test and are reported separately; hidden text never appears in prose |
| Overlays | one PNG per page exists for the 3 dev documents |
| Metrics table | reported per page type: digital, synthetic scan, real scan |
| Synthetic scans | **baseline only, no threshold** (no OCR yet) |
| CER / WER, digital | reported, no threshold (the reference extractor differs in small ways) |

### Step 4c (OCR), frozen now so it cannot drift after results

| Item | Threshold |
|---|---|
| Silent errors, every page type | **= 0** |
| Reader 1 vs reader 2 agreement and disagreement rates on number tokens | reported |
| False-alarm rate = disagreements where reader 1 was right / all disagreements | reported; target set by the owner after the first 4c run, not before |
| Number accuracy and CER on synthetic and real scans | reported per page type |
