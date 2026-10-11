"""One depth-param ranking path, selected-source summaries, separate neighbor context."""
from collections import Counter
import hashlib
from .embedding import DIGEST, QUERY_INPUT_VERSION, query_input
from .tokenizer import tokenize
from .scoring import bm25, cosine, fuse, terms_and_length


class Search:
    def __init__(self, repository, embedder, lexical_only=False):
        self.repo=repository;self.embedder=embedder;self.lexical_only=lexical_only
        self.query_vectors={}
        self.corpus_cache={}

    def query(self, notebook, selected, question, mode='focused', depth=None, ablation='hybrid'):
        if mode not in ('focused','survey') or ablation not in ('hybrid','bm25','vector','no-prefix'):
            raise ValueError('QUERY_MODE')
        self.repo.validate_selection(notebook,selected)
        key=(notebook,tuple(sorted(selected)),getattr(self.repo,'revision',0))
        if key not in self.corpus_cache:self.corpus_cache[key]={'rows':self.repo.selected_chunks(notebook,selected)}
        cache=self.corpus_cache[key];rows=cache['rows']
        b=max(10,3*len(selected));depth=(b if mode=='survey' else 10) if depth is None else depth
        if not isinstance(depth,int) or depth<1 or (mode=='survey' and depth<b):raise ValueError('QUERY_DEPTH')
        prefix=ablation!='no-prefix';variant='doc-input-v1' if prefix else 'doc-input-no-prefix-v1'
        if variant not in cache:
            records=[(r['chunk_id'],*terms_and_length(r['context_prefix']+'\n\n'+r['text'] if prefix else r['text'])) for r in rows]
            cache[variant]={'records':records,'stats':self.repo.source_stats(selected,variant),'vectors':self.repo.vectors(selected,variant)}
        cached=cache[variant]
        lexical=bm25(rows,question,prefix,cached['stats'],cached['records'])
        vector=[]
        vectors={};qvec=None
        if rows and ablation!='bm25' and not self.lexical_only:
            self.embedder.check_digest()  # mandatory even for cache hits
            qtext=query_input(question);cache_key=(DIGEST,QUERY_INPUT_VERSION,hashlib.sha256(qtext.encode()).hexdigest());qvec=self.query_vectors.get(cache_key)
            # Query vectors stay outside repository state: searching cannot create orphan cache rows.
            if qvec is None:
                qvec=self.embedder.embed([qtext])[0];self.query_vectors[cache_key]=qvec
            vectors=cached['vectors']
            if len(vectors)!=len(rows):raise ValueError('VECTOR_INTEGRITY')
            vector=cosine(rows,qvec,vectors)
        effective='bm25' if self.lexical_only else 'hybrid' if ablation=='no-prefix' else ablation
        global_rank=fuse(lexical,vector,effective);global_score=dict(global_rank)
        per_source={};reserved=set();source_rank={}
        if mode=='survey':
            for sid in sorted(selected):
                local=[r for r in rows if r['source_id']==sid]
                localids={r['chunk_id'] for r in local}
                lr=bm25(local,question,prefix,{sid:cached['stats'][sid]},[r for r in cached['records'] if r[0] in localids])
                vr=cosine(local,qvec,vectors) if qvec is not None else []
                per_source[sid]=fuse(lr,vr,effective)
                source_rank.update({cid:rank for rank,(cid,score) in enumerate(per_source[sid],1)})
                reserved.update(cid for cid,score in per_source[sid][:min(2,len(local))])
            base=set(reserved)
            for cid,score in global_rank:
                if len(base)>=b:break
                base.add(cid)
            ranking=sorted(base,key=lambda cid:(-global_score.get(cid,0),source_rank.get(cid,10**9),cid))
            ranking += [cid for cid,score in global_rank if cid not in base]
        else:ranking=[cid for cid,score in global_rank]
        by={r['chunk_id']:r for r in rows}
        lranks={cid:(rank,score) for rank,(cid,score) in enumerate(lexical[:50],1)}
        vranks={cid:(rank,score) for rank,(cid,score) in enumerate(vector[:50],1)}
        franks={cid:rank for rank,(cid,score) in enumerate(global_rank,1)}
        qterms={t for token in tokenize(question) for t in token.terms}
        hits=[];context=[];seencontext=set()
        for cid in ranking[:depth]:
            r=by[cid];hit={k:r.get(k) for k in ('chunk_id','source_id','doc_id','text','context_prefix','kind','section_path','evidence','numeric_tokens','unavailable_tables','coverage_flags')}
            hit.update(bm25_rank=lranks.get(cid,(None,None))[0],bm25_score=lranks.get(cid,(None,None))[1],
                vector_rank=vranks.get(cid,(None,None))[0],vector_score=vranks.get(cid,(None,None))[1],
                rrf_rank=franks.get(cid),rrf_score=global_score.get(cid,0),coverage_slot=cid in reserved,
                per_source_rank=source_rank.get(cid),matched_lexical_terms=sorted(qterms & set(next(tf for key,tf,dl in cached['records'] if key==cid))))
            hits.append(hit)
            for key in ('prev_chunk_id','next_chunk_id'):
                nid=r.get(key)
                if nid in by and nid not in seencontext and by[nid]['source_id']==r['source_id']:
                    context.append({k:by[nid].get(k) for k in ('chunk_id','source_id','text','context_prefix','evidence')});seencontext.add(nid)
        counts=Counter(h['source_id'] for h in hits);summary=[]
        for sid in sorted(selected):
            local=[r for r in rows if r['source_id']==sid];ids={r['chunk_id'] for r in local}
            s={'source_id':sid,'citable_count':len(local),'hits':counts[sid],
               'no_lexical_match':not any(score>0 for cid,score in lexical if cid in ids),'no_citable_content':not local}
            if mode=='survey':s['coverage_shortfall']=max(0,2-counts[sid])
            summary.append(s)
        return {'mode':mode,'ablation':ablation,'hits':hits,'summary':summary,'context':context}
