# Synthetic PDF fixtures

`make_sample_pdfs.py` creates all PDFs at test/runtime; no PDF binary is stored
in Git. The representative fixture covers English text, visually shaped Arabic,
Arabic plus English plus digits, two two-column pages, a title and list, a ruled
table, repeated header/footer, page rotation, a truly blank page, an image-only
page, a mixed text/image page, page labels, and non-contiguous page selection.

Arabic is rendered with `C:\Windows\Fonts\arial.ttf`, supplied by the target
Windows installation. Arial is a Microsoft-provided proprietary system font. It
is read locally for fixture generation and is not copied, redistributed, or
committed to this repository. If the font is unavailable, the representative
fixture tests report a pytest skip instead of claiming Arabic verification.

The Arabic pages were rendered to PNG with Poppler and visually inspected. The
letters were joined and readable, not boxes or isolated glyphs. Raw PyMuPDF text
uses Arabic presentation forms for this generated fixture; tests validate UTF-8
decoding and NFKC equivalence. PyMuPDF4LLM returns base Arabic characters.
