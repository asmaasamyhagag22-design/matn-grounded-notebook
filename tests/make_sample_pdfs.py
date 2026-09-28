"""Create deterministic local PDFs used by the extraction tests."""

from __future__ import annotations

import argparse
import html
from pathlib import Path
from typing import Sequence

import pymupdf


KNOWN_PAGE_TEXT = (
    "MATN PAGE 1\nINTRODUCTION TOKEN ALPHA",
    "MATN PAGE 2\nSENSOR READING: 42 kg\nREFERENCE TOKEN BRAVO",
    "MATN PAGE 3\nCONCLUSION TOKEN CHARLIE",
)
IMAGE_ONLY_VISIBLE_TEXT = "IMAGE ONLY: 73 km"
ARABIC_TEXT = "مرحبا بالعالم"
MIXED_TEXT = "Matn 2026 - القياس 123 kg"
SYSTEM_ARABIC_FONT = Path(r"C:\Windows\Fonts\arial.ttf")
REPRESENTATIVE_PAGE_COUNT = 10


def _require_new_file(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite sample PDF: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)


def create_known_text_pdf(path: Path) -> None:
    _require_new_file(path)
    with pymupdf.open() as document:
        for page_text in KNOWN_PAGE_TEXT:
            page = document.new_page(width=595, height=842)
            page.insert_text((72, 96), page_text, fontsize=14)
        document.save(path)


def create_blank_pdf(path: Path) -> None:
    _require_new_file(path)
    with pymupdf.open() as document:
        document.new_page(width=595, height=842)
        document.save(path)


def create_image_only_pdf(path: Path) -> None:
    _require_new_file(path)
    with pymupdf.open() as source:
        page = source.new_page(width=595, height=842)
        page.insert_text((72, 110), IMAGE_ONLY_VISIBLE_TEXT, fontsize=24)
        png_bytes = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes("png")

    with pymupdf.open() as image_pdf:
        page = image_pdf.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=png_bytes)
        image_pdf.save(path, deflate=True)


def create_password_pdf(path: Path) -> None:
    _require_new_file(path)
    with pymupdf.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((72, 96), "PROTECTED TEST PDF", fontsize=14)
        document.save(
            path,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw="owner-secret",
            user_pw="user-secret",
        )


def _insert_header_footer(page: pymupdf.Page, pdf_page: int) -> None:
    page.insert_text((36, 28), "MATN SYNTHETIC FIXTURE", fontsize=8)
    page.insert_text((36, 820), f"FIXTURE FOOTER - PDF PAGE {pdf_page}", fontsize=8)


def _insert_arabic_html(page: pymupdf.Page, text: str, rect: pymupdf.Rect) -> None:
    if not SYSTEM_ARABIC_FONT.is_file():
        raise FileNotFoundError(
            "Windows Arial font is required for the visually shaped Arabic fixture"
        )
    archive = pymupdf.Archive(str(SYSTEM_ARABIC_FONT.parent))
    css = (
        "@font-face {font-family: MatnArabic; src: url(arial.ttf);} "
        "* {font-family: MatnArabic; font-size: 18pt; direction: rtl; "
        "text-align: right;}"
    )
    spare_height, scale = page.insert_htmlbox(
        rect, html.escape(text), css=css, archive=archive
    )
    if spare_height < 0 or scale < 1:
        raise RuntimeError("Arabic fixture text did not fit its target rectangle")


def _raster_text_image(text: str) -> bytes:
    with pymupdf.open() as source:
        page = source.new_page(width=480, height=180)
        page.insert_text((35, 90), text, fontsize=24)
        return page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False).tobytes("png")


def create_representative_pdf(path: Path) -> None:
    """Create a deterministic, visually reviewable ten-page PDF fixture."""
    _require_new_file(path)
    with pymupdf.open() as document:
        page = document.new_page(width=595, height=842)
        _insert_header_footer(page, 1)
        page.insert_text((60, 90), "MATN EXTRACTION BASELINE", fontsize=22)
        page.insert_text(
            (72, 145),
            "- First list item\n- Second list item\nMEASUREMENT: 42 kg",
            fontsize=13,
        )

        page = document.new_page(width=595, height=842)
        _insert_header_footer(page, 2)
        _insert_arabic_html(page, ARABIC_TEXT, pymupdf.Rect(60, 90, 535, 200))

        page = document.new_page(width=595, height=842)
        _insert_header_footer(page, 3)
        _insert_arabic_html(page, MIXED_TEXT, pymupdf.Rect(60, 90, 535, 220))

        page = document.new_page(width=595, height=842)
        _insert_header_footer(page, 4)
        page.insert_textbox(
            pymupdf.Rect(50, 90, 275, 400),
            "LEFT COLUMN A\nAlpha 11 m\nLEFT COLUMN END A",
            fontsize=12,
        )
        page.insert_textbox(
            pymupdf.Rect(320, 90, 545, 400),
            "RIGHT COLUMN A\nBravo 22 s\nRIGHT COLUMN END A",
            fontsize=12,
        )

        page = document.new_page(width=595, height=842)
        _insert_header_footer(page, 5)
        # Insert right first so raw content-stream order differs from visual order.
        page.insert_textbox(
            pymupdf.Rect(320, 90, 545, 400),
            "RIGHT COLUMN B\nDelta 44 s\nRIGHT COLUMN END B",
            fontsize=12,
        )
        page.insert_textbox(
            pymupdf.Rect(50, 90, 275, 400),
            "LEFT COLUMN B\nCharlie 33 m\nLEFT COLUMN END B",
            fontsize=12,
        )

        page = document.new_page(width=595, height=842)
        _insert_header_footer(page, 6)
        page.insert_text((60, 80), "SIMPLE TABLE", fontsize=18)
        x_positions = (60, 260, 460)
        y_positions = (110, 150, 190, 230)
        for x in x_positions:
            page.draw_line((x, y_positions[0]), (x, y_positions[-1]))
        for y in y_positions:
            page.draw_line((x_positions[0], y), (x_positions[-1], y))
        table_rows = (
            ("Item", "Value"),
            ("Mass", "7 kg"),
            ("Length", "9 m"),
        )
        for row_index, row in enumerate(table_rows):
            baseline = 137 + row_index * 40
            page.insert_text((72, baseline), row[0], fontsize=11)
            page.insert_text((272, baseline), row[1], fontsize=11)

        page = document.new_page(width=595, height=842)
        _insert_header_footer(page, 7)
        page.insert_text((72, 120), "ROTATED PAGE TOKEN - 270 degrees", fontsize=16)
        page.set_rotation(90)

        document.new_page(width=595, height=842)  # Deliberately truly blank page 8.

        image_bytes = _raster_text_image("IMAGE ONLY FIXTURE - 73 km")
        page = document.new_page(width=595, height=842)
        page.insert_image(pymupdf.Rect(55, 100, 540, 282), stream=image_bytes)

        page = document.new_page(width=595, height=842)
        _insert_header_footer(page, 10)
        page.insert_text((60, 90), "MIXED NATIVE TEXT - 88 kg", fontsize=16)
        page.insert_image(
            pymupdf.Rect(60, 150, 420, 285),
            stream=_raster_text_image("IMAGE REGION - 99 m"),
        )

        document.set_page_labels(
            [{"startpage": 0, "prefix": "M-", "style": "D", "firstpagenum": 1}]
        )
        document.set_metadata(
            {
                "title": "Matn deterministic synthetic extraction fixture",
                "author": "Matn tests",
                "creator": "PyMuPDF",
                "producer": "PyMuPDF",
            }
        )
        if document.page_count != REPRESENTATIVE_PAGE_COUNT:
            raise RuntimeError("Representative fixture page count changed unexpectedly")
        document.save(path, garbage=4, deflate=True)


def create_samples(
    output_dir: Path,
    include_password: bool = False,
    include_representative: bool = False,
) -> dict[str, Path]:
    samples = {
        "known_text": output_dir / "known_text.pdf",
        "blank": output_dir / "blank.pdf",
        "image_only": output_dir / "image_only.pdf",
    }
    create_known_text_pdf(samples["known_text"])
    create_blank_pdf(samples["blank"])
    create_image_only_pdf(samples["image_only"])
    if include_password:
        samples["password"] = output_dir / "password.pdf"
        create_password_pdf(samples["password"])
    if include_representative:
        samples["representative"] = output_dir / "representative.pdf"
        create_representative_pdf(samples["representative"])
    return samples


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--include-password", action="store_true")
    parser.add_argument("--include-representative", action="store_true")
    args = parser.parse_args(argv)
    samples = create_samples(
        args.out,
        include_password=args.include_password,
        include_representative=args.include_representative,
    )
    for name, path in samples.items():
        print(f"{name}: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
