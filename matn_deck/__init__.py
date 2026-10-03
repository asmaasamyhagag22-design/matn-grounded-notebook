"""Deck renderer: DeckPlan + facts + tables -> editable .pptx in the Matn design system (docs/design/brief.md)."""

from .design import Box, Design, contrast_ratio, load_design
from .render import DeckOverflowError, DeckRenderError, Overflow, RenderReport, build_presentation, render

__all__ = [
    "Box",
    "DeckOverflowError",
    "DeckRenderError",
    "Design",
    "Overflow",
    "RenderReport",
    "build_presentation",
    "contrast_ratio",
    "load_design",
    "render",
]
