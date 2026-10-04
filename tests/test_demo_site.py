from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from PIL import Image

from app.site.build_assets import MANIFEST, OUTPUT
from app.site.build_site import build_site


@pytest.fixture(scope="module")
def site() -> tuple[Path, str, dict]:
    if not MANIFEST.is_file():
        pytest.skip("demo cache not built (out/demo/)")
    index = build_site()
    html = index.read_text(encoding="utf-8")
    match = re.search(r'<script id="site-data" type="application/json">(.*?)</script>', html, re.S)
    assert match
    return index, html, json.loads(match.group(1))


def _asset_paths(data: dict) -> set[str]:
    paths = {template["cover"] for template in data["templates"]}
    paths |= {image for step in data["timeline"] for image in step["images"]}
    for deck in data["decks"]:
        paths |= set(deck["grid"]) | set(deck["viewer"])
        paths |= {receipt["image"] for receipt in deck["receipts"]}
        paths |= {deck["pptx"], deck["pdf"]}
    return paths


def test_static_site_builds_and_embedded_json_parses(site):
    index, html, data = site
    assert index.is_file()
    assert len(data["templates"]) == 16
    assert len(data["documents"]) == 3
    assert len(data["decks"]) == 9
    assert "http://" not in html and "https://" not in html
    assert 'dir="rtl"' in html
    assert all(label in html for label in ("القصة", "المعرض", "العرض", "الإيصالات"))


def test_every_site_asset_exists_and_every_image_is_16_9(site):
    index, _, data = site
    for relative in _asset_paths(data):
        assert (index.parent / relative).is_file(), relative
    for relative in (path for path in _asset_paths(data) if path.lower().endswith((".jpg", ".png"))):
        with Image.open(index.parent / relative) as image:
            assert abs(image.width / image.height - 16 / 9) / (16 / 9) <= 0.01, relative


def test_index_and_assets_stay_under_sixty_megabytes(site):
    index, _, _ = site
    files = [index, *(path for path in (OUTPUT / "assets").rglob("*") if path.is_file())]
    assert sum(path.stat().st_size for path in files) < 60 * 1024 * 1024
