from __future__ import annotations

from enum import Enum, IntEnum


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
    HIDDEN_COLOR = "hidden_color"  # fill colour matches the rendered background under the glyph (white-on-white)


class FactKind(str, Enum):
    PURPOSE = "purpose"
    FINDING = "finding"
    TARGET = "target"
    RECOMMENDATION = "recommendation"
    CAVEAT = "caveat"
    DEFINITION = "definition"
    NUMBER = "number"


class Importance(IntEnum):
    SUPPORTING = 1
    IMPORTANT = 2
    HEADLINE = 3


class FactStatus(str, Enum):
    RAW = "raw"
    VERIFIED = "verified"
    REJECTED = "rejected"


class RejectReason(str, Enum):
    QUOTE_NOT_FOUND = "quote_not_found"
    INVALID_EVIDENCE_SPAN = "invalid_evidence_span"
    NUMBER_NOT_IN_EVIDENCE = "number_not_in_evidence"
    UNSUPPORTED_STATEMENT = "unsupported_statement"
    ATTRIBUTION_MISMATCH = "attribution_mismatch"
    HEDGE_MISMATCH = "hedge_mismatch"
    EVIDENCE_HIDDEN = "evidence_hidden"
    EVIDENCE_IN_FIGURE = "evidence_in_figure"
    SPELLED_NUMBER_MISMATCH = "spelled_number_mismatch"


class SentenceType(str, Enum):
    EXTRACTION = "extraction"
    INTERPRETATION = "interpretation"


class SlideType(str, Enum):
    TITLE = "title"
    EXECUTIVE_SUMMARY = "executive_summary"
    KPI = "kpi"
    FINDING = "finding"
    CHART = "chart"
    IMPLICATIONS = "implications"
    LIMITATIONS = "limitations"
    SOURCES = "sources"
    SECTION_DIVIDER = "section_divider"
    CLOSING = "closing"
    EVIDENCE_APPENDIX = "evidence_appendix"


class ChartType(str, Enum):
    BAR = "bar"
    COLUMN = "column"
    LINE = "line"
