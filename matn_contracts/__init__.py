"""Strict, standalone data contracts for the Matn pipeline."""

from .domain import (
    Block,
    BlockStyle,
    ExtractorInfo,
    PageRange,
    Section,
    SectionCoverage,
    Table,
    TableCell,
    check_section_coverage,
)

__all__ = [
    "Block",
    "BlockStyle",
    "ExtractorInfo",
    "PageRange",
    "Section",
    "SectionCoverage",
    "Table",
    "TableCell",
    "check_section_coverage",
]
