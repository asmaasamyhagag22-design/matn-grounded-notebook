"""Variant geometry (design/variants.json): slot recipes shared by the template builder and the renderer.

The builder places each layout's default placeholders with `default_layout`; the renderer recomputes the slots for
the actual item count with `slot_rects` and stacks measured text inside them, so no slot or card is ever left empty.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

from .scoring import EMU_PER_PT, Rect

VARIANTS_PATH = Path(__file__).resolve().parents[1] / "design" / "variants.json"
STEMS = ("item_title", "item", "kpi_value", "kpi_label", "marker")
BLOCKS = ("bar", "pictogram", "dot")


@lru_cache(maxsize=2)
def load_variants(path: Path = VARIANTS_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def placeholder_name(stem: str, n: int) -> str:
    return f"item_{n}_title" if stem == "item_title" else f"{stem}_{n}"


def sub_rect(area: Rect, frac: list[float]) -> Rect:
    x, y, w, h = frac
    return Rect(area.x + x * area.w, area.y + y * area.h, w * area.w, h * area.h)


def slot_rects(recipe: str, region: Rect, n: int, gap: float) -> list[Rect]:
    """Slot (card) rectangles for `n` items inside `region`, `gap` EMU apart."""
    if recipe == "single" or n == 1 and recipe in ("rows", "columns"):
        return [region]
    if recipe == "rows":
        h = (region.h - (n - 1) * gap) / n
        return [Rect(region.x, region.y + k * (h + gap), region.w, h) for k in range(n)]
    if recipe == "columns":
        w = (region.w - (n - 1) * gap) / n
        return [Rect(region.x + k * (w + gap), region.y, w, region.h) for k in range(n)]
    if recipe == "grid":
        w, h = (region.w - gap) / 2, (region.h - gap) / 2
        return [Rect(region.x + (k % 2) * (w + gap), region.y + (k // 2) * (h + gap), w, h) for k in range(n)]
    if recipe == "bento":
        big_w = (0.58 if n < 4 else 0.5) * region.w
        rest_x, rest_w = region.x + big_w + gap, region.w - big_w - gap
        big = Rect(region.x, region.y, big_w, region.h)
        if n == 2:
            return [big, Rect(rest_x, region.y, rest_w, region.h)]
        half_h = (region.h - gap) / 2
        top = Rect(rest_x, region.y, rest_w, half_h)
        if n == 3:
            return [big, top, Rect(rest_x, region.y + half_h + gap, rest_w, half_h)]
        quarter_w = (rest_w - gap) / 2
        low_y = region.y + half_h + gap
        return [big, top, Rect(rest_x, low_y, quarter_w, half_h),
                Rect(rest_x + quarter_w + gap, low_y, quarter_w, half_h)]
    raise ValueError(f"UNKNOWN_SLOT_RECIPE:{recipe}")


def pad_edges(rect: Rect, card: Rect, pad: float) -> Rect:
    """`rect` padded only on the edges it shares with its card, so stacked placeholders are not double-padded."""
    near = EMU_PER_PT
    left = pad if abs(rect.x - card.x) < near else 0.0
    top = pad if abs(rect.y - card.y) < near else 0.0
    right = pad if abs(rect.right - card.right) < near else 0.0
    bottom = pad if abs(rect.bottom - card.bottom) < near else 0.0
    return Rect(rect.x + left, rect.y + top, rect.w - left - right, rect.h - top - bottom)


def pad_emu(spec: dict) -> float:
    g = load_variants()["geometry"]
    return (g["row_pad_pt"] if spec.get("pad") == "row" else g["card_pad_pt"]) * EMU_PER_PT


def gap_emu(spec: dict) -> float:
    g = load_variants()["geometry"]
    recipe = spec.get("slots", {}).get("recipe")
    return (g["row_gap_pt"] if recipe == "rows" and spec.get("pad") == "row" else g["gap_pt"]) * EMU_PER_PT


def has_inner_pad(spec: dict) -> bool:
    return bool(spec.get("cards") or spec.get("pad"))


_DEFAULT_WEIGHT = {"item_title": 1.0, "item": 2.4, "kpi_value": 1.8, "kpi_label": 1.0, "dot": 0.4, "bar": 0.35,
                   "pictogram": 0.9}


def default_layout(name: str, area: Rect) -> list[tuple[str, str, Rect]]:
    """(placeholder name, style, rect) for the builder's default geometry at the layout's maximum slot count.
    Stacked parts share the slot height by fixed weights; native blocks (bar, pictogram, dot) keep their space."""
    spec = load_variants()["variants"][name]
    g = load_variants()["geometry"]
    out: list[tuple[str, str, Rect]] = []
    roles = spec.get("roles", {})
    for ph, frac in spec.get("fixed", {}).items():
        rect = sub_rect(area, frac)
        card = next((sub_rect(area, c) for c in spec.get("fixed_cards", []) if sub_rect(area, c).contains(rect, 1)),
                    None)
        if card is not None:
            rect = pad_edges(rect, card, pad_emu(spec))
        out.append((ph, ph, rect))
    panel = spec.get("hero_panel")
    if panel:
        inner = sub_rect(area, panel["region"]).inset(pad_emu(spec))
        value, label = panel["number"]
        out += [(value, "hero", Rect(inner.x, inner.y, inner.w, inner.h * 0.62)),
                (label, "kpi_label", Rect(inner.x, inner.y + inner.h * 0.64, inner.w, inner.h * 0.36))]
        quote, attribution = panel["quote"]
        out += [(quote, "quote", Rect(inner.x, inner.y, inner.w, inner.h * 0.78)),
                (attribution, "attribution", Rect(inner.x, inner.y + inner.h * 0.8, inner.w, inner.h * 0.2))]
    slots = spec.get("slots")
    if not slots:
        return out
    region = sub_rect(area, slots["region"])
    for n, slot in enumerate(slot_rects(slots["recipe"], region, slots["max"], gap_emu(spec)), start=1):
        inner = slot.inset(pad_emu(spec)) if has_inner_pad(spec) else slot
        if slots.get("arrange") == "side":
            split = slots["split"]
            left_w = g["marker_pt"] * EMU_PER_PT if split == "marker" else inner.w * split
            columns = [(slots["left"], Rect(inner.x, inner.y, left_w, inner.h)),
                       (slots["right"], Rect(inner.x + left_w + g["gap_pt"] * EMU_PER_PT / 2, inner.y,
                                             inner.w - left_w - g["gap_pt"] * EMU_PER_PT / 2, inner.h))]
        else:
            columns = [(slots["stack"], inner)]
        for parts, rect in columns:
            total = sum(_DEFAULT_WEIGHT.get(p, 1.0) for p in parts)
            y = rect.y
            for part in parts:
                h = rect.h * _DEFAULT_WEIGHT.get(part, 1.0) / total
                if part == "marker":
                    side = min(rect.w, g["marker_pt"] * EMU_PER_PT)
                    out.append((placeholder_name(part, n), "marker", Rect(rect.x, rect.y, side, side)))
                elif part not in BLOCKS:
                    role = (spec.get("first_role", {}) if n == 1 else {}).get(part) or roles.get(part, part)
                    out.append((placeholder_name(part, n), role, Rect(rect.x, y, rect.w, h)))
                y += h
    return out
