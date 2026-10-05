"""Step 4c page preprocessing: 300 DPI render, deskew, light denoise; every step recorded and switchable."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from matn_reading.ocr.preprocess import PreprocessConfig, deskew_angle, preprocess


def _text_page(width: int = 1200, height: int = 1500) -> Image.Image:
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    for row in range(30):
        y = 80 + row * 44
        for col in range(14):
            draw.rectangle((90 + col * 75, y, 90 + col * 75 + 55, y + 18), fill=20)
    return image


def test_deskew_recovers_a_known_rotation():
    page = _text_page().rotate(1.3, resample=Image.Resampling.BICUBIC, fillcolor=255)
    assert abs(deskew_angle(page) + 1.3) <= 0.15


def test_upright_page_needs_no_rotation():
    assert abs(deskew_angle(_text_page())) <= 0.1


def test_every_step_is_recorded_and_can_be_switched_off():
    page = _text_page().rotate(-0.8, resample=Image.Resampling.BICUBIC, fillcolor=255)
    out, record = preprocess(page, PreprocessConfig())
    assert [step["step"] for step in record["steps"]] == ["deskew", "denoise"]
    assert all(step["applied"] for step in record["steps"])
    assert abs(record["rotation_deg"] - 0.8) <= 0.15
    assert out.size == page.size

    off, record_off = preprocess(page, PreprocessConfig(deskew=False, denoise=False))
    assert [step["applied"] for step in record_off["steps"]] == [False, False]
    assert record_off["rotation_deg"] == 0.0
    assert np.array_equal(np.asarray(off), np.asarray(page.convert("L")))


def test_denoise_removes_isolated_specks_but_keeps_a_decimal_point():
    image = Image.new("L", (200, 100), 255)
    draw = ImageDraw.Draw(image)
    draw.ellipse((100, 60, 106, 66), fill=0)          # a 300-DPI decimal point is about 5-7 px
    pixels = np.asarray(image).copy()
    pixels[10, 10] = pixels[30, 150] = 0               # single-pixel sensor specks
    out, _ = preprocess(Image.fromarray(pixels), PreprocessConfig(deskew=False))
    arr = np.asarray(out)
    assert arr[10, 10] > 128 and arr[30, 150] > 128
    assert arr[63, 103] < 128
