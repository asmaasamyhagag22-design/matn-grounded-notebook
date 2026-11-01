"""Exact table row projection with headers and merged-cell membership, no prose inference."""
import re
from matn_verification.rules import eligibility, fingerprint, _linked


def lookup(documents, question):
    candidates=[]
    for d in documents:
        by={e.block.block_id:e for e in d.elements}
        for table in d.tables:
            if table.structure!='available' or any(eligibility(d,by[b]) for b in table.block_ids):continue
            headers={c.col:c.text for c in table.cells if c.is_header}
            # Require a requested source header, an exact source value, and a
            # wh question. Negated/yes-no/comparative claims are not projections.
            if not re.match(r'^\s*(?:what|which)\b',question,re.I):continue
            requested=[col for col,text in headers.items() if text.casefold() in question.casefold()]
            matches=[c for c in table.cells if not c.is_header and c.text and re.search(r'(?<!\w)'+re.escape(c.text)+r'(?!\w)',question,re.I)]
            if len(requested)!=1 or len(matches)!=1:continue
            cell=matches[0]
            # Full grammar match, rather than keyword presence. Unsupported
            # negation, comparison, modifiers and extra clauses fail closed.
            header=re.escape(headers[requested[0]])
            value=re.escape(cell.text)
            projection=rf"\s*(?:which|what)\s+{header}\s+(?:includes?|contains?)\s+{value}\s*\?\s*"
            if not re.fullmatch(projection,question,re.I):continue
            if cell.col==requested[0]:continue
            if cell.row_span!=1:continue  # broad merged key would request many rows
            row=[c for c in table.cells if not c.is_header and c.row<=cell.row<c.row+c.row_span]
            if not any(c.col==requested[0] for c in row):continue
            if any(not _linked(n) for c in row for n in c.numeric_tokens):continue
            candidates.append((d,table,headers,row,by))
    base=dict(schema_version=1,configuration='exact-table-projection-v1',state='insufficient_evidence',
        message='No unambiguous source table row matches the requested header and value.',sentences=[],
        receipts=[],error=None,dropped_sentences=0,discarded_candidates=0,timings={},model_calls=0)
    if len(candidates)!=1:return base
    d,t,headers,row,by=candidates[0];citations=[]
    for cell in row:
        for s in cell.source_spans:
            e=by[s.block_id]
            citations.append(dict(block_id=s.block_id,start=s.start,end=s.end,quote=e.block.text[s.start:s.end],
                doc_id=d.doc_id,pdf_page_index=e.block.page_index,page_label=e.block.page_label,
                bbox=list(cell.bbox.coordinates),bbox_precision=cell.bbox.bbox_precision))
    base.update(state='answered',message='Exact source table cells with original headers and row membership; no generated paraphrase.',
        table_projection=dict(table_id=t.table_id,source_fingerprint=fingerprint(d),row=next(c.row for c in row if c.row_span==1),
            matched_value_row=next(c.row for c in row if c.row_span==1),headers=headers,
            cells=[c.model_dump(mode='json') for c in row],membership='row <= matched_value_row < row + row_span'),
        sentences=[dict(text='; '.join(headers.get(c.col,str(c.col))+': '+c.text for c in sorted(row,key=lambda c:c.col)),
            kind='source_table_projection',verification_scope='source_cells_headers_and_row_membership',
            citations=citations,receipt_index=None)],answer_sources=[d.doc_id],answer_kind='source_table_projection')
    return base
