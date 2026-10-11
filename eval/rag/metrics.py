"""Offline pre-registered retrieval measurements; no model calls or source reads."""
import math
import numpy as np


def wilson(successes,n):
    if not n:return [None,None]
    z=1.959963984540054;p=successes/n;d=1+z*z/n
    center=(p+z*z/(2*n))/d;radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [max(0.,center-radius),min(1.,center+radius)]


def paired_exact(lost,gained):
    n=lost+gained
    return min(1.,2*sum(math.comb(n,k) for k in range(min(lost,gained)+1))/2**n) if n else 1.


def rank(question,result):
    relevant=set(question['relevant_chunk_ids'])
    return next((i for i,h in enumerate(result['hits'],1) if h['chunk_id'] in relevant),None)


def measure(questions,results):
    reachable=[q for q in questions if q['reachable']];ranks=[rank(q,results[q['id']]) for q in reachable];n=len(ranks)
    hit={str(k):{'successes':sum(r is not None and r<=k for r in ranks),'n':n} for k in (1,5,10,20,50)}
    for record in hit.values():record.update(rate=record['successes']/n if n else None,wilson95=wilson(record['successes'],n))
    reciprocal=np.array([1/r if r is not None and r<=10 else 0. for r in ranks])
    if n:
        rng=np.random.default_rng(20261012);boot=reciprocal[rng.integers(0,n,size=(10000,n))].mean(axis=1);ci=np.quantile(boot,[.025,.975]).tolist()
    else:ci=[None,None]
    return {'total':len(questions),'reachable':n,'unreachable':len(questions)-n,'reading_ceiling':n/len(questions) if questions else None,
        'hit':hit,'mrr10':float(reciprocal.mean()) if n else None,'mrr10_bootstrap95':ci,
        'end_to_end_hit':{k:v['successes']/len(questions) if questions else None for k,v in hit.items()}}


def grouped(questions,results):
    groups={'overall':questions}
    for field in ('source','split','question_kind'):
        for value in sorted({q[field] for q in questions}):groups[field+'/'+value]=[q for q in questions if q[field]==value]
    ordered=sorted(questions,key=lambda q:(q['content_token_overlap_ratio'],q['id']))
    for i in range(3):groups['overlap_tertile/'+str(i+1)]=ordered[i*len(ordered)//3:(i+1)*len(ordered)//3]
    for source in sorted({q['source'] for q in questions}):
        for split in ('tune','check'):
            for kind in ('kp','kn'):groups[f'{source}/{split}/{kind}']=[q for q in questions if q['source']==source and q['split']==split and q['question_kind']==kind]
    return {k:measure(qs,results) for k,qs in groups.items()}
