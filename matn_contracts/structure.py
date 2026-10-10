"""R-lite v1. Citation offsets are Unicode code points, exclusive at the end.

Number dispositions for verifiers: digital = exact digital reader text, not OCR
consensus; accepted = unflagged OCR reader verdict (not independently verified);
flagged = linked OCR uncertainty; flagged-unlinked = OCR text lacking a unique
reader record. Neither flagged disposition may be treated as verified.
digital-unlinked = digital Block numeric text without an exact source-word link;
coarse geometry only, no reader value or verification claim.
Separators are typed synthetic text, never evidence.
"""
from typing import Literal
from pydantic import Field, model_validator
from .base import VersionedContract
from .domain import Block, DocId
from .ids import validate_bbox
from .structure_ids import structure_id

VERSION='r-lite-1'

class BBoxRef(VersionedContract):
    coordinates: tuple[float,float,float,float]
    bbox_precision: Literal['char','word','line','region']
    frame: Literal['pdf_points','reader_points']='pdf_points'
    interpolated: bool=False
    @model_validator(mode='after')
    def valid(self):
        validate_bbox(self.coordinates)
        if self.interpolated and self.bbox_precision=='char': raise ValueError('interpolated char box')
        return self

class BlockSpan(VersionedContract):
    block_id: str
    start: int=Field(ge=0)
    end: int=Field(gt=0)
    boxes: tuple[BBoxRef,...]=()
    @model_validator(mode='after')
    def valid(self):
        if self.start>=self.end: raise ValueError('empty/inverted span')
        return self

class PrimarySpan(BlockSpan): pass
class RepeatedContextSpan(BlockSpan):
    primary_chunk_id: str

class OffsetSpan(VersionedContract):
    kind: Literal['primary','repeated_context','separator']
    start: int=Field(ge=0)
    end: int=Field(gt=0)
    block_id: str|None=None
    char_start: int|None=None
    char_end: int|None=None
    separator: Literal['\n\n','\t','\n']|None=None
    primary_chunk_id: str|None=None
    @model_validator(mode='after')
    def valid(self):
        if self.end<=self.start: raise ValueError('empty offset')
        if self.kind=='separator':
            if any(x is not None for x in (self.block_id,self.char_start,self.char_end,self.primary_chunk_id)): raise ValueError('separator has source')
            if self.separator is None or len(self.separator)!=self.end-self.start: raise ValueError('separator length')
        else:
            if self.block_id is None or self.char_start is None or self.char_end is None: raise ValueError('missing source')
            if self.char_start<0 or self.char_end-self.char_start!=self.end-self.start: raise ValueError('source length')
            if self.separator is not None: raise ValueError('sourced separator')
            if (self.kind=='repeated_context') != (self.primary_chunk_id is not None): raise ValueError('repeat target')
        return self

class SentenceSpan(VersionedContract):
    start: int=Field(ge=0)
    end: int=Field(gt=0)
    flags: tuple[str,...]=()
    @model_validator(mode='after')
    def valid(self):
        if self.start>=self.end: raise ValueError('empty sentence')
        return self

class NumberTokenRef(VersionedContract):
    reader_source: Literal['digital','ocr']
    status: Literal['digital','digital-unlinked','accepted','flagged','flagged-unlinked']
    text: str
    pdf_page_index: int=Field(ge=0)
    block_id: str
    start: int=Field(ge=0)
    end: int=Field(gt=0)
    bbox: BBoxRef
    reader_ref: str|None=None
    reader_status: str|None=None
    reader1: str|None=None
    reader2: str|None=None
    reader_bbox: BBoxRef|None=None
    reasons: tuple[str,...]=()
    chunk_start: int|None=None
    chunk_end: int|None=None
    @model_validator(mode='after')
    def valid(self):
        if self.start>=self.end: raise ValueError('empty number')
        if self.status=='digital-unlinked':
            if self.reader_source!='digital' or any(v is not None for v in (self.reader_ref,self.reader_status,self.reader1,self.reader2,self.reader_bbox)) or not self.reasons: raise ValueError('digital-unlinked has reader verdict or no reason')
        elif self.reader_source=='digital':
            if self.status!='digital' or self.bbox.bbox_precision not in ('char','word') or self.reader_ref is None: raise ValueError('digital disposition/geometry')
        elif self.status=='digital': raise ValueError('OCR digital disposition')
        elif self.status=='flagged-unlinked':
            if self.reader_ref is not None or self.reader_status is not None: raise ValueError('unlinked has reader verdict')
        elif self.reader_ref is None or self.reader_status is None or self.reader_bbox is None: raise ValueError('missing OCR reader provenance')
        if (self.chunk_start is None)!=(self.chunk_end is None): raise ValueError('partial chunk span')
        return self

class StructureIssue(VersionedContract):
    reason: str
    pdf_page_index: int|None=None
    block_id: str|None=None
    detail: str=''

class Element(VersionedContract):
    block: Block
    role: str
    citable: bool
    exclusion_reasons: tuple[str,...]=()
    flags: tuple[str,...]=()
    source_spans: tuple[BlockSpan,...]=()
    number_tokens: tuple[NumberTokenRef,...]=()
    reader_frame: str='pdf_points'
    bbox: BBoxRef
    @model_validator(mode='after')
    def valid(self):
        if self.citable==bool(self.exclusion_reasons): raise ValueError('exclusion disposition')
        for span in self.source_spans:
            if span.block_id!=self.block.block_id or span.end>len(self.block.text): raise ValueError('element span outside block')
        for token in self.number_tokens:
            if token.block_id!=self.block.block_id or token.end>len(self.block.text): raise ValueError('number outside block')
        return self

class PageGeometry(VersionedContract):
    pdf_page_index: int=Field(ge=0)
    page_label: str|None=None
    width: float=Field(gt=0)
    height: float=Field(gt=0)
    cropbox: BBoxRef
    rotation: int=0
    route: str

class Section(VersionedContract):
    section_id: str
    doc_id: DocId
    title: str
    parent_id: str|None=None
    child_ids: tuple[str,...]=()
    level: int=Field(ge=0)
    path: tuple[str,...]
    source: Literal['outline','layout_heading','page_window']
    heading_block_id: str|None=None
    block_ids: tuple[str,...]=()
    page_range: tuple[int,int]
    issues: tuple[StructureIssue,...]=()
    producer_version: str=VERSION
    @model_validator(mode='after')
    def valid(self):
        if self.section_id!=structure_id(self.doc_id,'s',self.producer_version,[self.source,list(self.path),self.heading_block_id]): raise ValueError('section identity')
        if self.child_ids and self.block_ids: raise ValueError('internal ownership')
        if self.page_range[0]>self.page_range[1]: raise ValueError('page range')
        return self

class TableCell(VersionedContract):
    row: int=Field(ge=0)
    col: int=Field(ge=0)
    row_span: int=Field(ge=1,default=1)
    col_span: int=Field(ge=1,default=1)
    text: str
    bbox: BBoxRef
    source_spans: tuple[BlockSpan,...]=()
    numeric_tokens: tuple[NumberTokenRef,...]=()
    is_header: bool=False

class Table(VersionedContract):
    table_id: str
    doc_id: DocId
    pdf_page_index: int=Field(ge=0)
    bbox: BBoxRef
    block_ids: tuple[str,...]
    structure: Literal['available','unavailable']
    unavailable_reason: str|None=None
    rows: int=Field(ge=0,default=0)
    cols: int=Field(ge=0,default=0)
    header_rows: tuple[int,...]=()
    cells: tuple[TableCell,...]=()
    issues: tuple[StructureIssue,...]=()
    producer_version: str=VERSION
    def identity_inputs(self):
        return self.model_dump(exclude={'table_id','schema_version'})
    @model_validator(mode='after')
    def valid(self):
        if self.structure=='unavailable':
            if not self.unavailable_reason or self.cells: raise ValueError('unavailable shape')
        elif self.unavailable_reason or not self.cells or not self.rows or not self.cols: raise ValueError('available shape')
        occupied=set();x0,y0,x1,y1=self.bbox.coordinates
        for c in self.cells:
            a,b,d,e=c.bbox.coordinates
            if a<x0-1e-6 or b<y0-1e-6 or d>x1+1e-6 or e>y1+1e-6: raise ValueError('cell outside region')
            if c.row+c.row_span>self.rows or c.col+c.col_span>self.cols: raise ValueError('cell outside grid')
            for r in range(c.row,c.row+c.row_span):
                for col in range(c.col,c.col+c.col_span):
                    if (r,col) in occupied: raise ValueError('duplicate cell')
                    occupied.add((r,col))
            if any(n.status=='flagged-unlinked' for n in c.numeric_tokens): raise ValueError('unlinked cell number')
        if any(r<0 or r>=self.rows for r in self.header_rows): raise ValueError('header outside grid')
        if self.table_id!=structure_id(self.doc_id,'t',self.producer_version,self.identity_inputs()): raise ValueError('table identity')
        return self
    @classmethod
    def create(cls,**data):
        data.setdefault('producer_version',VERSION)
        provisional=cls.model_construct(table_id='',**data)
        # Canonicalize nested models/defaults before hashing.
        inputs=provisional.identity_inputs()
        return cls(table_id=structure_id(data['doc_id'],'t',data['producer_version'],inputs),**data)

class Chunk(VersionedContract):
    chunk_id: str
    doc_id: DocId
    section_id: str
    kind: Literal['body','table','caption','footnote']
    text: str
    context_prefix: str
    offset_map: tuple[OffsetSpan,...]
    primary: tuple[PrimarySpan,...]
    repeated_context: tuple[RepeatedContextSpan,...]=()
    sentence_spans: tuple[SentenceSpan,...]=()
    numeric_tokens: tuple[NumberTokenRef,...]=()
    table_id: str|None=None
    row_range: tuple[int,int]|None=None
    prev_chunk_id: str|None=None
    next_chunk_id: str|None=None
    word_count: int=Field(ge=0)
    estimator: str='unicode-whitespace'
    estimator_version: str='1'
    flags: tuple[str,...]=()
    producer_version: str=VERSION
    @model_validator(mode='after')
    def valid(self):
        cursor=0
        for span in self.offset_map:
            if span.start!=cursor: raise ValueError('offset gap/overlap')
            cursor=span.end
        if cursor!=len(self.text): raise ValueError('offset length')
        if any(s.end>len(self.text) for s in self.sentence_spans): raise ValueError('sentence outside chunk')
        if self.word_count!=len(self.text.split()): raise ValueError('word count')
        material=[self.section_id,self.kind,self.text,[m.model_dump(exclude={'primary_chunk_id'}) for m in self.offset_map],self.table_id,self.row_range]
        if self.chunk_id!=structure_id(self.doc_id,'c',self.producer_version,material): raise ValueError('chunk identity')
        return self

class DocumentStructure(VersionedContract):
    doc_id: DocId
    title: str
    producer_versions: dict[str,str]
    reader_fingerprint: str
    coordinate_convention: str
    pages: tuple[PageGeometry,...]
    elements: tuple[Element,...]
    sections: tuple[Section,...]
    tables: tuple[Table,...]
    chunks: tuple[Chunk,...]
    excluded_blocks: dict[str,tuple[str,...]]
    issues: tuple[StructureIssue,...]=()
    @model_validator(mode='after')
    def valid(self):
        expected={e.block.block_id:e.exclusion_reasons for e in self.elements if not e.citable}
        if self.excluded_blocks!=expected: raise ValueError('excluded ledger')
        for values,key in [(self.elements,lambda e:e.block.block_id),(self.sections,lambda s:s.section_id),(self.tables,lambda t:t.table_id),(self.chunks,lambda c:c.chunk_id)]:
            if len({key(v) for v in values})!=len(values): raise ValueError('duplicate structure id')
        by_id={s.section_id:s for s in self.sections}
        for s in self.sections:
            if s.doc_id!=self.doc_id: raise ValueError('section document')
            seen=set();parent=s
            while parent.parent_id:
                if parent.section_id in seen: raise ValueError('section cycle')
                seen.add(parent.section_id)
                if parent.parent_id not in by_id: raise ValueError('missing parent')
                above=by_id[parent.parent_id]
                if parent.section_id not in above.child_ids: raise ValueError('parent/child mismatch')
                parent=above
            for child in s.child_ids:
                if child not in by_id or by_id[child].parent_id!=s.section_id: raise ValueError('missing child')
        if any(e.block.doc_id!=self.doc_id for e in self.elements): raise ValueError('element document')
        if any(c.section_id not in by_id or c.doc_id!=self.doc_id for c in self.chunks): raise ValueError('chunk document/section')
        return self

class OfflineRunManifest(VersionedContract):
    doc_id: DocId
    started_at: str
    completed_at: str
    wall_seconds: float=Field(ge=0)
    cache_key: str
    structure_hashes: dict[str,str]
