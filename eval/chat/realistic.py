"""Compact first-attempt/redraft packet and descriptive, unlabeled summaries."""
from collections import Counter
from eval.verification.pilot import quantiles


def candidates(attempt):
    if attempt.get('sentences'):return attempt['sentences']
    parsed=attempt.get('parsed',{})
    rows=parsed.get('sentences',[]) if isinstance(parsed,dict) else []
    return [r for r in rows if isinstance(r,dict) and isinstance(r.get('text'),str)] if isinstance(rows,list) else []


def render_packet(rows):
    lines=['# Realistic-v2 — UNLABELED / NOT FROZEN','','Local only; VNR publication exclusions apply. Label source support independently of verifier outcomes. Every first-attempt and redraft sentence is retained.','']
    for row in rows:
        lines += [f"## {row['id']} — {row['cohort']} / {row['split']}",'',f"Question: {row['question']}",'',f"Answer state: {row['response']['state']}",'']
        for attempt in row.get('trace',[]):
            lines += ['### '+('First attempt' if attempt['attempt']==0 else 'Redraft'),'']
            items=candidates(attempt)
            if not items:lines += ['No identifiable sentences. '+attempt.get('error',{}).get('code','Empty list.'),'']
            for i,item in enumerate(items,1):
                receipt=item.get('receipt',{});first=item.get('first_failure');reasons=item.get('reasons',[])
                if not receipt:verdict='error';failure=attempt.get('error',{}).get('code','unverified_contract');reasons=[failure]
                else:verdict=receipt['status'];failure=first['layer']+' '+first['verdict'] if first else 'none'
                lines += [f"**Sentence {i}:** {item['text']}",'']
                for h in item.get('handles',[]):
                    citations=[c for c in item.get('citations',[]) if c in row.get('handles',{}).get(h,{}).get('citations',[])]
                    if not citations and h in row.get('handles',{}):citations=row['handles'][h]['citations']
                    # Packet can also be constructed from a trace fixture without the catalog.
                    if not row.get('handles') and len(item.get('handles',[]))==1:citations=item.get('citations',[])
                    if citations:
                        lines += [f"Evidence `{h}`:",'']
                        for c in citations:lines += ['```text',c['quote'],'```','']
                    else:lines += [f"Evidence `{h}`: [UNKNOWN / UNRESOLVED HANDLE]",'']
                lines += [f"Verdict: {verdict}. First failure: {failure}. Reasons: {', '.join(reasons) or 'none'}.",'',
                    'Label (supported / unsupported / partial / unclear): ______','','Reviewer reason: ______','']
    return '\n'.join(lines)+'\n'


def summarize(rows):
    cohorts={}
    for cohort in sorted({r['cohort'] for r in rows}):
        sub=[r for r in rows if r['cohort']==cohort];first=[];repair=[];before=0;after=0;failed=0;rescued=0;lost=0
        for r in sub:
            attempts=r.get('trace',[]);a=candidates(attempts[0]) if attempts else []
            first.extend(a);repair.extend(c for attempt in attempts[1:] for c in candidates(attempt))
            initial_verified=sum(c.get('receipt',{}).get('status')=='verified' for c in a)
            before+=initial_verified
            rescued+=max(0,len(r['response']['sentences'])-initial_verified)
            lost+=max(0,initial_verified-len(r['response']['sentences']))
            after+=len(r['response']['sentences']);failed+=sum(c.get('receipt',{}).get('status')!='verified' for c in a)
        def distribution(items):
            return dict(Counter((c.get('first_failure') or {}).get('layer','verified' if c.get('receipt',{}).get('status')=='verified' else 'error') for c in items))
        cohorts[cohort]={'questions':len(sub),'answer_states':dict(Counter(r['response']['state'] for r in sub)),
            'verified_sentences_per_answer':dict(sorted(Counter(len(r['response']['sentences']) for r in sub).items())),
            'first_attempt':{'sentences':len(first),'verified':before,'first_failure':distribution(first)},
            'redraft':{'sentences':len(repair),'failed_initial_slots':failed,'rescued_slots':rescued,'verified_before':before,'verified_after':after,'lost_on_error':lost,'first_failure':distribution(repair)},
            'latency_seconds':{k:quantiles([r['response']['timings'][k] for r in sub if k in r['response'].get('timings',{})]) for k in ('generation_seconds','verification_seconds','total_seconds')},
            'dropped_sentences':sum(r['response']['dropped_sentences'] for r in sub)}
    return {'label_state':'UNLABELED / NOT FROZEN','cohorts':cohorts,'scope':'descriptive coverage and failure diagnostics, never support labels or verifier accuracy'}
