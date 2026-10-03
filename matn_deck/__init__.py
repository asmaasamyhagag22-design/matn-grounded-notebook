"""Deck renderer: DeckPlan + facts + tables -> editable .pptx through a gallery template (docs/design/)."""

from .template_renderer import (
    DeckOverflowError,
    DeckRenderError,
    Overflow,
    RenderReport,
    TemplateInvalidError,
    build_presentation,
    render,
)
from .templates import default_template_id, gallery, validate_template

__all__ = [
    "DeckOverflowError",
    "DeckRenderError",
    "Overflow",
    "RenderReport",
    "TemplateInvalidError",
    "build_presentation",
    "default_template_id",
    "gallery",
    "render",
    "validate_template",
]
