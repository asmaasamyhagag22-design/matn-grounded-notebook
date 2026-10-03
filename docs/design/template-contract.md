# Template contract (v2, Step 2c)

A Matn template is a `.pptx` whose **slide layouts** follow the names below. The renderer picks a layout by name and
fills its placeholders by name. The template owns fonts, colors, backgrounds, master art, the title box, the content
area and the rounded "p. N" chip. Since Step 2c the renderer also places the content inside the content area (§5):
it sets placeholder boxes and type sizes, and draws native-shape visuals (cards, bars, icons, timeline, tracker) for
filled slots only, using theme color slots so every template keeps its palette. Values are still copied from facts and
tables by code (`docs/design/tricks.md`, data rule).

Later phases add variants and optional placeholders; they never rename or remove what is listed here.

## 1. File rules (checked by `matn_deck.templates.validate_template`)

- Slide size 16:9 (`12192000 x 6858000` EMU, or any size with a 16:9 ratio).
- The file holds **no slides**: sample slides left in a template are an error.
- Every layout in §3 exists exactly once. Extra layouts named `matn:<known slide_type>:<new variant>` are allowed
  (forward compatibility); any other layout name is a warning.
- Inside a layout, placeholder names are unique. Required placeholders (§3) must exist.
- Fonts: the theme's heading and body fonts (latin and complex script) and every explicit typeface in the master and
  layouts are standard Windows/Office fonts (`STANDARD_FONTS` in `matn_deck/templates.py`: Aptos, Bahnschrift,
  Segoe UI, Calibri, Arial, Cambria, Candara, Corbel, Georgia, Tahoma, Verdana, Times New Roman, Wingdings and the
  Windows Arabic fonts).
- Only templates that pass appear in the gallery (`matn_deck.templates.gallery()`).

Each gallery template lives in `design/templates/<id>/` with `template.pptx`, `thumbnail.png` and `theme.json`:

```json
{"id": "facet-light", "name_ar": "...", "name_en": "Facet (light)", "fonts": {"heading": "...", "body": "..."},
 "mode": "light", "source": "Office theme Facet"}
```

## 2. Names

- Layout name: `matn:<slide_type>:<variant>`, where `slide_type` is a `SlideType` value (`matn_contracts/enums.py`).
- Placeholder names (the shape name of the placeholder in the layout):

| Name | Kind | Filled with (by code) |
|---|---|---|
| `title` | title | the slide title |
| `subtitle` | text | title slide: the plan's items; divider: its one question |
| `body` | text | a list of item texts, one paragraph each (template styles the bullets) |
| `item_1` .. `item_4` | text | one item's text (after its lead, see §4) |
| `item_1_title` .. `item_4_title` | text | the item's lead before ": ", else its ordinal "01".."04" |
| `kpi_value_1` .. `kpi_value_4` | text | a number fact's `value_as_written` + unit |
| `kpi_label_1` .. `kpi_label_4` | text | that fact's `label` |
| `chart` | chart | a native chart built from the table cells; it inherits the theme colors |
| `quote` | text | the verbatim quote of the first cited fact, in quotation marks |
| `attribution` | text | the quote's page, "p. N" |
| `source` | text | the cited pages, "p. N, M" (+ "(table)"); styled by the template as a small rounded chip |
| `section_number` | text | the divider's position, "01", "02", ... counted by code |
| `marker_1` .. `marker_4` | text | the item's ordinal "1".."4"; styled by the template as an accent oval (2c) |
| `decisions_title` | text | closing: the label "Decisions needed" (2c) |
| `decisions` | text | closing: the items that cite only recommendation facts, one paragraph each (2c) |

## 3. Layouts for 2b (R = required, O = optional)

| Layout | Required | Optional |
|---|---|---|
| `matn:title:default` | title | subtitle |
| `matn:executive_summary:default` | title, item_1..item_4, source | item_1_title..item_4_title |
| `matn:kpi:big-number` | title, kpi_value_1..2, kpi_label_1..2, source | body |
| `matn:kpi:cards` | title, kpi_value_1..4, kpi_label_1..4, source | body |
| `matn:finding:split-60-40` | title, body, quote, source | attribution |
| `matn:finding:cards-3` | title, item_1..item_3, source | item_1_title..item_3_title |
| `matn:finding:two-col` | title, item_1, item_2, source | item_1_title, item_2_title |
| `matn:chart:hero` | title, chart, source | body |
| `matn:implications:default` | title, item_1..item_4, source | item_1_title..item_4_title |
| `matn:limitations:default` | title, body, source | |
| `matn:sources:default` | title, body | |
| `matn:section_divider:default` | title, section_number | subtitle |
| `matn:closing:default` | title, item_1..item_4, source | item_1_title..item_4_title |
| `matn:evidence_appendix:default` | title, body, source | |

Step 2c variants (the same rules; geometry in `design/variants.json`):

| Layout | Required | Optional |
|---|---|---|
| `matn:executive_summary:grid-2x2` | title, item_1..item_4, source | item_1_title..item_4_title |
| `matn:kpi:hero-number` | title, kpi_value_1, kpi_label_1, source | body |
| `matn:kpi:bento` | title, kpi_value_1..4, kpi_label_1..4, source | body |
| `matn:kpi:pictogram` | title, kpi_value_1..2, kpi_label_1..2, source | body |
| `matn:kpi:progress` | title, kpi_value_1..4, kpi_label_1..4, source | body |
| `matn:finding:two-split` | title, item_1..item_2, marker_1..marker_2, source | item_1_title..item_2_title |
| `matn:finding:grid-2x2` | title, item_1..item_4, source | item_1_title..item_4_title |
| `matn:finding:timeline` | title, item_1..item_4, source | item_1_title..item_4_title |
| `matn:finding:single-hero` | title, item_1, source | item_1_title, kpi_value_1, kpi_label_1, quote, attribution |
| `matn:implications:cards-3` | title, item_1..item_3, source | item_1_title..item_3_title |
| `matn:implications:two-split` | title, item_1..item_2, marker_1..marker_2, source | item_1_title..item_2_title |
| `matn:implications:single-hero` | title, item_1, source | item_1_title, kpi_value_1, kpi_label_1, quote, attribution |
| `matn:limitations:numbered` | title, item_1..item_4, marker_1..marker_4, source | |
| `matn:closing:takeaways` | title, item_1..item_3, decisions_title, decisions, source | item_1_title..item_3_title |

The machine-readable copy of both tables is `LAYOUTS` in `matn_deck/templates.py`; a test keeps them in sync, and
another keeps `design/variants.json` covering exactly these layouts.

## 4. How the renderer uses the contract

1. **Variant choice.** Candidates are the layouts of the slide type whose `valid` rule in `design/variants.json`
   accepts the content (item or value count, and data rules: `timeline` needs ordered years or steps, `two-col` a
   comparison with leads, `pictogram` and `progress` their number rules, `takeaways` at least one decision). §5 scores
   them.
2. **Fill by name.** Each named placeholder gets its value; placeholders the content does not use are removed from
   the slide, so no empty prompt text is left.
3. **Measure.** Text is measured with the real font files against the placeholder's real box (size, insets, font
   and size inherited from layout and master). On overflow the next candidate variant is tried; when none fits, the
   slide's items (or appendix lines, or KPI values) are split over two slides with the same title plus "(1/2)",
   "(2/2)", recursively. A fact is never cut. A title or single item that still overflows is reported, not cut.
   Cards are drawn only for filled slots, so no card or slot is ever left empty (the 2b split-implications bug).
4. **KPI values.** The value is copied as written; its unit is a second run at half the value size. When the
   values of a slide do not fit one line at the candidate's type-scale size, all of them step down together to 85%,
   70% or 55% of it.
5. **Item lead.** "Lead: rest" with a lead of at most 40 characters puts the lead in `item_N_title` and the rest in
   `item_N` when the layout has the title slot; otherwise the full text goes in `item_N`.

## 5. Generate-and-score (Step 2c)

- **Content area.** The `body` placeholder of `matn:limitations:default` defines it; the source chip sits in the band
  below it. Dividers use the safe zone in the template's `theme.json` (`divider.safe`).
- **Candidates.** (valid variants) x (type-scale steps L, M, S in `design/scoring.json`) x (anchor: top or
  centered). Content titles use one size for the whole deck: the largest of `title_sizes` at which every title fits.
- **Geometry.** Slots are recomputed for the actual item count from the variant's recipe (rows, columns, 2x2 grid,
  bento, single); each slot stacks its parts at their measured heights (real font files). No PowerPoint export.
- **Hard constraints** (candidate rejected): text overflow; collision; out of the content area or safe zone;
  contrast below 4.5 (3.0 for large text and graphics) from the theme colors; body text under 16 pt or a content
  title under 28 pt; an empty slot or card; no visual element on a content slide (the evidence rule: a KPI value,
  chart, pictogram, progress bar, cards, timeline or quote block); a chart under 55% of the content area.
- **Soft scores** (0-1, weights in `design/scoring.json`): fill (target band; card area counts at half weight),
  balance, vertical distribution, hierarchy (title/body >= 1.5, KPI value/label >= 3), density, deck variety (the
  previous content slide's variant scores 0).
- **Choice.** Highest total; candidates within `tie_margin` of it are a tie, broken by variant order (data-specific
  variants first), then step, then anchor. When none passes, the slide splits; when it cannot split, the least-bad
  candidate is kept and its violations are reported (`HARD_VIOLATION:` warnings).
- **Typography.** Titles longer than 30 characters override a theme's `cap="all"`; title line breaks are balanced by
  measured width with no single-word last line.
- **Charts.** `design/chart_rules.json`: the type follows the data shape, the key point (the cited number, else the
  maximum) takes the accent and one callout, the rest is muted; direct labels, no gridlines, no legend for one series.
- **Records.** Every slide's candidates and scores are in `RenderReport.scores` (the gallery QA writes them to
  `out/gallery/<template>/scores.json`).
