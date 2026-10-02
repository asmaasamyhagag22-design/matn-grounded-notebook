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


class FactKind(str, Enum):
    PURPOSE = "purpose"
    SCOPE = "scope"
    DEFINITIONS = "definitions"
    REQUIREMENT = "requirement"
    RECOMMENDATION = "recommendation"
    FINDING = "finding"
    RISK = "risk"
    LIMITATION = "limitation"
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


class ChartType(str, Enum):
    BAR = "bar"
    COLUMN = "column"
    LINE = "line"
