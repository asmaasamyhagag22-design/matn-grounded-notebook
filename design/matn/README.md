# Original Matn templates

`python -m design.matn.generate` builds three editable source templates under
`design/templates/matn/`. `palettes.json` is their design source. The generator
authors a new OOXML package, theme, master and contract layouts directly. It does
not copy an Office theme, download assets or call PowerPoint, a model or a CDN.

| Template | Direction | Fonts |
| --- | --- | --- |
| Ministry Light | Off-white, ink and deep teal; formal hierarchy | Carlito |
| Midnight | Dark navy, warm white, mint and muted gold | Noto Sans Display + Carlito |
| Editorial | Warm paper, dark ink and brick red; serif headlines | Noto Serif + Carlito |

All declared fonts come from the pinned OFL packages in `design/fonts/fonts.json`.
The 28 renderer contract layouts provide a title, section, sourced bullets,
comparison, disagreement, figure/caption, table and closing/sources. The renderer
chooses and splits layouts against measured text, then checks LibreOffice's PDF.
Factual content, chart restrictions and citation gates remain deck-v2's policy.

Use `matn_deck.product_templates.product_template(id)` and `fonts="template"`.
The legacy gallery stays unchanged because its provenance and test contract are
different. During output, the Matn theme also replaces the library-generated
notes theme and embedded chart workbook theme. Notes retain citations; figures
and native charts retain their evidence-based alt text.

`DELIVERY_READY` on these templates means all local two-renderer gates and the
original-template/OFL package checks passed. Windows PowerPoint rendering remains
**UNMEASURED**. Install the same OFL fonts on Windows before comparing the PPTX
with the delivered PDF. No PowerPoint inspection is claimed.
