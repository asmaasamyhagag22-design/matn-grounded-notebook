"""Selected-source BM25, fixed-order exact cosine and deterministic equal-weight RRF."""
from collections import Counter, defaultdict
import math
from .tokenizer import tokenize


def terms_and_length(text):
    tokens=tokenize(text);terms=defaultdict(set)
    for token in tokens:
        for term in token.terms: terms[term].add(token.position)
    return {term:len(positions) for term,positions in terms.items()},len(tokens)


def bm25(rows, question, prefix=True, source_stats=None, records=None):
    q=sorted({t for token in tokenize(question) for t in token.terms})
    if records is None:records=[(r['chunk_id'],*terms_and_length(r['context_prefix']+'\n\n'+r['text'] if prefix else r['text'])) for r in rows]
    if source_stats is None:
        n=len(records);total=sum(dl for cid,tf,dl in records);df=Counter(t for cid,tf,dl in records for t in tf)
    else:
        n=sum(s['N'] for s in source_stats.values());total=sum(s['sumdl'] for s in source_stats.values());df=Counter()
        for s in source_stats.values():df.update(s['df'])
    avg=total/n if n else 0
    result=[]
    for cid,tf,dl in records:
        scores=[]
        for term in q:
            f=tf.get(term,0)
            if f and avg:
                idf=math.log1p((n-df[term]+.5)/(df[term]+.5))
                scores.append(idf*(f*2.2)/(f+1.2*(.25+.75*dl/avg)))
        result.append((cid,math.fsum(scores)))
    return sorted(result,key=lambda r:(-r[1],r[0]))


def cosine(rows, query, vectors):
    return sorted([(r['chunk_id'],math.fsum(float(a)*float(b) for a,b in zip(query,vectors[(r['source_id'],r['chunk_id'])],strict=True))) for r in rows],key=lambda r:(-r[1],r[0]))


def fuse(lexical, vector, ablation='hybrid'):
    streams=[lexical[:50]] if ablation=='bm25' else [vector[:50]] if ablation=='vector' else [lexical[:50],vector[:50]]
    contributions=defaultdict(list)
    for stream in streams:
        for rank,(cid,score) in enumerate(stream,1):contributions[cid].append(1/(60+rank))
    return sorted([(cid,math.fsum(scores)) for cid,scores in contributions.items()],key=lambda r:(-r[1],r[0]))
