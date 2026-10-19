"""Request-local sentence handles over authoritative retrieved source intervals."""
from matn_reading.structure.sentences import sentence_spans
from matn_verification.contracts import Citation
from matn_verification.rules import eligibility, evidence_bundles, interval_covered

HANDLE_VERSION = 'chat-sentence-handles-v1'


def build_handles(documents, hits):
    documents=tuple(documents)
    by={e.block.block_id:(d,e) for d in documents for e in d.elements}
    refs=[];ranks={}
    for rank,hit in enumerate(hits):
        for locator in hit['evidence']:
            if locator['kind']!='pdf_block_span':continue
            p=locator['payload'];b=p['block_id']
            if b not in by:raise ValueError('UNKNOWN_RETRIEVED_BLOCK')
            d,e=by[b]
            if hit['doc_id']!=d.doc_id or not 0<=p['start']<p['end']<=len(e.block.text):
                raise ValueError('INVALID_RETRIEVED_SPAN')
            refs.append(Citation(block_id=b,start=p['start'],end=p['end']))
            ranks[b]=min(rank,ranks.get(b,rank))
    units=[];order={}
    for d in documents:
        for e in d.elements:
            b=e.block.block_id;order[b]=len(order)
            if b not in ranks or eligibility(d,e):continue
            for s in sentence_spans(e.block.text):
                ref=Citation(block_id=b,start=s.start,end=s.end)
                if e.block.text[s.start:s.end].strip() and interval_covered(ref,refs):units.append(ref)
    # Bundle only the existing verifier's adjacent, unfinished-sentence rule.
    groups=evidence_bundles(documents,units)
    groups.sort(key=lambda group:(min(ranks[r.block_id] for r in group),order[group[0].block_id],group[0].start))
    handles={}
    for i,group in enumerate(groups,1):
        citations=[]
        for ref in group:
            d,e=by[ref.block_id]
            citations.append(dict(block_id=ref.block_id,start=ref.start,end=ref.end,
                quote=e.block.text[ref.start:ref.end],doc_id=d.doc_id,pdf_page_index=e.block.page_index,
                page_label=e.block.page_label,bbox=list(e.bbox.coordinates),bbox_precision=e.bbox.bbox_precision))
        handles[f's{i}']={'text':' '.join(c['quote'] for c in citations),'citations':citations,'source_title':by[group[0].block_id][0].title}
    return handles
