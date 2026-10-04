from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.site.build_assets import build_assets


def _referenced_images(inventory: dict) -> list[str]:
    images = [template["cover"] for template in inventory["templates"]]
    images += [path for deck in inventory["decks"] for key in ("grid", "viewer") for path in deck[key]]
    images += [path for step in inventory["timeline"] for path in step["images"]]
    return images


@pytest.fixture(scope="module")
def built_assets(tmp_path_factory):
    output = tmp_path_factory.mktemp("demo-site-assets")
    return output, build_assets(output)


def test_demo_site_assets_exist_are_uncropped_16_9_and_include_downloads(built_assets):
    output, inventory = built_assets
    assert len(inventory["templates"]) == 16
    assert len(inventory["decks"]) == 9
    assert all(len(step["images"]) >= 2 for step in inventory["timeline"])
    for relative in _referenced_images(inventory):
        path = output / relative
        assert path.is_file(), relative
        with Image.open(path) as image:
            assert abs(image.width / image.height - 16 / 9) / (16 / 9) <= 0.01
    for deck in inventory["decks"]:
        assert (output / deck["pptx"]).is_file()
        assert (output / deck["pdf"]).is_file()


def test_templates_without_demo_decks_are_kept_as_preview_only(built_assets):
    output, inventory = built_assets
    preview_only = [template for template in inventory["templates"] if template["primary_deck_id"] is None]
    assert len(preview_only) == 9
    assert all((output / template["cover"]).is_file() for template in preview_only)
