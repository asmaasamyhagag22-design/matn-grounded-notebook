"""Page images for OCR: render at 300 DPI with pypdfium2, then deskew, then a light denoise.

Every step is recorded (and can be switched off for the ablations in the Step 4c report). Deskew uses the projection
profile: the page is rotated over a range of small angles and the angle whose row profile is sharpest wins (text lines
become thin dark bands with clean white gaps). Denoise is a 3x3 median filter: it removes isolated sensor specks but
keeps anything at least two pixels across, so a 300-DPI decimal point (about 5-7 px) survives.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from PIL import Image, ImageFilter

RENDER_DPI = 300
DESKEW_MAX_DEG = 4.0
DESKEW_COARSE_STEP = 0.25
DESKEW_FINE_STEP = 0.02
DESKEW_WORK_WIDTH = 800       # the angle search runs on a downscaled copy; the result is applied to the full image
DENOISE_MEDIAN_SIZE = 3


@dataclass(frozen=True)
class PreprocessConfig:
    deskew: bool = True
    denoise: bool = True


def render_page_image(pdf_path, page_index: int, dpi: int = RENDER_DPI) -> Image.Image:
    """Grayscale image of the page's CropBox at ``dpi``."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return pdf[page_index].render(scale=dpi / 72).to_pil().convert("L")
    finally:
        pdf.close()


def _ink(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    scale = DESKEW_WORK_WIDTH / max(gray.width, 1)
    small = gray.resize((DESKEW_WORK_WIDTH, max(1, round(gray.height * scale))), Image.Resampling.BILINEAR)
    pixels = np.asarray(small, dtype=np.float32)
    dark = pixels < 0.6 * float(np.median(pixels))     # relative to the paper, so lamp falloff does not matter
    return Image.fromarray((dark * 255).astype(np.uint8))


def _sharpness(ink: Image.Image, angle: float) -> float:
    rows = np.asarray(ink.rotate(angle, resample=Image.Resampling.NEAREST, fillcolor=0), dtype=np.float32).sum(axis=1)
    return float(np.square(np.diff(rows)).sum())


def deskew_angle(image: Image.Image) -> float:
    """The rotation (degrees, PIL ``rotate`` convention) that makes the text lines horizontal."""
    ink = _ink(image)
    if not np.asarray(ink).any():
        return 0.0
    coarse = np.arange(-DESKEW_MAX_DEG, DESKEW_MAX_DEG + 1e-9, DESKEW_COARSE_STEP)
    best = max(coarse, key=lambda a: _sharpness(ink, float(a)))
    fine = np.arange(best - DESKEW_COARSE_STEP, best + DESKEW_COARSE_STEP + 1e-9, DESKEW_FINE_STEP)
    angle = float(max(fine, key=lambda a: _sharpness(ink, float(a))))
    return round(angle, 2) + 0.0


def preprocess(image: Image.Image, config: PreprocessConfig = PreprocessConfig()) -> tuple[Image.Image, dict]:
    """Return the image reader 1 sees and the record of what was done to it."""
    out = image.convert("L")
    record: dict = {"config": asdict(config), "steps": [], "rotation_deg": 0.0, "size": list(out.size)}
    angle = deskew_angle(out) if config.deskew else 0.0
    if config.deskew and angle:
        out = out.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=255)
    record["rotation_deg"] = angle
    record["steps"].append({"step": "deskew", "applied": config.deskew, "angle_deg": angle})
    if config.denoise:
        out = out.filter(ImageFilter.MedianFilter(DENOISE_MEDIAN_SIZE))
    record["steps"].append({"step": "denoise", "applied": config.denoise,
                            "median_size": DENOISE_MEDIAN_SIZE if config.denoise else None})
    return out, record
