from __future__ import annotations

from enum import Enum


class BlockType(str, Enum):
    TEXT = "text"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    TABLE = "table"
    FIGURE = "figure"
    CAPTION = "caption"
    HEADER = "header"
    FOOTER = "footer"
    FOOTNOTE = "footnote"


class ExtractionRoute(str, Enum):
    TEXT_LAYER = "text_layer"
    OCR = "ocr"


class Visibility(str, Enum):
    VISIBLE = "visible"
    HIDDEN_IMAGE = "hidden_image"
    HIDDEN_VECTOR = "hidden_vector"
