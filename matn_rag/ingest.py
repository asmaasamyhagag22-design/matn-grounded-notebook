"""Ingest validated structure only, with exact primary/repeat block-span provenance."""
import hashlib
from matn_contracts.structure import DocumentStructure
from matn_reading.structure.coverage import resolve_citation, validate_coverage
from .contracts import INDEX_VERSION, canonical
from .tokenizer import VERSION
from .embedding import DIGEST


def prepare(document):
    if not isinstance(document,DocumentStructure):
        raise TypeError('VALIDATED_DOCUMENT_STRUCTURE_REQUIRED')
    validate_coverage(document.elements,document.sections,document.chunks)
    by={e.block.block_id:e for e in document.elements};sections={s.section_id:s for s in document.sections}
    records=[]
    for c in document.chunks:
        evidence=[]
        for mapping in c.offset_map:
            if mapping.kind=='separator':continue
            for span in resolve_citation(c,mapping.start,mapping.end,document.chunks):
                e=by[span['block_id']]
                if not e.citable:raise ValueError('NON_CITABLE_EVIDENCE')
                payload={**span,'pdf_page_index':e.block.page_index,'page_label':e.block.page_label,
                         'bbox':e.bbox.model_dump(mode='json')}
                evidence.append({'kind':'pdf_block_span','payload':payload})
        if not evidence:continue
        pages={e['payload']['pdf_page_index'] for e in evidence}
        tables=[{'table_id':t.table_id,'unavailable_reason':t.unavailable_reason,'pdf_page_index':t.pdf_page_index}
                for t in document.tables if t.structure=='unavailable' and t.pdf_page_index in pages]
        flags=sorted(set(c.flags) | {f for s in c.primary for f in by[s.block_id].flags})
        blockids={s.block_id for s in c.primary}
        for coverage in document.coverage:
            if blockids & set(coverage.possible_prose_in_figure_block_ids):flags.append('possible_prose_in_figure')
            if blockids & set(coverage.suspected_order_break_block_ids):flags.append('suspected_order_break')
        records.append({'chunk_id':c.chunk_id,'doc_id':c.doc_id,'text':c.text,'context_prefix':c.context_prefix,
            'kind':c.kind,'section_path':list(sections[c.section_id].path),'evidence':evidence,
            'numeric_tokens':[n.model_dump(mode='json') for n in c.numeric_tokens],
            'unavailable_tables':tables,'coverage_flags':sorted(set(flags)),'prev_chunk_id':c.prev_chunk_id,'next_chunk_id':c.next_chunk_id})
    metadata={'fingerprint':hashlib.sha256(canonical(document.model_dump(mode='json'))).hexdigest(),
              'versions':{'tokenizer':VERSION,'index':INDEX_VERSION,'chunker':document.producer_versions.chunks if hasattr(document.producer_versions,'chunks') else document.producer_versions['chunks']},
              'digest':DIGEST,'source_type':'pdf','reader_fingerprint':document.reader_fingerprint}
    return metadata,records


def ingest(repository, notebook, document, embedder):
    metadata,records=prepare(document);embedder.check_digest()
    repository.create_notebook(notebook)
    sid=repository.add_source(notebook,document.doc_id,metadata,records)
    for variant in ('doc-input-v1','doc-input-no-prefix-v1'):
        inputs=sorted([(r['chunk_id'], r['context_prefix']+'\n\n'+r['text'] if variant=='doc-input-v1' else r['text']) for r in records])
        missing=[]
        for cid,text in inputs:
            if repository.get_embedding(DIGEST,variant,text) is None:missing.append((cid,text))
        for start in range(0,len(missing),8):
            batch=missing[start:start+8];vectors=embedder.embed([text for cid,text in batch])
            for (cid,text),vector in zip(batch,vectors,strict=True):repository.put_embedding(DIGEST,variant,text,vector)
        for cid,text in inputs:repository.link_embedding(sid,cid,variant,DIGEST,variant,text)
    return sid
