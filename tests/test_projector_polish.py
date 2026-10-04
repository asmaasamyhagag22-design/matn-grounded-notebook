"""Overnight Part 4 polish: projector-safe dark roles, art strength, layout bias, and the stricter dark QA minimums."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

from design.creative.backgrounds import decor_zone_metrics, render_background
from design.creative.generate import PROJECTOR_LARGE_TARGET, PROJECTOR_TEXT_TARGET, specs
from design.creative.spec import CreativeSpec
from matn_deck.color import contrast_ratio, derive_roles, rgb_from_hex
from matn_deck.specimen import specimen_inputs
from matn_deck.template_renderer import build_presentation, load_scoring
from matn_deck.templates import GALLERY_DIR, LAYOUTS

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = {name.rsplit(":", 1)[-1] for name in LAYOUTS}


def test_projector_targets_lift_every_text_role_and_leave_the_default_unchanged():
    default = derive_roles("#2056A8", "#D6A84B", "dark", "#07182E", 0.16)
    assert default == derive_roles("#2056A8", "#D6A84B", "dark", "#07182E", 0.16, text_target=4.5, large_target=3.0)
    roles = derive_roles("#2056A8", "#D6A84B", "dark", "#07182E", 0.16, text_target=PROJECTOR_TEXT_TARGET,
                         large_target=PROJECTOR_LARGE_TARGET)
    surface = rgb_from_hex(roles["surface"])
    for role in ("on_surface", "muted", "primary", "accent"):
        assert contrast_ratio(rgb_from_hex(roles[role]), surface) >= PROJECTOR_TEXT_TARGET, role
    assert contrast_ratio(rgb_from_hex(roles["focus"]), surface) >= PROJECTOR_LARGE_TARGET
    assert roles["surface"] == default["surface"]  # the background colour (and so the art) is not changed


def test_dark_creative_gallery_templates_carry_projector_roles():
    for template_id, (_, spec) in specs().items():
        if spec.mode != "dark":
            continue
        roles = json.loads((GALLERY_DIR / template_id / "theme.json").read_text(encoding="utf-8"))["roles"]
        surface = rgb_from_hex(roles["surface"])
        for role in ("on_surface", "muted", "accent"):
            assert contrast_ratio(rgb_from_hex(roles[role]), surface) >= PROJECTOR_TEXT_TARGET, (template_id, role)


def test_dark_qa_minimums_are_stricter_than_wcag():
    sys.path.insert(0, str(ROOT / "design" / "templates" / "src"))
    import qa  # noqa: PLC0415

    assert (qa.PROJECTOR_BODY_MIN, qa.PROJECTOR_LARGE_MIN) == (7.0, 4.5)
    assert qa.PROJECTOR_BODY_MIN > qa.BODY_MIN and qa.PROJECTOR_LARGE_MIN > qa.LARGE_MIN


def _with_parameter(spec: CreativeSpec, key: str, value: float) -> CreativeSpec:
    data = spec.model_dump()
    data["background"]["parameters"][key] = value
    return CreativeSpec.model_validate(data)


def test_art_strength_parameters_default_to_the_old_art_and_strengthen_only_the_edges():
    found = specs()
    for template_id, key in (("nile-night", "glow_strength"), ("papyrus", "motif_weight")):
        spec = found[template_id][1]
        base = _with_parameter(spec, key, 1.0)
        data = base.model_dump()
        del data["background"]["parameters"][key]
        unset = CreativeSpec.model_validate(data)
        size = (640, 360)
        assert np.array_equal(np.asarray(render_background(unset, size)), np.asarray(render_background(base, size)))
        before = base.model_dump()
        before["motif"]["opacity"] = 0.22 if template_id == "papyrus" else before["motif"]["opacity"]  # 2d value
        weak = decor_zone_metrics(render_background(CreativeSpec.model_validate(before), size))
        strong = decor_zone_metrics(render_background(spec, size))
        assert strong["edge_std"] > 1.5 * weak["edge_std"], (template_id, weak, strong)
        assert strong["calm"], (template_id, strong)


def test_layout_bias_names_real_variants_and_follows_the_families():
    expected = {"nile-night": {"hero-number", "single-hero"}, "papyrus": {"split-60-40", "single-hero"},
                "mashrabiya": {"bento", "grid-2x2"}, "modulo": {"cards-3", "two-col"}}
    for meta_path in sorted(GALLERY_DIR.glob("*/theme.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        bias = set(meta.get("layout_bias", []))
        assert bias <= VARIANTS, (meta["id"], bias - VARIANTS)
        family = next((f for f in expected if meta["id"] == f or meta["id"].startswith(f + "-")), None)
        if family is not None:
            assert bias == expected[family], meta["id"]
    assert 0 < load_scoring()["layout_bias_bonus"] < 0.05  # small: it decides close calls only


def test_layout_bias_prefers_its_variants_among_passing_candidates_and_records_unbiased_totals(tmp_path):
    plan, facts, tables = specimen_inputs()
    source = GALLERY_DIR / "integral-light"
    chosen = {}
    for bias in ([], ["timeline", "two-split", "single-hero", "split-60-40"]):
        folder = tmp_path / ("biased" if bias else "plain")
        shutil.copytree(source, folder)
        meta = json.loads((folder / "theme.json").read_text(encoding="utf-8"))
        meta["layout_bias"] = bias
        (folder / "theme.json").write_text(json.dumps(meta), encoding="utf-8")
        _, report = build_presentation(plan, facts, tables, folder / "template.pptx")
        chosen[bool(bias)] = report
        for entry in report.scores:
            assert not entry["chosen"]["hard"]  # a bias never picks a failing candidate
            assert entry["chosen"]["total"] == max((c["total"] for c in entry["candidates"]
                                                    if c["layout"] == entry["chosen"]["layout"]
                                                    and c["step"] == entry["chosen"]["step"]
                                                    and c["anchor"] == entry["chosen"]["anchor"]), default=None)
    favoured = ("timeline", "two-split", "single-hero", "split-60-40")
    count = {k: sum(name.rsplit(":", 1)[-1] in favoured for name in r.layouts) for k, r in chosen.items()}
    assert count[True] >= count[False]
