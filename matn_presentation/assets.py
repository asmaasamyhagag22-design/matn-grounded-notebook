from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pymupdf as fitz


FIGURE_2_PAGE = 3
FIGURE_2_CROP_POINTS = [305.0, 315.0, 551.0, 592.0]


def render_figure_2(pdf_path: Path, output_path: Path) -> dict[str, Any]:
    """Render the verified Figure 2 region directly from physical PDF page 3."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf_path) as document:
        if document.page_count < FIGURE_2_PAGE:
            raise ValueError("SOURCE_PDF_DOES_NOT_CONTAIN_PAGE_3")
        page = document[FIGURE_2_PAGE - 1]
        clip = fitz.Rect(*FIGURE_2_CROP_POINTS)
        if not page.rect.contains(clip):
            raise ValueError("FIGURE_2_CROP_OUTSIDE_PAGE")
        pixmap = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip, alpha=False)
        pixmap.save(output_path)
    provenance = {
        "asset_id": "figure-2-page-3",
        "source_pdf_page": FIGURE_2_PAGE,
        "crop_pdf_points": FIGURE_2_CROP_POINTS,
        "method": "PyMuPDF direct clip; no OCR or reconstructed figure text",
        "caption_claim_ids": ["src-src-037", "src-src-038", "src-src-039"],
    }
    output_path.with_suffix(".provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return provenance
