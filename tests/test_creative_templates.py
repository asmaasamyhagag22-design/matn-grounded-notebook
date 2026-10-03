"""Creative-family color, spec and deterministic-background behavior."""
from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from design.creative.backgrounds import content_zone_variance, render_background
from design.creative.spec import CreativeSpec
from matn_deck.color import (contrast_ratio, derive_roles, oklch_to_srgb, rgb_from_hex, srgb_to_oklch)


def sample_spec(**changes):
    data = {
        "id": "sample", "name_ar": "عينة", "name_en": "Sample", "mood": "Calm", "recommended_audience": "Leaders",
        "family": "creative", "mode": "dark", "seed_colors": {"primary": "#123B66", "accent": "#D6A84B"},
        "fonts": {"title": "Bahnschrift", "body": "Segoe UI"},
        "background": {"generator": "aurora", "parameters": {"grain": 0.5}, "fixed_seed": 7},
        "card_style": {"fill_alpha": 0.16, "corner_radius_pt": 14,
                       "shadow": {"enabled": True, "alpha": 0.16, "blur_pt": 12, "distance_pt": 2}},
        "divider_style": {"type": "gradient", "secondary": "#087E8B", "thin_rules": False},
        "motif": {"type": "aurora", "placement": "edges", "opacity": 0.12}, "pattern": False,
    }
    data.update(changes)
    return data


def test_oklch_round_trip_and_known_wcag_pairs():
    for value in ("000000", "FFFFFF", "0057B8", "D6A84B", "F4EBDD"):
        rgb = rgb_from_hex(value)
        assert oklch_to_srgb(srgb_to_oklch(rgb)) == pytest.approx(rgb, abs=2e-6)
    assert contrast_ratio(rgb_from_hex("000000"), rgb_from_hex("FFFFFF")) == pytest.approx(21)
    assert contrast_ratio(rgb_from_hex("777777"), rgb_from_hex("FFFFFF")) == pytest.approx(4.478, abs=0.002)


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_derived_roles_meet_contrast_targets(mode):
    roles = {name: rgb_from_hex(value) for name, value in derive_roles("#075985", "#D6A84B", mode).items()}
    for role in ("on_surface", "muted", "primary"):
        assert contrast_ratio(roles[role], roles["surface"]) >= 4.5
    assert contrast_ratio(roles["accent"], roles["surface"]) >= 3
    assert contrast_ratio(roles["on_divider"], roles["divider_background"]) >= 4.5


def test_spec_rejects_nonstandard_font_and_missing_seed_role():
    bad_font = sample_spec(fonts={"title": "Comic Sans MS", "body": "Segoe UI"})
    with pytest.raises(ValidationError, match="FONT_NOT_STANDARD"):
        CreativeSpec.model_validate(bad_font)
    missing = sample_spec()
    del missing["seed_colors"]["accent"]
    with pytest.raises(ValidationError, match="accent"):
        CreativeSpec.model_validate(missing)


@pytest.mark.parametrize("kind", ["aurora", "paper", "mashrabiya"])
def test_backgrounds_are_deterministic_and_keep_the_content_zone_calm(kind):
    data = sample_spec(mode="light" if kind != "aurora" else "dark")
    data["background"] = {"generator": kind, "parameters": {}, "fixed_seed": 91}
    data["motif"] = {"type": "lotus" if kind == "paper" else "mashrabiya" if kind == "mashrabiya" else "aurora",
                     "placement": "corners" if kind == "paper" else "side_band" if kind == "mashrabiya" else "edges",
                     "opacity": 0.12}
    spec = CreativeSpec.model_validate(data)
    first, second = render_background(spec, (320, 180)), render_background(spec, (320, 180))
    assert hashlib.sha256(first.tobytes()).digest() == hashlib.sha256(second.tobytes()).digest()
    assert content_zone_variance(first) < 12
