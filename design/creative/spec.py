"""Validated input format for creative templates."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from matn_deck.templates import is_standard_font


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SeedColors(StrictModel):
    primary: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    accent: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    surface: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")


class Fonts(StrictModel):
    title: str
    body: str

    @field_validator("title", "body")
    @classmethod
    def standard_windows_font(cls, value: str) -> str:
        if not is_standard_font(value) or not any(value.lower().startswith(f) for f in
                                                  ("georgia", "cambria", "bahnschrift", "segoe ui")):
            raise ValueError(f"FONT_NOT_STANDARD:{value}")
        return value


class Background(StrictModel):
    generator: Literal["aurora", "paper", "mashrabiya"]
    parameters: dict[str, float | int | str] = Field(default_factory=dict)
    fixed_seed: int


class Shadow(StrictModel):
    enabled: bool = False
    alpha: float = Field(default=0.16, ge=0, le=1)
    blur_pt: float = Field(default=10, ge=0, le=40)
    distance_pt: float = Field(default=2, ge=0, le=20)


class CardStyle(StrictModel):
    fill_alpha: float = Field(ge=0, le=1)
    corner_radius_pt: float = Field(ge=0, le=40)
    shadow: Shadow = Field(default_factory=Shadow)


class DividerStyle(StrictModel):
    type: Literal["color_block", "gradient", "outline_number"]
    secondary: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    thin_rules: bool = False


class Motif(StrictModel):
    type: Literal["none", "lotus", "mashrabiya", "aurora"]
    placement: Literal["corners", "edges", "side_band", "divider"]
    opacity: float = Field(ge=0, le=0.35)


class CreativeSpec(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name_ar: str = Field(min_length=1)
    name_en: str = Field(min_length=1)
    mood: str = Field(min_length=1)
    recommended_audience: str = Field(min_length=1)
    family: Literal["creative"]
    mode: Literal["light", "dark"]
    seed_colors: SeedColors
    fonts: Fonts
    background: Background
    card_style: CardStyle
    divider_style: DividerStyle
    motif: Motif
    pattern: bool
    layout_bias: tuple[str, ...] = ()  # favourite variant names (scoring.json layout_bias_bonus), overnight Part 4


def load_spec(path: Path) -> CreativeSpec:
    return CreativeSpec.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))
