from __future__ import annotations

from collections import Counter
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator

from .base import VersionedContract
from .enums import BlockType, ExtractionRoute, Visibility
from .ids import make_block_id, make_section_id, make_table_id, validate_bbox


DocId = Annotated[str, Field(pattern=r"^sha256-[0-9a-f]{64}$")]
BBox = tuple[float, float, float, float]


class BlockStyle(VersionedContract):
    font_size_pt: Annotated[float, Field(gt=0)] | None
    is_bold: bool | None


class ExtractorInfo(VersionedContract):
    name: Annotated[str, Field(min_length=1)]
    version: Annotated[str, Field(min_length=1)]


class Block(VersionedContract):
    block_id: str
    doc_id: DocId
    page_index: Annotated[int, Field(ge=0)]
    page_label: str | None
    bbox: BBox
    block_type: BlockType
    text: str
    reading_order: Annotated[int, Field(ge=0)]
    style: BlockStyle
    extractor: ExtractorInfo
    route: ExtractionRoute
    visibility: Visibility

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        validate_bbox(self.bbox)
        expected = make_block_id(self.doc_id, self.page_index, self.bbox, self.text)
        if self.block_id != expected:
            raise ValueError("block_id does not match the deterministic identity inputs")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        block_id = make_block_id(
            str(values["doc_id"]),
            int(values["page_index"]),
            values["bbox"],  # type: ignore[arg-type]
            str(values["text"]),
        )
        return cls(block_id=block_id, **values)


class TableCell(VersionedContract):
    row: Annotated[int, Field(ge=0)]
    col: Annotated[int, Field(ge=0)]
    text: str
    bbox: BBox
    is_header: bool

    @model_validator(mode="after")
    def validate_coordinates(self) -> Self:
        validate_bbox(self.bbox)
        return self


class Table(VersionedContract):
    table_id: str
    doc_id: DocId
    page_index: Annotated[int, Field(ge=0)]
    bbox: BBox
    header_rows: tuple[Annotated[int, Field(ge=0)], ...]
    cells: tuple[TableCell, ...]

    @field_validator("header_rows", mode="before")
    @classmethod
    def normalize_header_rows(cls, value: object) -> tuple[int, ...]:
        return tuple(sorted(set(value)))  # type: ignore[arg-type]

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        validate_bbox(self.bbox)
        expected = make_table_id(self.doc_id, self.page_index, self.bbox)
        if self.table_id != expected:
            raise ValueError("table_id does not match the deterministic identity inputs")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        table_id = make_table_id(
            str(values["doc_id"]),
            int(values["page_index"]),
            values["bbox"],  # type: ignore[arg-type]
        )
        return cls(table_id=table_id, **values)


class PageRange(VersionedContract):
    first_page_index: Annotated[int, Field(ge=0)]
    last_page_index: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if self.first_page_index > self.last_page_index:
            raise ValueError("first_page_index must not exceed last_page_index")
        return self


class Section(VersionedContract):
    section_id: str
    doc_id: DocId
    title: Annotated[str, Field(min_length=1)]
    level: Annotated[int, Field(ge=1)]
    heading_path: Annotated[tuple[Annotated[str, Field(min_length=1)], ...], Field(min_length=1)]
    block_ids: Annotated[tuple[str, ...], Field(min_length=1)]
    page_range: PageRange

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        expected = make_section_id(self.doc_id, self.heading_path, self.block_ids[0])
        if self.section_id != expected:
            raise ValueError("section_id does not match the deterministic identity inputs")
        return self

    @classmethod
    def create(cls, **values: object) -> Self:
        block_ids = tuple(values["block_ids"])  # type: ignore[arg-type]
        if not block_ids:
            raise ValueError("a section needs at least one block_id")
        section_id = make_section_id(
            str(values["doc_id"]),
            values["heading_path"],  # type: ignore[arg-type]
            block_ids[0],
        )
        return cls(section_id=section_id, **{**values, "block_ids": block_ids})


class SectionCoverage(VersionedContract):
    missing_block_ids: tuple[str, ...]
    duplicated_block_ids: tuple[str, ...]


_COVERED_PROSE_TYPES = {
    BlockType.TEXT,
    BlockType.HEADING,
    BlockType.LIST_ITEM,
    BlockType.CAPTION,
    BlockType.FOOTNOTE,
}


def check_section_coverage(
    blocks: tuple[Block, ...],
    sections: tuple[Section, ...],
) -> SectionCoverage:
    required = {
        block.block_id
        for block in blocks
        if block.visibility is Visibility.VISIBLE and block.block_type in _COVERED_PROSE_TYPES
    }
    counts = Counter(
        block_id
        for section in sections
        for block_id in section.block_ids
        if block_id in required
    )
    return SectionCoverage(
        missing_block_ids=tuple(sorted(block_id for block_id in required if counts[block_id] == 0)),
        duplicated_block_ids=tuple(sorted(block_id for block_id in required if counts[block_id] > 1)),
    )
