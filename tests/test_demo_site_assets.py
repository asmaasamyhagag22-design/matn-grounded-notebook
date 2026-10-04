from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from app.site import build_assets as assets_module
from app.site.build_assets import build_assets, fit_16_9, missing_inputs


def _referenced_images(inventory: dict) -> list[str]:
    images = [template["cover"] for template in inventory["templates"]]
    images += [path for deck in inventory["decks"] for key in ("grid", "viewer") for path in deck[key]]
    images += [path for step in inventory["timeline"] for path in step["images"]]
    return images


@pytest.fixture(scope="module")
def built_assets(tmp_path_factory):
    missing = missing_inputs()
    if missing:  # out/ and output/ are git-ignored local caches; a clean checkout has neither
        pytest.skip(f"local demo cache absent ({len(missing)} inputs missing, first: {missing[0]}); "
                    "build it with run_demo_site.ps1")
    output = tmp_path_factory.mktemp("demo-site-assets")
    return output, build_assets(output)


def test_missing_inputs_names_the_absent_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(assets_module, "MANIFEST", tmp_path / "absent" / "manifest.json")
    assert str(tmp_path / "absent" / "manifest.json") in missing_inputs()


def test_fit_16_9_pads_without_cropping_a_generated_image(tmp_path):
    source = tmp_path / "tall.png"
    Image.new("RGB", (300, 600), (200, 30, 30)).save(source)
    target = tmp_path / "out.jpg"
    fit_16_9(source, target, 320)
    with Image.open(target) as image:
        assert image.size == (320, 180)
        assert image.getpixel((160, 90))[0] > 150  # source pixels in the middle
        assert image.getpixel((5, 90))[0] < 252 and image.getpixel((5, 90))[1] > 200  # padding at the side


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
