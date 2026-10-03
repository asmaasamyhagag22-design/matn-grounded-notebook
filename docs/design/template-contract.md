# Template contract (v1, Step 2b)

A Matn template is a `.pptx` whose **slide layouts** follow the names below. The renderer picks a layout by name and
fills its placeholders by name; it never draws shapes, sets colors or chooses fonts. Everything visual (backgrounds,
master shapes, colors, fonts, the rounded "p. N" chip) lives in the template. Values are still copied from facts and
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

The machine-readable copy of this table is `LAYOUTS` in `matn_deck/templates.py`; a test keeps the two in sync.

## 4. How the renderer uses the contract

1. **Variant order.** Candidates are the layouts of the slide type that can hold the content (enough `item_N` or
   `kpi_value_N` slots). The preferred variant comes first, deterministically from the content: finding with 2 items
   → `two-col`, 3 items → `cards-3`, otherwise `split-60-40`; KPI with 2 values → `big-number`, otherwise `cards`.
   The other candidates follow in §3 order.
2. **Fill by name.** Each named placeholder gets its value; placeholders the content does not use are removed from
   the slide, so no empty prompt text is left.
3. **Measure.** Text is measured with the real font files against the placeholder's real box (size, insets, font
   and size inherited from layout and master). On overflow the next candidate variant is tried; when none fits, the
   slide's items (or appendix lines, or KPI values) are split over two slides with the same title plus "(1/2)",
   "(2/2)", recursively. A fact is never cut. A title or single item that still overflows is reported, not cut.
   A card layout whose decorated cards would stay empty is tried only after every other candidate.
4. **KPI values.** The value is copied as written; its unit is a second run at half the value size. When the
   values of a slide do not fit one line at the template's size, all of them step down together to 85%, 70% or 55%
   of it (the template sets the maximum; code never goes above it).
5. **Item lead.** "Lead: rest" with a lead of at most 40 characters puts the lead in `item_N_title` and the rest in
   `item_N` when the layout has the title slot; otherwise the full text goes in `item_N`.
