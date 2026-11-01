"""Figure crops and image safety for decks (ADR-0025).

- `crop_figure`: a reader-detected figure region cut from the original PDF by PDFium, unaltered (no recolour, no
  redraw, no reading of numbers off the image), saved as PNG within the size caps. Only uploaded documents.
- `safe_png`: any external raster is decoded and re-encoded to PNG within the same caps; SVG and anything that is not
  a decodable raster is rejected. Web images are never placed in research decks (cite/link only); this guard exists
  for any future path that receives image bytes.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image

from .catalog import Figure

MAX_SIDE_PX = 2400
MAX_BYTES = 4 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000  # decompression-bomb guard for external rasters
RENDER_DPI = 200


class ImageRejected(ValueError):
    pass


def _encode(image: Image.Image) -> bytes:
    """PNG bytes within MAX_SIDE_PX and MAX_BYTES; downscales (never crops) until both caps hold."""
    image = image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
    while True:
        if max(image.size) > MAX_SIDE_PX:
            ratio = MAX_SIDE_PX / max(image.size)
            image = image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
                                 Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        data = buffer.getvalue()
        if len(data) <= MAX_BYTES:
            return data
        image = image.resize((max(1, image.width * 3 // 4), max(1, image.height * 3 // 4)), Image.Resampling.LANCZOS)


def safe_png(data: bytes, *, content_type: str = "") -> bytes:
    """Re-encode an external image to capped PNG; reject SVG and undecodable or oversized input."""
    head = data[:512].lstrip().lower()
    if "svg" in content_type.lower() or head.startswith((b"<?xml", b"<svg", b"<!doctype svg")) or b"<svg" in head:
        raise ImageRejected("IMAGE_SVG_REJECTED")
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ("PNG", "JPEG", "GIF", "BMP", "WEBP", "TIFF"):
                raise ImageRejected(f"IMAGE_FORMAT_REJECTED:{image.format}")
            image.seek(0)
            image.load()
            return _encode(image.copy())
    except (Image.DecompressionBombError, Image.UnidentifiedImageError, OSError) as exc:
        raise ImageRejected(f"IMAGE_UNREADABLE:{type(exc).__name__}") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous


def crop_figure(figure: Figure, out_dir: Path) -> Path:
    """The figure region of its page, rendered from the original PDF and saved as `<id>-<hash>.png`."""
    import pypdfium2 as pdfium
    from matn_research.reader import PDF_LOCK
    if figure.rights != "uploaded-document" or not figure.pdf:
        raise ImageRejected(f"FIGURE_NOT_FROM_UPLOADED_DOCUMENT:{figure.id}")
    with PDF_LOCK:
        document = pdfium.PdfDocument(figure.pdf)
        try:
            page = document[figure.page_index]
            left, top, right, bottom = page.get_cropbox()
            scale = RENDER_DPI / 72
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            x0, y0, x1, y1 = figure.bbox
            box = (round((x0 - left) * scale), round(y0 * scale), round((x1 - left) * scale), round(y1 * scale))
            crop = image.crop(box)
            bitmap.close()
            page.close()
        finally:
            document.close()
    data = _encode(crop)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{figure.id}-{hashlib.sha256(data).hexdigest()[:12]}.png"
    path.write_bytes(data)
    return path
