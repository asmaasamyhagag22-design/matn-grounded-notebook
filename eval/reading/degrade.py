"""Deterministic scan degradation for the synthetic reading benchmark (Step 4a).

Every page gets a seed derived from (doc_id, page_index); the seed alone fixes every parameter, so the large images
never need to be in git: they are regenerated from the seed and checked against the recorded hash. Only Pillow and
numpy are used (both already pinned). Image hashes depend on the Pillow/numpy/libjpeg build, so the manifest records
their versions next to each hash.

Order of operations, like a real scanner: rotation (paper skew) -> uneven brightness (lamp falloff) -> blur (focus)
-> noise (sensor) -> JPEG (compression).
"""
from __future__ import annotations

import hashlib
import io
import math

import numpy as np
from PIL import Image, ImageFilter


def page_seed(doc_id: str, page_index: int) -> int:
    return int.from_bytes(hashlib.sha256(f"{doc_id}:{page_index}".encode()).digest()[:4], "big")


def sample_params(seed: int) -> dict:
    """Every degradation parameter, fixed by the seed."""
    rng = np.random.default_rng(seed)
    return {
        "seed": seed,
        "rotation_deg": round(float(rng.uniform(0.5, 2.0) * rng.choice([-1.0, 1.0])), 3),
        "brightness_min": round(float(rng.uniform(0.70, 0.95)), 3),
        "brightness_direction_deg": round(float(rng.uniform(0.0, 360.0)), 1),
        "blur_radius": round(float(rng.uniform(0.3, 1.2)), 3),
        "noise_sigma": round(float(rng.uniform(2.0, 10.0)), 2),
        "jpeg_quality": int(rng.integers(35, 76)),
    }


def degrade(image: Image.Image, seed: int) -> tuple[Image.Image, dict]:
    """Return (degraded grayscale image of the same size, the parameters used)."""
    params = sample_params(seed)
    gray = image.convert("L")
    rotated = gray.rotate(params["rotation_deg"], resample=Image.Resampling.BICUBIC, fillcolor=255)

    width, height = rotated.size
    theta = math.radians(params["brightness_direction_deg"])
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    ramp = (xs / max(width - 1, 1) - 0.5) * math.cos(theta) + (ys / max(height - 1, 1) - 0.5) * math.sin(theta)
    ramp = (ramp - ramp.min()) / max(float(ramp.max() - ramp.min()), 1e-6)
    gain = params["brightness_min"] + (1.0 - params["brightness_min"]) * ramp
    pixels = np.asarray(rotated, dtype=np.float32) * gain

    blurred = Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(params["blur_radius"]))
    noise = np.random.default_rng(seed + 1).normal(0.0, params["noise_sigma"], size=(height, width))
    noisy = np.clip(np.asarray(blurred, dtype=np.float32) + noise, 0, 255).astype(np.uint8)

    buffer = io.BytesIO()
    Image.fromarray(noisy).save(buffer, "JPEG", quality=params["jpeg_quality"])
    buffer.seek(0)
    with Image.open(buffer) as jpeg:
        return jpeg.convert("L"), params


def rotate_bbox(bbox: tuple[float, float, float, float], angle_deg: float,
                size: tuple[int, int]) -> tuple[float, float, float, float]:
    """Axis-aligned box around ``bbox`` after ``Image.rotate(angle_deg)`` (counter-clockwise, about the centre,
    same canvas size). Coordinates are image pixels, top-left origin."""
    cx, cy = size[0] / 2, size[1] / 2
    theta = math.radians(angle_deg)
    cos, sin = math.cos(theta), math.sin(theta)
    points = []
    for x, y in ((bbox[0], bbox[1]), (bbox[2], bbox[1]), (bbox[0], bbox[3]), (bbox[2], bbox[3])):
        dx, dy = x - cx, y - cy
        # counter-clockwise on screen (y down): x' = cx + dx cos + dy sin ; y' = cy - dx sin + dy cos
        points.append((cx + dx * cos + dy * sin, cy - dx * sin + dy * cos))
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)
