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
from .regions import RULES as CLOSEOUT_RULES


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
    noise = estimate_noise(out) if config.denoise else 0.0
    filtered = config.denoise and noise >= CLOSEOUT_RULES["noise_threshold"]
    if filtered:
        out = edge_preserving(out)
    record["steps"].append({"step": "denoise", "applied": config.denoise, "filtered": filtered,
                            "noise": round(noise, 4), "threshold": CLOSEOUT_RULES["noise_threshold"],
                            "filter": "light-bilateral-3x3" if filtered else None})
    return out, record


def estimate_noise(image: Image.Image) -> float:
    """RMS residual on flat-neighbor pixels; text edges are excluded. Includes isolated sensor impulses."""
    pixels = np.asarray(image, dtype=np.float32)
    pad = np.pad(pixels, 1, mode="edge")
    neighbors = [pad[dy:dy+pixels.shape[0], dx:dx+pixels.shape[1]] for dy in range(3) for dx in range(3)
                 if (dy, dx) != (1, 1)]
    lo = np.minimum.reduce(neighbors); hi = np.maximum.reduce(neighbors)
    flat = hi-lo < CLOSEOUT_RULES["noise_flat_neighbor_range"]
    residual = pixels - sum(neighbors)/8
    return float(np.sqrt(np.mean(residual[flat]**2))) if flat.any() else 0.0


def edge_preserving(image: Image.Image) -> Image.Image:
    """Small bilateral window; isolated one-pixel outliers repaired separately, connected punctuation retained."""
    pixels = np.asarray(image, dtype=np.float32)
    pad = np.pad(pixels, 1, mode="edge")
    total = pixels.copy(); weight = np.ones_like(pixels)
    lo = np.full_like(pixels, 255); hi = np.zeros_like(pixels)
    sigma = CLOSEOUT_RULES["bilateral_range_sigma"]
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            if dx == dy == 0: continue
            neighbor = pad[1+dy:1+dy+pixels.shape[0], 1+dx:1+dx+pixels.shape[1]]
            lo = np.minimum(lo, neighbor); hi = np.maximum(hi, neighbor)
            w = np.exp(-(neighbor-pixels)**2 / (2*sigma*sigma) - (dx*dx+dy*dy)/2)
            total += w*neighbor; weight += w
    out = total / weight
    isolated = ((hi-lo) < 10) & (np.abs(pixels-(hi+lo)/2) > 100)
    out[isolated] = (hi[isolated]+lo[isolated])/2
    return Image.fromarray(np.clip(np.rint(out), 0, 255).astype(np.uint8))
