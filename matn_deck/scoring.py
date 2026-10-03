"""Verifiable layout metrics for generate-and-score (Step 2c; inspired by AeSlides and SlideGen).

A candidate slide is a list of `Element`s: measured text extents and native visuals, in EMU. Hard constraints reject
a candidate; soft scores are each 0-1 and combine with the weights in design/scoring.json. Everything here is pure
geometry, so it runs on hand-built rectangles in tests and on thousands of candidates per deck without PowerPoint.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np

SCORING_PATH = Path(__file__).resolve().parents[1] / "design" / "scoring.json"
EMU_PER_PT = 12700
_TOLERANCE = EMU_PER_PT  # 1 pt: touching edges and rounding are not collisions
VISUAL_KINDS = frozenset({"kpi", "hero", "chart", "icon", "bar", "card", "timeline", "quote"})  # the evidence rule
_OUTSIDE_CONTENT = frozenset({"title", "chip", "tracker"})  # placed by the template, not in the content area
GRAPHIC_KINDS = frozenset({"bar", "icon", "timeline", "marker_shape"})
SOFT_NAMES = ("fill", "balance", "vertical", "hierarchy", "density", "variety")


@lru_cache(maxsize=4)
def load_scoring(path: Path = SCORING_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h / 2

    def overlap(self, other: "Rect") -> tuple[float, float]:
        """Width and height of the intersection (0 when apart)."""
        return (max(0.0, min(self.right, other.right) - max(self.x, other.x)),
                max(0.0, min(self.bottom, other.bottom) - max(self.y, other.y)))

    def contains(self, other: "Rect", tolerance: float = _TOLERANCE) -> bool:
        return (other.x >= self.x - tolerance and other.y >= self.y - tolerance
                and other.right <= self.right + tolerance and other.bottom <= self.bottom + tolerance)

    def clip(self, other: "Rect") -> "Rect":
        x, y = max(self.x, other.x), max(self.y, other.y)
        return Rect(x, y, max(0.0, min(self.right, other.right) - x), max(0.0, min(self.bottom, other.bottom) - y))

    def inset(self, d: float) -> "Rect":
        return Rect(self.x + d, self.y + d, self.w - 2 * d, self.h - 2 * d)

    def as_list(self) -> list[int]:
        return [round(self.x), round(self.y), round(self.w), round(self.h)]


def bbox(rects: Iterable[Rect]) -> Rect:
    rects = list(rects)
    x, y = min(r.x for r in rects), min(r.y for r in rects)
    return Rect(x, y, max(r.right for r in rects) - x, max(r.bottom for r in rects) - y)


@dataclass(frozen=True)
class Element:
    """One thing on a candidate slide. Text elements carry their measured ink extent in `rect`."""
    name: str
    kind: str  # text, title, chip, tracker, card, kpi, hero, chart, quote, marker, icon, bar, timeline
    rect: Rect
    ink: float = 0.5  # visual weight per unit area (0-1), for balance
    role: str | None = None  # type-scale role, for the size minimums and hierarchy
    size_pt: float | None = None
    bold: bool = False
    container: bool = False  # cards hold other elements: no collision with them, not counted as fill
    contrast: float | None = None  # foreground/background ratio as the template's colors give it
    empty: bool = False
    overflow: bool = False


@dataclass(frozen=True)
class SlideContext:
    content_slide: bool  # subject to the evidence rule and the size minimums
    area: Rect  # the template's content area
    safe: Rect  # where content elements may go (the content area, or a divider's safe zone)
    slide: Rect  # the whole slide
    title_pt: float | None = None
    centered_hero: bool = False  # a single centered hero is exempt from the vertical-distribution score


@dataclass
class CandidateScore:
    hard: list[str]
    soft: dict[str, float]
    total: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.hard


# ---- hard constraints -------------------------------------------------------------------------------------------

def _large(e: Element) -> bool:
    return e.size_pt is not None and (e.size_pt >= 18 or (e.bold and e.size_pt >= 14))


def hard_violations(elements: list[Element], ctx: SlideContext, cfg: dict | None = None) -> list[str]:
    cfg = cfg or load_scoring()
    found: list[str] = []
    for e in elements:
        if e.overflow:
            found.append(f"OVERFLOW:{e.name}")
        if e.empty:
            found.append(f"EMPTY:{e.name}")
        bounds = ctx.slide if e.kind in _OUTSIDE_CONTENT else ctx.safe
        if not bounds.contains(e.rect):
            found.append(f"OUT_OF_BOUNDS:{e.name}")
        if e.contrast is not None:
            if e.kind in GRAPHIC_KINDS:
                minimum = cfg["contrast"]["graphics"]
            else:
                minimum = cfg["contrast"]["large" if _large(e) else "text"]
            if e.contrast < minimum:
                found.append(f"LOW_CONTRAST:{e.name}:{e.contrast:.2f}<{minimum}")
        if ctx.content_slide and e.size_pt is not None:
            if e.kind == "title" and e.size_pt < cfg["minimums"]["title_pt"]:
                found.append(f"TITLE_TOO_SMALL:{e.name}:{e.size_pt:g}")
            if e.role in cfg["body_roles"] and e.size_pt < cfg["minimums"]["body_pt"]:
                found.append(f"TEXT_TOO_SMALL:{e.name}:{e.size_pt:g}")
    found += [f"COLLISION:{a}:{b}" for a, b in collisions(elements)]
    if ctx.content_slide and not any(e.kind in VISUAL_KINDS and not e.empty for e in elements):
        found.append("NO_VISUAL")
    return found


def collisions(elements: list[Element]) -> list[tuple[str, str]]:
    """Pairs of non-container elements whose rectangles overlap by more than 1 pt both ways."""
    solid = [e for e in elements if not e.container]
    pairs = []
    for i, a in enumerate(solid):
        for b in solid[i + 1:]:
            w, h = a.rect.overlap(b.rect)
            if w > _TOLERANCE and h > _TOLERANCE:
                pairs.append((a.name, b.name))
    return pairs


# ---- soft scores ------------------------------------------------------------------------------------------------

def _content(elements: list[Element], containers: bool = False) -> list[Element]:
    return [e for e in elements if e.kind not in _OUTSIDE_CONTENT and (containers or not e.container)]


def _mask(rects: list[Rect], area: Rect, cells: tuple[int, int]) -> np.ndarray:
    nx, ny = cells
    mask = np.zeros((ny, nx), dtype=bool)
    for r in rects:
        # cells whose center lies inside r: center_i = x + (i + 0.5) * w / nx
        i0 = max(0, math.ceil((r.x - area.x) * nx / area.w - 0.5))
        i1 = min(nx, math.floor((r.right - area.x) * nx / area.w - 0.5) + 1)
        j0 = max(0, math.ceil((r.y - area.y) * ny / area.h - 0.5))
        j1 = min(ny, math.floor((r.bottom - area.y) * ny / area.h - 0.5) + 1)
        if i0 < i1 and j0 < j1:
            mask[j0:j1, i0:i1] = True
    return mask


def coverage(rects: list[Rect], area: Rect, cells: tuple[int, int] = (96, 54)) -> float:
    """Share of `area` covered by the union of `rects` (raster of cell centers, so overlaps count once)."""
    if area.area <= 0:
        return 0.0
    return float(_mask(rects, area, cells).mean())


def fill_ratio(elements: list[Element], area: Rect, card_weight: float = 0.5, cells: tuple[int, int] = (96, 54)
               ) -> float:
    """Occupied share of the content area: content ink counts fully, card area not covered by ink counts at
    `card_weight` (a card is a deliberate block, but a flat one)."""
    if area.area <= 0:
        return 0.0
    ink = _mask([e.rect for e in _content(elements)], area, cells)
    cards = _mask([e.rect for e in _content(elements, containers=True) if e.container], area, cells)
    return float((ink | cards).mean() - (1 - card_weight) * (cards & ~ink).mean())


def fill_score(ratio: float, cfg: dict) -> float:
    low, high = cfg["fill"]["band"]
    falloff = cfg["fill"]["falloff"]
    if ratio < low:
        return max(0.0, 1 - (low - ratio) / falloff)
    if ratio > high:
        return max(0.0, 1 - (ratio - high) / falloff)
    return 1.0


def balance_score(elements: list[Element], area: Rect, cfg: dict) -> float:
    """1 when the visual-weight centroid (area x ink) sits on the content-area center, 0 at `max_offset` away."""
    total = cx = cy = 0.0
    for e in _content(elements, containers=True):
        r = e.rect.clip(area)
        weight = r.area * (cfg["balance"]["card_ink"] if e.container else e.ink)
        x, y = r.center
        total += weight
        cx += weight * x
        cy += weight * y
    if total <= 0:
        return 0.0
    ax, ay = area.center
    offset = math.hypot((cx / total - ax) / area.w, (cy / total - ay) / area.h)
    return max(0.0, 1 - offset / cfg["balance"]["max_offset"])


def vertical_score(elements: list[Element], ctx: SlideContext, cfg: dict) -> float:
    """Content must reach the lower part of the content area, unless the slide is a single centered hero."""
    if ctx.centered_hero:
        return 1.0
    content = _content(elements, containers=True)
    if not content:
        return 0.0
    reach = (max(e.rect.bottom for e in content) - ctx.area.y) / ctx.area.h
    floor, full = cfg["vertical"]["floor"], cfg["vertical"]["reach"]
    return min(1.0, max(0.0, (reach - floor) / (full - floor)))


def hierarchy_score(elements: list[Element], ctx: SlideContext, cfg: dict) -> float:
    parts = []
    body = [e.size_pt for e in elements if e.role in cfg["body_roles"] and e.size_pt]
    if ctx.title_pt and body:
        parts.append(min(1.0, ctx.title_pt / max(body) / cfg["hierarchy"]["title_body"]) ** 2)
    values = [e.size_pt for e in elements if e.role in ("kpi_value", "hero", "bento_big", "progress_value")
              and e.size_pt]
    labels = [e.size_pt for e in elements if e.role == "kpi_label" and e.size_pt]
    if values and labels:
        parts.append(min(1.0, min(values) / max(labels) / cfg["hierarchy"]["kpi_value_label"]) ** 2)
    return sum(parts) / len(parts) if parts else 1.0


def density_score(elements: list[Element], area: Rect, cfg: dict) -> float:
    """SlideGen-style geometry-aware density: penalize empty grid cells (sparsity) and many small fragments or
    crowded cells (clutter)."""
    gx, gy = cfg["density"]["grid"]
    content = _content(elements)
    if not content:
        return 0.0
    counts = [[0] * gx for _ in range(gy)]
    for e in content:
        r = e.rect.clip(area)
        if r.area <= 0:
            continue
        for j in range(gy):
            cell_y = area.y + j * area.h / gy
            for i in range(gx):
                cell = Rect(area.x + i * area.w / gx, cell_y, area.w / gx, area.h / gy)
                w, h = r.overlap(cell)
                if w * h > 0.05 * cell.area:
                    counts[j][i] += 1
    cells = [c for row in counts for c in row]
    sparsity = sum(c == 0 for c in cells) / len(cells)
    small = sum(e.rect.area < cfg["density"]["small_fragment"] * area.area for e in content) / len(content)
    crowd = max(0, max(cells) - cfg["density"]["max_fragments_per_cell"]) / cfg["density"]["max_fragments_per_cell"]
    return max(0.0, min(1.0, 1 - 0.7 * sparsity - 0.4 * small - 0.4 * crowd))


def score(elements: list[Element], ctx: SlideContext, *, variety: float = 1.0, cfg: dict | None = None
          ) -> CandidateScore:
    cfg = cfg or load_scoring()
    ratio = fill_ratio(elements, ctx.area, cfg["fill"]["card_weight"])
    soft = {
        "fill": fill_score(ratio, cfg),
        "balance": balance_score(elements, ctx.area, cfg),
        "vertical": vertical_score(elements, ctx, cfg),
        "hierarchy": hierarchy_score(elements, ctx, cfg),
        "density": density_score(elements, ctx.area, cfg),
        "variety": variety,
    }
    weights = cfg["weights"]
    total = sum(weights[k] * soft[k] for k in SOFT_NAMES) / sum(weights[k] for k in SOFT_NAMES)
    result = CandidateScore(hard_violations(elements, ctx, cfg), {k: round(v, 4) for k, v in soft.items()},
                            round(total, 6))
    result.soft["fill_ratio"] = round(ratio, 4)
    return result
