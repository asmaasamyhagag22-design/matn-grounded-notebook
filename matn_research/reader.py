"""Saved originals + exact text offsets. HTML never claims PDF geometry.

HTML uses an explicitly virtual reader coordinate system. Numeric HTML tokens
remain digital-unlinked (no invented PDF word boxes); existing L1 may abstain.
Born-digital PDF uses Matn's existing reader, snapshots and structural assembly.
"""
from html.parser import HTMLParser
from contextlib import nullcontext
import threading
import hashlib
import json
from pathlib import Path
import re

from matn_chat.readiness import write
from matn_contracts.domain import Block, BlockStyle, ExtractorInfo
from matn_contracts.enums import BlockType, ExtractionRoute, Visibility
from matn_reading.structure.document import assemble
from matn_reading.structure.cache import save_snapshot
from .network import request, canonical_url

VERSION = 'topic-reader-v1'
PDF_LOCK = threading.RLock()  # one PDFium/pdfplumber parse at a time, process-wide


def pdf_metadata(path):
    """Read page count and the full outline through the installed PDFium stack.

    No page bodies are scanned here. Iterative bookmark traversal avoids the
    helper's default depth limit, retaining the selector's complete outline.
    Non-page destinations retain PyMuPDF's -1 sentinel and cannot select pages.
    """
    import ctypes
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw

    try:
        pdf = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as exc:
        if exc.err_code == raw.FPDF_ERR_PASSWORD:
            raise ValueError('PASSWORD_PROTECTED_PDF') from exc
        raise
    with pdf:
        outline = []; seen = set()
        pointer = raw.FPDFBookmark_GetFirstChild(pdf, None)
        pending = [(pointer, 0)] if pointer else []
        while pending:
            pointer, level = pending.pop()
            address = ctypes.addressof(pointer.contents)
            if address in seen:
                raise ValueError('PDF_OUTLINE_CYCLE')
            seen.add(address)
            bookmark = pdfium.PdfBookmark(pointer, pdf, level)
            destination = bookmark.get_dest()
            page_index = destination.get_index() if destination else None
            outline.append([level + 1, bookmark.get_title(), page_index + 1 if page_index is not None else -1])
            sibling = raw.FPDFBookmark_GetNextSibling(pdf, pointer)
            child = raw.FPDFBookmark_GetFirstChild(pdf, pointer)
            if sibling:
                pending.append((sibling, level))
            if child:
                pending.append((child, level + 1))
        return len(pdf), outline


def reader_identity():
    from matn_reading.structure.cache import core_fingerprint
    return hashlib.sha256((Path(__file__).read_text() + Path(__file__).with_name('admission.py').read_text() + core_fingerprint()).encode()).hexdigest()


class HTMLText(HTMLParser):
    """Extract explicit prose nodes; retain source character offsets in raw HTML."""
    DROP = {'script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'noscript', 'svg', 'template', 'table'}
    PROSE = {'p', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote'}

    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.raw = raw; self.lines = [0]
        self.lines += [m.end() for m in re.finditer('\n', raw)]
        self.stack = []; self.active = None; self.parts = []; self.blocks = []

    def raw_offset(self):
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def flush(self):
        if self.active:
            text = re.sub(r'\s+', ' ', ''.join(self.parts)).strip()
            if text:
                self.blocks.append(dict(text=text, html_start=self.active[1], html_end=self.raw_offset(),
                                        tag=self.active[0]))
        self.active = None; self.parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        drop = (tag in self.DROP or 'hidden' in attrs or attrs.get('aria-hidden') == 'true'
                or bool(re.search(r'display\s*:\s*none|visibility\s*:\s*hidden', attrs.get('style', ''), re.I)))
        if drop or self.stack:
            if tag not in ('br', 'img', 'input', 'meta', 'link', 'hr'):
                self.stack.append(tag)
            return
        if tag in self.PROSE:
            self.flush(); self.active = (tag, self.raw_offset())
        elif tag == 'br' and self.active:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if self.stack:
            if tag in self.stack:
                self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]
            return
        if self.active and tag == self.active[0]:
            self.flush()

    def handle_data(self, data):
        if self.active and not self.stack:
            self.parts.append(data)


def html_document(raw, source_hash, title):
    parser = HTMLText(raw); parser.feed(raw); parser.flush()
    records = []; mappings = []; doc_id = 'sha256-' + source_hash
    for i, entry in enumerate(parser.blocks):
        # Virtual region = block ordinal, not measured page geometry.
        box = (0., float(i), 1., float(i + 1))
        b = Block.create(doc_id=doc_id, page_index=0, page_label='HTML', bbox=box,
                         block_type=BlockType.HEADING if entry['tag'].startswith('h') else BlockType.TEXT,
                         text=entry['text'], reading_order=i,
                         style=BlockStyle(font_size_pt=None, is_bold=None),
                         extractor=ExtractorInfo(name=VERSION, version='1'),
                         route=ExtractionRoute.TEXT_LAYER, visibility=Visibility.VISIBLE)
        # No word box or invented numeric reader witness for HTML.
        records.append(dict(block=b.model_dump(mode='json'), flagged=False, lines=[]))
        mappings.append(dict(block_id=b.block_id, **entry))
    if not records:
        raise ValueError('NO_STATIC_HTML_PROSE')
    snapshot = dict(schema_version=1, doc_id=doc_id, title=title,
                    core_fingerprint=reader_identity(), cache_key=source_hash,
                    outline=[dict(level=int(entry['tag'][1:])-1, title=entry['text'], page_index=0)
                             for entry in parser.blocks if entry['tag'].startswith('h')],
                    pages=[dict(page_index=0, page_label='HTML', width=1., height=float(len(records)),
                                cropbox=[0., 0., 1., float(len(records))], route='digital_healthy',
                                reasons=[], blocks=records, flags=[], tables=[], ocr=None)])
    d = assemble(snapshot)
    # Relabel all geometry honestly. Text offsets remain exact extracted Unicode.
    data = d.model_dump(mode='json')
    data['coordinate_convention'] = 'Virtual HTML block ordinal; no PDF or browser geometry; raw HTML offsets in html-map.json'
    data['producer_versions']['html'] = VERSION
    tags = {m['block_id']: m['tag'] for m in mappings}
    for e in data['elements']:
        if tags[e['block']['block_id']].startswith('h'):
            e['flags'].append('html_heading_level:' + tags[e['block']['block_id']][1:])
        e['reader_frame'] = 'html_block_ordinal'; e['bbox']['frame'] = 'reader_points'
        for span in e['source_spans']:
            for box in span['boxes']:
                box['frame'] = 'reader_points'
        for token in e['number_tokens']:
            token['bbox']['frame'] = 'reader_points'
    # Chunk numeric occurrences copy the same element occurrences. Relabel the
    # virtual frame consistently, retaining digital-unlinked and every offset.
    for chunk in data['chunks']:
        for token in chunk['numeric_tokens']:
            token['bbox']['frame'] = 'reader_points'
    from matn_contracts.structure import DocumentStructure
    return DocumentStructure.model_validate(data), snapshot, mappings


def read_source(url, folder, *, fetch=request, limits=None):
    """Resume fetch and extraction separately; a failed attempt is never retried."""
    limits = limits or dict(download_bytes=4 * 1024 * 1024, fetch_seconds=25, pdf_pages=6, source_characters=30000)
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    identity = dict(url=canonical_url(url), limits=limits, reader=reader_identity())
    from matn_storyboard.core import digest
    prior = folder / 'read.json'; original = folder / 'original.bin'; fetched = folder / 'fetch.json'
    if prior.exists():
        result = json.loads(prior.read_bytes())
        if result['identity'] != identity:
            raise ValueError('SOURCE_RESUME_BINDING_CHANGED')
        if result['status'] == 'complete':
            if hashlib.sha256(original.read_bytes()).hexdigest() != result['source_sha256']:
                raise ValueError('ORIGINAL_HASH_CHANGED')
            if digest(json.loads((folder / 'document.json').read_bytes())) != result['document_sha256']:
                raise ValueError('READ_SNAPSHOT_CHANGED')
            for name, sha in result['artifacts'].items():
                if hashlib.sha256((folder / name).read_bytes()).hexdigest() != sha:
                    raise ValueError('READ_PROVENANCE_CHANGED')
        return result
    started = dict(identity=identity, status='interrupted', reason='READ_ATTEMPT_HAS_NO_COMPLETED_OUTCOME')
    write(prior, started)  # crash is visible, never an implicit retry
    try:
        if fetched.exists():
            meta = json.loads(fetched.read_bytes())
            if meta['identity'] != identity or hashlib.sha256(original.read_bytes()).hexdigest() != meta['source_sha256']:
                raise ValueError('FETCH_CHECKPOINT_CHANGED')
        else:
            value = fetch(url, timeout=limits['fetch_seconds'], max_bytes=limits['download_bytes'])
            raw = value.pop('body'); original.write_bytes(raw)
            meta = dict(value, identity=identity, source_sha256=hashlib.sha256(raw).hexdigest())
            write(fetched, meta)
        raw = original.read_bytes(); source_hash = meta['source_sha256']
        # PDFium is not thread-safe; the v2 path reads sources concurrently (fetch and HTML stay parallel).
        with (PDF_LOCK if raw.startswith(b'%PDF-') else nullcontext()):
            if raw.startswith(b'%PDF-'):
                from matn_reading.read import read_document
                from matn_reading.structure.cache import page_record, core_fingerprint, cache_key
                total, outline = pdf_metadata(original)
                # Outline inspection reads metadata, not all PDF page bodies. Count
                # any future text scan separately; this selector performs none.
                terms = set(re.findall(r'[a-z]{3,}', limits.get('pdf_query', '').lower()))
                ranked = sorted(outline, key=lambda row: -len(terms & set(re.findall(r'[a-z]{3,}', row[1].lower()))))
                selected = []
                if terms:
                    for _, title, page in ranked:
                        if terms & set(re.findall(r'[a-z]{3,}', title.lower())):
                            for i in (page - 1, page):
                                if 0 <= i < total and i not in selected and len(selected) < limits['pdf_pages']:
                                    selected.append(i)
                indices = sorted(selected or range(min(total, limits['pdf_pages'])))
                reading = read_document(original, pages=indices)
                snapshot = dict(schema_version=1, doc_id=reading.doc_id, title='Public PDF ' + source_hash[:12],
                                core_fingerprint=core_fingerprint(), cache_key=cache_key(reading.doc_id, core_fingerprint()),
                                pages=[page_record(p) for p in reading.pages],
                                outline=[dict(level=level - 1, title=title, page_index=page - 1) for level, title, page in outline])
                d = assemble(snapshot)
                coverage = dict(kind='pdf', read_pages=indices, total_pages=total,
                                complete=len(indices) == total, ocr='not_requested',
                                routes=[p.route.value for p in reading.pages], outline_entries_inspected=len(outline),
                                preliminary_page_text_scans=0, selection='outline relevance then adjacent page; first pages only when no outline match')
            elif 'html' in meta['content_type']:
                # Honor declared encodings; failure is explicit, never replacement glyphs.
                charset = re.search(r'charset=["\s]*([\w-]+)', meta['content_type'])
                text = raw.decode(charset.group(1) if charset else 'utf-8-sig')
                d, snapshot, mappings = html_document(text, source_hash, 'Public HTML ' + source_hash[:12])
                write(folder / 'html-map.json', mappings)
                coverage = dict(kind='html', complete=False, scope='static explicit prose nodes; no CSS/JS visibility evaluation, tables or linked pages',
                                prose_blocks=len(mappings), numeric_geometry='digital-unlinked; existing numeric gate retained')
            else:
                raise ValueError('UNSUPPORTED_CONTENT_TYPE')
        total_chars = sum(len(e.block.text) for e in d.elements)
        coverage['extracted_characters'] = total_chars
        coverage['model_packing_separate'] = True
        save_snapshot(folder / '00_reading.json', snapshot)
        write(folder / 'document.json', d.model_dump(mode='json'))
        from .admission import document_admission
        write(folder / 'admission.json', document_admission(d))
        result = dict(identity=identity, status='complete', source_sha256=source_hash,
                      revision=digest(d.model_dump(mode='json')), doc_id=d.doc_id,
                      document_sha256=digest(d.model_dump(mode='json')), coverage=coverage,
                      final_url=meta['final_url'], fetched_at=meta['fetched_at'], reader=VERSION)
        result['artifacts'] = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
                               for name in ('fetch.json', '00_reading.json', 'html-map.json', 'admission.json') if (folder / name).exists()}
        write(prior, result); return result
    except Exception as exc:
        result = dict(started, status='failed', reason=type(exc).__name__ + ':' + str(exc)[:160])
        write(prior, result); return result
