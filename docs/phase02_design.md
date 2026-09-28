# Phase 02 design: document structure and source-scoped selection

## Scope

Phase 02 consumes paired Phase 01 raw and structured runs for the same source
and page set. It builds a local, versioned evidence store, detects structural
candidates without an LLM, applies optional human corrections, and produces
page- or section-scoped selections. It does not summarize.

## Store layout and identity

`document-store.json` contains:

- document identity: SHA-256, byte size, safe basename, and PDF page count;
- index identity: deterministic builder ID plus both extraction run IDs,
  extractor versions/settings, and the Phase 02 builder version;
- page records with `pdf_page`, optional PDF `page_label`, human-only
  `printed_page`, relative raw/structured text references, chunks, warnings, and
  content-risk flags;
- heading candidates, sections, conservative header/footer candidates, and
  store warnings.

Derived evidence is copied into `text/raw/` and `text/structured/`. The original
PDF is read to verify its SHA-256 and inspect bookmarks, but it is never copied
or changed. No absolute local path is stored.

Chunk IDs hash the document identity, builder version, source type, PDF page,
offsets, and exact chunk text. A chunk never crosses a PDF-page boundary. Each
chunk retains exact structured text and start/end offsets. `layout_block` is not
claimed to be a linguistically complete paragraph. Raw text remains separate
evidence; there is no automatic raw/structured fallback.

## Structural evidence order

1. PDF outline/bookmarks from PyMuPDF.
2. Structured Markdown headings.
3. Font/layout signals only when a targeted rule is implemented.
4. Explicit manual correction.

Heading candidates retain original and normalized text, semantic/Markdown
level evidence, page and chunk/offset anchors, source methods, warnings, and a
`proposed`, `confirmed`, or `rejected` status. Evidence labels are categorical:
`outline_and_heading_agree`, `heading_only`, `conflicting_evidence`,
`manual_confirmed`, and `manual_rejected`. There is no invented confidence
score.

Numbered titles determine semantic depth (`2` → level 1, `2.1` → level 2),
which protects the index from observed Markdown-depth changes. Abstract,
References, Acknowledgment, and Appendix are named structural items. Other
Markdown headings remain candidates until reviewed; this is important for code
blocks and table cells that PyMuPDF4LLM can style as headings.

## Section boundaries and hierarchy

A section begins at its heading chunk. Its exclusive end is the next active
heading at the same or a higher semantic level. Child subsections remain inside
their parent section, while each child has its own independently selectable
range. Confirmed header-only chunks remain in the canonical store but do not
inflate section page spans or enter section selections.

“First two sections” is intentionally not accepted as a selector. The CLI lists
explicit IDs, levels, page spans, and statuses so the caller must resolve
whether Abstract or subsections count.

## Header/footer policy

The detector looks only at the first/last three non-empty structured lines and
requires the same normalized line on at least three pages and at least half the
indexed page population. This emits candidates only. It does not delete source
evidence and does not use a paper-specific string.

A human may confirm or reject a candidate. Selection text can omit a confirmed
line, but keeps `original_text`, a transformation record, the excluded text, and
the reason. Insufficient evidence leaves content unchanged with a warning. A
body phrase repeated outside the edge window is not a candidate.

## Content-risk flags

Flags are review signals, not accuracy claims:

- `contains_picture_region`
- `contains_table`
- `complex_table_suspected`
- `equation_or_symbol_risk`
- `repeated_header_footer_candidate`
- `extraction_order_risk`
- `structured_raw_disagreement`
- `needs_human_review`

Selections aggregate their chunks' flags for later phases. Phase 02 never
chooses a fallback extractor automatically.

## Atomicity and privacy

The complete store is written to an owned hidden sibling staging directory and
published by same-volume rename. An existing output is never replaced. A build
failure publishes no final store. Selection output uses a sibling temporary
file and atomic replacement, also refusing to overwrite an existing path.

PDF content is never logged by default. The list command prints only structural
metadata. Real PDFs, reviewed expectations/corrections, renders, generated
stores, and selections remain under ignored paths.

