"""Step 4a: synthetic scans are degraded deterministically from a per-page seed, and ground-truth boxes follow."""
from __future__ import annotations

import hashlib

import numpy as np
from PIL import Image, ImageDraw

from eval.reading.degrade import degrade, page_seed, rotate_bbox, sample_params


def _page() -> Image.Image:
    image = Image.new("L", (300, 400), 255)
    draw = ImageDraw.Draw(image)
    for row in range(5):
        draw.text((20, 40 + row * 60), f"Row {row}: GDP grew 3.{row}% in 2021", fill=0)
    return image


def _sha(image: Image.Image) -> str:
    return hashlib.sha256(image.tobytes()).hexdigest()


def test_page_seed_is_stable_and_distinct():
    assert page_seed("wb-eem-2021-12", 22) == page_seed("wb-eem-2021-12", 22)
    assert page_seed("wb-eem-2021-12", 22) != page_seed("wb-eem-2021-12", 23)


def test_degrade_is_deterministic_for_a_seed_and_differs_across_seeds():
    page = _page()
    a, params_a = degrade(page, 1234)
    b, params_b = degrade(page, 1234)
    c, _ = degrade(page, 99)
    assert params_a == params_b and _sha(a) == _sha(b)
    assert _sha(a) != _sha(c)
    assert a.size == page.size and a.mode == "L"


def test_degrade_parameters_stay_in_the_specified_ranges():
    for seed in range(40):
        params = sample_params(seed)
        assert 0.5 <= abs(params["rotation_deg"]) <= 2.0
        assert 0.3 <= params["blur_radius"] <= 1.2
        assert 2.0 <= params["noise_sigma"] <= 10.0
        assert 35 <= params["jpeg_quality"] <= 75
        assert 0.70 <= params["brightness_min"] < 1.0


def test_rotate_bbox_follows_the_pixels():
    image = Image.new("L", (600, 800), 255)
    ImageDraw.Draw(image).rectangle((400, 100, 420, 120), fill=0)
    angle = 2.0
    rotated = image.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=255)
    ys, xs = np.nonzero(np.asarray(rotated) < 128)
    x0, y0, x1, y1 = rotate_bbox((400, 100, 421, 121), angle, image.size)
    assert x0 - 2 <= xs.min() and xs.max() <= x1 + 2
    assert y0 - 2 <= ys.min() and ys.max() <= y1 + 2
    assert abs((x0 + x1) / 2 - xs.mean()) < 1.5 and abs((y0 + y1) / 2 - ys.mean()) < 1.5
