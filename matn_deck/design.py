"""Load design/tokens.json and design/layouts.json and turn layout slots into boxes (EMU)."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

DESIGN_DIR = Path(__file__).resolve().parents[1] / "design"


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Design:
    tokens: dict[str, Any]
    layouts: dict[str, Any]

    def color(self, token: str) -> str:
        return self.tokens["color"][token]

    def role(self, name: str) -> dict[str, Any]:
        return self.tokens["type"][name]

    def label(self, key: str, **values: object) -> str:
        return self.layouts["labels"][key].format(**values)

    def archetype(self, slide_type: str) -> dict[str, Any]:
        return self.layouts["archetypes"][slide_type]

    def resolve_box(self, slot: dict[str, Any], cell: dict[str, Any] | None = None, *, rtl: bool = False) -> Box:
        """Grid slot -> box. Columns count from the reading-start edge, so RTL is a pure mirror."""
        slide_w = self.tokens["slide"]["width_emu"]
        if slot.get("bleed"):
            return Box(0, 0, slide_w, self.tokens["slide"]["height_emu"])
        grid = self.tokens["grid"]
        columns, gutter = grid["columns"], grid["gutter_emu"]
        content_w = slide_w - grid["margin_left_emu"] - grid["margin_right_emu"]
        col_w = (content_w - (columns - 1) * gutter) // columns
        col = slot["col"] + (cell["col"] if cell else 0)
        span = slot.get("span") or ((cell["span"] - slot["col"]) if cell else columns - col)
        x = grid["margin_left_emu"] + col * (col_w + gutter)
        w = slot.get("width_emu") or span * col_w + (span - 1) * gutter
        inset = slot.get("inset", 0)
        x, w = x + inset, w - 2 * inset
        if rtl:
            x = slide_w - x - w
        return Box(x, slot["top"] + (cell["top"] if cell else 0), w, slot["height"])


@lru_cache(maxsize=4)
def load_design(design_dir: Path = DESIGN_DIR) -> Design:
    tokens = json.loads((design_dir / "tokens.json").read_text(encoding="utf-8"))
    layouts = json.loads((design_dir / "layouts.json").read_text(encoding="utf-8"))
    return Design(tokens=tokens, layouts=layouts)


def contrast_ratio(color_a: str, color_b: str) -> float:
    """WCAG 2.x contrast ratio of two RRGGBB colors."""

    def luminance(color: str) -> float:
        channels = [int(color[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(color_a), luminance(color_b)), reverse=True)
    return (high + 0.05) / (low + 0.05)
