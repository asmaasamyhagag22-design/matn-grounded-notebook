"""Per-source hybrid retrieval over a bounded lexical pool; no global source loss."""
from matn_rag.embedding import Embedder, MODEL, query_input
from matn_rag.scoring import bm25,cosine,fuse
from matn_research.requirement_selection import vectors
import json
import time
import urllib.request


class HybridSearch:
    def __init__(self,search,*,lookup=None,release=None):
        self.search=search;self.repo=search.repo;self.coverage=[];self.audit=[]
        self.lookup=lookup or self._vectors;self.release=release or self._release

    def _vectors(self,texts):return vectors(texts,embedder=Embedder(),audit=self.audit)

    @staticmethod
    def _release():
        from matn_rag.transport import LoopbackTransport
        from checks.egress_guard import block_egress
        from matn_chat.memory import sample_memory
        transport=LoopbackTransport(timeout=20)
        request=urllib.request.Request(transport.base_url+'/api/generate',
            data=json.dumps(dict(model=MODEL,keep_alive=0)).encode(),headers={'Content-Type':'application/json'})
        with block_egress(),transport.opener.open(request,timeout=20) as stream:response=json.load(stream)
        if not response.get('done') or response.get('done_reason')!='unload':raise RuntimeError('EMBED_UNLOAD_UNCONFIRMED')
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            if not sample_memory()['ollama_runner_rss_bytes']:return
            time.sleep(.1)
        raise RuntimeError('EMBED_DRAIN_UNCONFIRMED')

    def query(self,notebook,sources,question,**kwargs):
        hits=[];coverage=[]
        try:
            for source in sources:
                value=self.search.query(notebook,[source],question,mode='focused',depth=12,ablation='bm25')
                rows=value['hits'];ranked=[]
                if rows:
                    found=self.lookup([h['text'] for h in rows]+[query_input(str(question))])
                    table={(h['source_id'],h['chunk_id']):v for h,v in zip(rows,found[:-1],strict=True)}
                    semantic=cosine(rows,found[-1],table)
                    lexical=bm25(rows,str(question),prefix=False)
                    ranked=fuse(lexical,semantic,'hybrid')
                by={h['chunk_id']:h for h in rows}
                hits.extend(dict(by[cid],hybrid_score=score,source_hybrid_rank=i+1) for i,(cid,score) in enumerate(ranked))
                coverage.append(dict(source=source,candidates=len(rows),hybrid_candidates=len(ranked)))
        finally:self.release()
        self.coverage.append(dict(question=str(question),sources=coverage,policy='per-source-bm25-prefilter12-hybrid-v1'))
        return dict(hits=hits,source_coverage=coverage)


class HybridBlockRanker:
    def __init__(self):self.calls=[]
    def rank(self,question,hits):
        # Retain the lexical/semantic union. A lexical-only postfilter would
        # silently erase the semantic leg and its source-coverage guarantee.
        from matn_chat.block_rank import exclusion
        groups={};excluded=[]
        for hit in hits:
            reason=exclusion(question,hit)
            if reason:excluded.append(dict(id=hit['chunk_id'],reason=reason));continue
            groups.setdefault(hit['source_id'],[]).append(hit)
        from matn_chat.block_rank import LexicalBlockRanker
        for key,rows in groups.items():
            # A chunk can mix checklist cells with narrative. Rank the complete
            # blocks for the question, then retain semantic-only candidates.
            lexical=LexicalBlockRanker().rank(question,rows)
            seen={h['chunk_id'] for h in lexical}
            semantic=sorted((h for h in rows if h['chunk_id'] not in seen),key=lambda h:(h.get('source_hybrid_rank',10**9),h['chunk_id']))
            groups[key]=lexical+semantic
        result=[]
        for i in range(max(map(len,groups.values()),default=0)):
            result.extend(rows[i] for rows in groups.values() if i<len(rows))
        self.calls.append(dict(policy='round-robin-source-hybrid-v1',new_model_calls=0,excluded=excluded))
        return result
