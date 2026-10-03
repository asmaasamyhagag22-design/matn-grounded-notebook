# The 28 design tricks

Adopted by the owner on 2026-10-03 (decision log, `docs/REVIEWER_BRIEF.md` §9). Templates are PowerPoint files that
follow `docs/design/template-contract.md`; code never draws the design, it only fills named placeholders.

**One data rule for every trick:** any value a trick shows (a number, a percentage, a bar width, a page, a quote, a
highlighted word) is copied or computed by code from a fact or a table cell. Nothing is decorative data and nothing is
invented. When the data a trick needs is missing, the trick is skipped, never faked.

Status after Step 2c (2026-10-03): tricks 3, 6, 8, 11, 13, 14, 15, 18 and 21 are done (3, 13, 14 and 21 moved
forward from 2d). Tricks 7 (icons), 16, 17 and 25, marked 2c below, are still open. The tracker sits in the chip band
at the bottom right, not at the top, so it never meets the templates' title art.

Where: **template** = built into `design/templates/<id>/template.pptx`; **renderer** = `matn_deck` code;
**deck plan** = what the planner (Step 3) puts in the `DeckPlan`.

| # | Trick | Where | Data rule | Phase | Acceptance check |
|---|---|---|---|---|---|
| 1 | Assertion titles: every title is the answer, not a topic. | deck plan | The title's numbers must appear in the facts the slide cites. | 3 | Every content title is a full sentence; digits in it match a cited fact. |
| 2 | A one-slide summary of the whole deck at the start. | deck plan | Each summary item cites the facts of the section it summarizes. | 3 | Slide 2 is `executive_summary` and cites at least one fact per section. |
| 3 | A small progress tracker at the top, showing the current section. | template + renderer | Section names and position come from the deck's `section_divider` slides. | 2c (done) | Each content slide shows a tracker whose active step is its own section. |
| 4 | Section dividers with a huge number and a one-line question. | template + renderer | The number is the divider's position, counted by code; the question is a cited item. | 2b | `matn:section_divider:default` renders `section_number` = 1, 2, 3 in order. |
| 5 | A closing slide with 3 takeaways and "decisions needed". | template + deck plan | Takeaways and decisions are cited items; no free text. | 2b | `matn:closing:default` renders up to 4 cited items; decisions block added in 2c. |
| 6 | The layout adapts to the content: 2 items split, 3 cards, 4 a 2x2 grid, ordered steps a timeline, a comparison two columns. | renderer | Variant chosen only from item count and kind, deterministically. | 2c (done) | The same item count always picks the same variant; 2b already maps 2 → two-col, 3 → cards-3. |
| 7 | Cards with an icon, a short headline and one line. | template + renderer | The headline is the item's own lead text before a colon; the icon is chosen by fact kind. | 2c | Each card has `item_N_title` from the item text and an icon from a fixed kind → icon table. |
| 8 | A bento grid for KPI dashboards. | template | Tile values are KPI facts copied by code. | 2c (done) | A `kpi:bento` variant exists and every tile value equals its fact's `value_as_written`. |
| 9 | An asymmetric 60/40 split, with the visual on the larger side. | template | The visual is a quote, chart or KPI from cited facts. | 2b | `matn:finding:split-60-40` exists in every gallery template; the larger box holds the body. |
| 10 | A big number plus its meaning in one small line. | template | Number = `value_as_written` + unit; line = the fact's label. | 2b | `matn:kpi:big-number` shows each value and its label in separate placeholders. |
| 11 | Highlight the key bar; mute the rest. | renderer | The key bar is the table cell a cited number fact points to, or the maximum, chosen by code. | 2c (done) | Exactly one data point has the accent fill; the rest use a muted theme color. |
| 12 | Direct value labels, with no legend and no gridlines. | renderer | Labels show the chart data copied from the table. | 2b | Rendered charts have data labels on, gridlines off, and a legend only for 2+ series. |
| 13 | A callout annotation on the key chart point. | renderer | Callout text is a cited fact's label and value. | 2c (done) | The callout text equals a cited number fact. |
| 14 | A pictogram for ratio facts (e.g. 1 in 4), computed from the fact. | renderer | Icon count and filled count come from the fact's numbers. | 2c (done) | A "1 in 4" fact renders 4 icons with 1 filled; other facts render no pictogram. |
| 15 | Progress bars for percentage facts, with width taken from the value. | renderer | Width = value / 100 of the track, computed by code. | 2c (done) | A 72% fact renders a bar whose width is 72% of its track (±1 EMU rounding). |
| 16 | Accent color on the number or key phrase inside titles, detected deterministically. | renderer | Only tokens that equal a cited fact's value are colored. | 2c | The accent run in a title equals a cited `value_as_written`; no other run is accented. |
| 17 | Only 3 type sizes, with strong contrast between them. | template | Not data. | 2c | The validator counts at most 3 text sizes in content layouts (big numbers excepted). |
| 18 | Balanced title line breaks: never one orphan word on the second line. | renderer | Text is never changed, only where it breaks. | 2c (done) | No rendered two-line title has a single word on line 2 when a balanced break fits. |
| 19 | Shapes and gradients in the template master backgrounds. | template | Not data. | 2b | Gallery templates keep the Office theme's master shapes and backgrounds. |
| 20 | Dark and light variants of each template. | template | Not data. | 2b | Each chosen theme has a light and a dark gallery entry (where the theme supports it). |
| 21 | A subtle geometric pattern on dividers (optional per template). | template | Not data. | 2c (done) | Templates that opt in show a pattern only on `section_divider`. |
| 22 | A rounded "p. N" source chip on every content slide. | template + renderer | N is the physical page from the cited block IDs, computed by code. | 2b | Every content slide fills `source` with "p. N" pages of the facts it cites. |
| 23 | The source chip links to the PDF at that page (experiment: PDF path#page=N). | renderer | The page is the chip's page. | 2d | Clicking the chip in PowerPoint opens the local PDF at page N (experiment report). |
| 24 | An evidence appendix ("receipts"): every number with its exact quote. | renderer + deck plan | Each line is a cited number fact: value, label, page and verbatim quote. | 2b | The appendix lists every cited number fact once, with its quote; long lists split. |
| 25 | A small check badge on verified KPI cards. | template + renderer | Shown only when the fact status is `verified`. | 2c | Verified KPI tiles show the badge; unverified ones do not. |
| 26 | Speaker notes written as a speakable script, with the quotes. | deck plan + renderer | The script cites facts; the renderer appends their quotes and pages. | 3 | Every content slide's notes hold script text plus each cited quote and page. |
| 27 | Morph transitions between related slides (experiment). | renderer | Not data. | 2d | Consecutive slides of one section use Morph (experiment report). |
| 28 | Exports: PPTX, PDF, and a one-page handout. | renderer | The handout repeats titles and cited values only. | 2d | One run writes the three files; the handout's numbers equal the deck's. |
