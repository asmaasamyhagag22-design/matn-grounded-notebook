"""read_document on generated PDFs: block types, reading order, contract Blocks, flags (fail loud)."""
from __future__ import annotations

from matn_contracts.enums import BlockType, Visibility
from matn_reading.read import read_document, words_out
from matn_reading.triage import Route

from .pdf_fixtures import write_pdf

PAGE = b"""BT /F2 18 Tf 72 720 Td (Economic outlook) Tj ET
BT /F1 10 Tf 72 690 Td (Growth reached 3.3 percent in 2021 and is projected) Tj ET
BT /F1 10 Tf 72 678 Td (to slow in the coming fiscal year as support fades.) Tj ET
BT /F1 10 Tf 72 640 Td (Figure 2: Real GDP growth, percent) Tj ET
BT /F1 10 Tf 72 610 Td (- Inflation stayed near 5.6 percent.) Tj ET
BT /F1 7 Tf 72 80 Td (1 Staff estimates based on official data.) Tj ET
"""

IMAGE = (b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 "
         b"/Length 1 >>\nstream\n\x80\nendstream")


def test_block_types_order_and_contract_blocks(tmp_path):
    reading = read_document(write_pdf(tmp_path / "page.pdf", PAGE))
    page = reading.pages[0]
    assert page.route is Route.DIGITAL_HEALTHY and page.reasons
    kinds = [(b.block_type, b.layout.text[:16]) for b in page.blocks]
    assert kinds == [("heading", "Economic outlook"), ("text", "Growth reached 3"), ("caption", "Figure 2: Real G"),
                     ("list_item", "- Inflation stay"), ("footnote", "1 Staff estimate")]
    contracts = [b.contract for b in page.blocks]
    assert [c.reading_order for c in contracts] == list(range(5))
    assert all(c.visibility is Visibility.VISIBLE for c in contracts)
    assert contracts[0].block_type is BlockType.HEADING and contracts[0].doc_id == reading.doc_id
    assert not any(flagged for _, flagged in words_out(page))


def test_an_image_only_page_is_routed_to_ocr_and_flagged(tmp_path):
    content = b"q 612 0 0 792 0 0 cm /Im1 Do Q\nBT /F1 10 Tf 72 40 Td (scan) Tj ET\n"
    path = write_pdf(tmp_path / "scan.pdf", content, extra_resources=b"/XObject << /Im1 7 0 R >> ",
                     extra_objects=(IMAGE,))
    page = read_document(path).pages[0]
    assert page.route is Route.SCANNED
    assert page.flags[0]["kind"] == "page_route"
    assert all(flagged for _, flagged in words_out(page))
