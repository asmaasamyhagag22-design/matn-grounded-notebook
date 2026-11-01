"""General bibliography admission policy over immutable local reader blocks.

This is a negative source-genre filter, not a relevance or verification rule.
Keep originals and exact offsets; exclude entire blocks so reference titles
cannot re-enter as same-block reading context or adjacent continuations.
"""
from collections import Counter
from copy import deepcopy
import re

from matn_storyboard.core import digest


VERSION = 'bibliography-block-admission-v1'
_NUMBER = re.compile(r'^\s*(?:(?:section|chapter|appendix)\s+)?(?:\[?\d+(?:\.\d+)*\]?|[ivxlcdm]+|[a-z])[.)\s:–—-]+', re.I)
_HEADING = re.compile(
    r'(?:(?:selected|annotated|general|additional|list of)\s+)?(?:references?(?:\s+(?:list|cited))?|bibliograph(?:y|ies)|'
    r'works\s+(?:cited|consulted)|literature\s+cited|cited\s+literature|sources|'
    r'(?:further|suggested|recommended|additional)\s+reading|end\s*notes|foot\s*notes|notes)'
    r'(?:\s*(?:and|&|/)\s*(?:references?|bibliograph(?:y|ies)|sources|notes|further\s+reading|resources))?', re.I)
_YEAR = re.compile(r'\b(?:18|19|20)\d{2}[a-z]?\b|\bn\s*\.\s*d\s*\.', re.I)
_AUTHOR = re.compile(
    r'^(?:[A-ZÀ-ÖØ-Þ][\wÀ-ž\'’–-]+(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ž\'’–-]+){0,3},\s*'
    r'(?:[A-Z]\s*\.|[A-Z][a-z]+)|[A-ZÀ-ÖØ-Þ][\wÀ-ž\'’–-]+\s+[A-Z]{1,3}(?:\b|\.))')
_DOI = re.compile(r'(?:https?://(?:dx\.)?doi\.org/|\bdoi\s*:\s*)10\.\d{4,9}/\S+', re.I)
_ISBN = re.compile(r'\bISBN(?:-1[03])?\s*:?\s*[\dX][\dX\s-]{8,}[\dX]\b', re.I)
_RETRIEVAL = re.compile(r'\b(?:retrieved(?:\s+\w+){0,5}\s+from|accessed(?:\s+on)?\b)', re.I)
_JOURNAL = re.compile(r'\b\d+\s*\(\s*\d+(?:[-–]\d+)?\s*\)\s*[,;:]\s*\d+(?:\s*[-–]\s*\d+)?|'
                      r'\b\d+\s*[,;:]\s*\d+\s*[-–]\s*\d+\b')
_ENTRY_NUMBER = re.compile(r'^\s*(?:\[\d+\]|\d+[.)])\s*')
_MONTH = re.compile(r'^(?:(?:January|February|March|April|May|June|July|August|September|October|November|December)\s*,?\s*)?(?:\d{1,2}\s*,?\s*)?$', re.I)


def _name_field(value):
    words = re.findall(r"[A-Za-zÀ-ž]+", value)
    return bool(words) and len(words) <= 35 and all(
        word[0].isupper() or word in ('and', 'et', 'al', 'de', 'van', 'von', 'of', 'the') for word in words)


def _date_prefix(value, year):
    prefix = value[:year.start()].strip()
    if '(' in prefix:
        author, month = prefix.rsplit('(', 1)
        return _name_field(author) and bool(_MONTH.fullmatch(month))
    return _name_field(prefix)


def _author_date_only(text):
    value = _ENTRY_NUMBER.sub('', re.sub(r'\s+', ' ', text).strip())
    year = _YEAR.search(value[:220])
    return bool(year and _date_prefix(value, year) and re.fullmatch(r'\s*\)?\s*[.;]?\s*', value[year.end():]))


def _bibliographic_tail(text):
    value = re.sub(r'\s+', ' ', text).strip().rstrip('.')
    if _DOI.fullmatch(value) or _ISBN.fullmatch(value): return True
    if re.match(r'^(?:retrieved\b|accessed\b)', value, re.I) and re.search(r'https?://', value): return True
    journal = _JOURNAL.search(value)
    if journal:
        prefix = value[:journal.start()].strip(' ,.;')
        # A journal-name field and volume/pages, with optional identifier suffix;
        # an ordinary result sentence containing a DOI is not a tail field.
        rest = value[journal.end():].strip(' ,.;')
        return _name_field(prefix) and (not rest or bool(_DOI.fullmatch(rest)))
    return False


def bibliography_heading(text):
    value = re.sub(r'\s+', ' ', text).strip().strip(':.;–—- ')
    value = re.sub(r'\s*(?:\((?:continued|cont\.?|selected|annotated)\)|[-–—]\s*continued)\s*$', '', value, flags=re.I)
    value = _NUMBER.sub('', value).strip().strip(':.;–—- ')
    return bool(_HEADING.fullmatch(value))


def citation_structure(text):
    """Require entry structure; a DOI or year in ordinary prose is insufficient."""
    value = _ENTRY_NUMBER.sub('', re.sub(r'\s+', ' ', text).strip())
    signals = []
    if _DOI.search(value): signals.append('doi')
    if _ISBN.search(value): signals.append('isbn')
    if _RETRIEVAL.search(value): signals.append('retrieval')
    if _JOURNAL.search(value): signals.append('journal_volume_issue_pages')
    year = _YEAR.search(value[:220])
    author = bool(_AUTHOR.match(value) or re.match(r'^[A-Z][\w\'’–-]+\s+et\s+al\.', value))
    # APA/Harvard: the date is followed by a title field, not "found/showed" prose.
    dated_title = bool(year and _date_prefix(value, year) and re.match(r'\s*\)?\s*\.\s*\S', value[year.end():]))
    if author and dated_title:
        return ['author_year_title', *signals], True
    # Institutional authors and title-led web/book entries use the same field
    # delimiters. Require a capitalized name/title ending before the date.
    corporate = bool(year and re.fullmatch(
        r'(?:[A-ZÀ-ÖØ-Þ][\wÀ-ž\'’–-]*[ ,:&-]*){1,10}\.\s*\(?\s*', value[:year.start()]))
    if corporate and dated_title:
        return ['author_year_title', *signals], True
    # Vancouver: authors, title, then journal/year/volume/page fields.
    if author and year and 'journal_volume_issue_pages' in signals and re.match(r'\s*[;,:]', value[year.end():]) and re.search(r'\.\s+\S', value[:year.start()]):
        return ['author_title_journal', *signals], True
    # Corporate/title-led entries with a parenthesized year or n.d. and a field.
    if year and dated_title and signals and '(' in value[:year.start() + 1]:
        return ['dated_bibliographic_fields', *signals], True
    if _DOI.fullmatch(value.rstrip('.')) or _ISBN.fullmatch(value.rstrip('.')):
        return ['standalone_identifier', *signals], True
    if re.match(r'^(?:retrieved\b|accessed\b)', value, re.I) and re.search(r'https?://', value):
        return ['standalone_retrieval', *signals], True
    if _author_date_only(text):
        return ['author_date_fragment', *signals], True
    # Weak entry fragments count only in a dense adjacent reference run.
    return signals, bool('journal_volume_issue_pages' in signals and _ENTRY_NUMBER.match(text) and year)


def document_admission(document):
    rows = []; active = None; active_level = None; candidates = []
    levels = {s.heading_block_id: s.level for s in document.sections if s.heading_block_id}
    # Real DOM heading ranks survive duplicate titles, which cannot always be
    # matched uniquely by the general PDF/outline section builder.
    for element in document.elements:
        for flag in element.flags:
            if re.fullmatch(r'html_heading_level:[1-6]', flag):
                levels[element.block.block_id] = int(flag.rsplit(':', 1)[1])
    for element in document.elements:
        block = element.block; text = block.text
        heading = bibliography_heading(text)
        typed_heading = block.block_type.value == 'heading' or element.role == 'heading'
        if heading:
            active = block.block_id; active_level = levels.get(block.block_id)
        elif typed_heading and (active_level is None or levels.get(block.block_id, active_level) <= active_level):
            active = None; active_level = None
        reasons, weak = citation_structure(text)
        strong = bool(reasons and reasons[0] in (
            'author_year_title', 'author_title_journal', 'dated_bibliographic_fields',
            'standalone_identifier', 'standalone_retrieval', 'author_date_fragment'))
        # Digital PDF readers may put several complete reference lines in one
        # text block. A dense run within that block uses the same entry rule.
        lines = [line for line in text.splitlines() if line.strip()]
        line_entries = sum(citation_structure(line)[1] for line in lines)
        dense_block = len(lines) >= 2 and line_entries >= 2 and line_entries / len(lines) >= .5
        excluded = (['bibliographic_section'] if active else []) + reasons if (active or strong) else []
        if dense_block: excluded = list(dict.fromkeys([*excluded, 'dense_citation_block']))
        rows.append(dict(block_id=block.block_id, page_index=block.page_index,
            text_sha256=digest(text), admitted=not excluded, reasons=excluded,
            **(dict(section_heading_block_id=active) if active else {})))
        candidates.append((strong or weak, reasons))
    # A reference split into author/date, title, and publication fields is a
    # bounded structural sequence. Detect across at most three adjacent blocks;
    # never join their text or change original offsets.
    for i in range(len(rows)-2):
        header, title, tail = document.elements[i:i+3]
        title_text = title.block.text.strip()
        if (_author_date_only(header.block.text) and 2 <= len(title_text.split()) <= 60
                and len(title_text) <= 400 and title_text[:1].isupper()
                and title.block.block_type.value != 'heading' and _bibliographic_tail(tail.block.text)):
            for row in rows[i:i+3]:
                row['admitted'] = False
                row['reasons'] = list(dict.fromkeys([*row['reasons'], 'split_citation_entry']))
    # Two adjacent structured entries are a dense run. This also covers PDF
    # blocks split at wrapping/newlines without relying on DOM list elements.
    start = 0
    while start < len(rows):
        if not candidates[start][0]: start += 1; continue
        end = start + 1
        while end < len(rows) and candidates[end][0]: end += 1
        if end - start >= 2:
            for i in range(start, end):
                rows[i]['admitted'] = False
                rows[i]['reasons'] = list(dict.fromkeys([*rows[i]['reasons'], 'dense_citation_run', *candidates[i][1]]))
        start = end
    excluded = {r['block_id'] for r in rows if not r['admitted']}
    for row, element in zip(rows, document.elements, strict=True):
        if row['block_id'] in excluded:
            row['text'] = element.block.text
    return dict(policy=VERSION, doc_id=document.doc_id,
        document_sha256=digest(document.model_dump(mode='json')), blocks=rows,
        counts=dict(blocks=len(rows), excluded_blocks=len(excluded), admitted_blocks=len(rows)-len(excluded)),
        reason_counts=dict(Counter(reason for r in rows for reason in r['reasons'])),
        interpretation='Bibliographic blocks remain in the immutable reading; excluded from support and reading context. No semantic coverage inferred.')


def admission_inventory(documents):
    audits = [document_admission(d) for d in documents]
    excluded = {(a['doc_id'], r['block_id']): r['reasons'] for a in audits for r in a['blocks'] if not r['admitted']}
    return dict(policy=VERSION, documents=audits), excluded


def admitted_hits(hits, excluded):
    result = []
    for hit in hits:
        value = deepcopy(hit)
        value['evidence'] = [r for r in value['evidence'] if r['kind'] != 'pdf_block_span'
            or (value['doc_id'], r['payload']['block_id']) not in excluded]
        if value['evidence']: result.append(value)
    return result


def admitted_handles(handles, excluded):
    # Meaning-handle completion may inspect an adjacent source block. Its
    # expanded citations must obey the same policy as initial index locators.
    return {key: h for key, h in handles.items()
            if not any((c['doc_id'], c['block_id']) in excluded for c in h['citations'])}
