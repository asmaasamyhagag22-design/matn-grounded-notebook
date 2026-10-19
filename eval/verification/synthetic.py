"""Deterministic preconditioned operators; quota shortfalls never force a mutation."""
import json
import random
import re
from pathlib import Path
from .v2 import sha,save,ROOT

SEED=20261017
TYPES=('positive','number_change','direction_flip','negation','modality_shift','entity_swap','scope_change','unsupported_addition')


def mutations(text,neighbor_entities=()):
    result={}
    def edit(kind,m,new,subtype):
        a,z=m.span() if hasattr(m,'span') else m
        result[kind]=dict(start=a,end=z,old=text[a:z],new=new,text=text[:a]+new+text[z:],subtype=subtype,operator_version='single-edit-v1')
    from matn_verification.numbers import parse
    nums,problems=parse(text)
    if not problems:
        for n in nums:
            if n.unit and not n.unit.startswith('period:') and not n.qualifier and n.value>=0:
                new=str(n.value+1)
                if new not in text:edit('number_change',(n.start,n.end),new,'value');break
    m=re.search(r'\b(increased|decreased|increases|decreases)\b',text)
    if m and not re.search(r'\b(growth|decline|rate of)\b',text,re.I):
        edit('direction_flip',m,{'increased':'decreased','decreased':'increased','increases':'decreases','decreases':'increases'}[m.group()],'direction')
    if not re.search(r'\b(not|no|never|without|cannot|only)\b',text,re.I):
        m=re.search(r'\b(is|are|was|were|has|have|had|can|could|may|will|should)\b',text)
        if m:edit('negation',(m.end(),m.end()),' not','insert_not')
    m=re.search(r'\bmay\b',text)
    if m:edit('modality_shift',m,'will','possibility_to_prediction')
    # Only known same-kind named subjects; no arbitrary title-case substitution.
    countries=('Egypt','France','Denmark','Germany','India','China','United States')
    sectors=('Financial Services','IT Services','Government')
    for names in (countries,sectors):
        old=next((n for n in names if re.search(r'\b'+re.escape(n)+r'\b',text)),None)
        new=next((n for n in names if n in neighbor_entities and n not in text),None)
        if old and new:
            edit('entity_swap',(text.index(old),text.index(old)+len(old)),new,'same_chunk_neighbor');break
    m=re.search(r'\b(?:19|20)\d{2}\b',text)
    if m:
        new=str(int(m.group())+7)
        if new not in text:edit('scope_change',m,new,'period')
    # A new universal causal conclusion is unsupported by the source quote.
    if not re.search(r'\b(all national outcomes|proves)\b',text,re.I):
        edit('unsupported_addition',(len(text),len(text)),' This proves that all national outcomes will improve.','causal_universal')
    return result


def family_split(rows):
    rng=random.Random(SEED);result={}
    for source in sorted({r['source'] for r in rows}):
        ids=sorted({r['family_id'] for r in rows if r['source']==source});rng.shuffle(ids)
        result.update({f:'tune' if i<len(ids)//3 else 'check' for i,f in enumerate(ids)})
    return result


def choose_items(parents):
    pools={kind:[] for kind in TYPES}
    for parent in parents:
        changes=mutations(parent['text'],parent['neighbors'])
        for kind in TYPES:
            if kind!='positive' and kind not in changes:continue
            base={k:v for k,v in parent.items() if k!='neighbors'};change=changes.get(kind)
            pools[kind].append({**base,'item_id':sha(parent['family_id']+':'+kind)[:24],'type':kind,
                'label':'supported' if kind=='positive' else 'unsupported',
                'claim':change['text'] if change else parent['text'],'edit':change,
                'seed':SEED,'status':'frozen_pending_reviewer_spotcheck','annotator':'code operator v1','adjudicator':None})
    selected=[]
    for kind,pool in pools.items():
        for split,quota in [('tune',20),('check',40)]:
            eligible=sorted((r for r in pool if r['split']==split),key=lambda r:(r['source'],r['family_id'],r.get('start',0)))
            # Round-robin sources, at most one sibling of a type per family.
            by={source:[r for r in eligible if r['source']==source] for source in sorted({r['source'] for r in eligible})}
            used=set();count=0
            while count<quota and any(by.values()):
                for source in by:
                    while by[source] and by[source][0]['family_id'] in used:by[source].pop(0)
                    if by[source] and count<quota:
                        row=by[source].pop(0);selected.append(row);used.add(row['family_id']);count+=1
    return selected


def source_sentences(text):
    for m in re.finditer(r'.+?[.!?](?!\d)(?:\s|$)',text):
        q=m.group().strip();a=m.start()+len(m.group())-len(m.group().lstrip())
        yield a,a+len(q),q


def build():
    from .coverage import load_documents
    from matn_verification.rules import eligibility,fingerprint,entities
    docs=load_documents();parents=[];exclusions=[]
    # All sentence targets in one block are one conservative family; no split crossing.
    for name,d in sorted(docs.items()):
        candidates=[]
        structure_sha=fingerprint(d)
        chunk_entities={c.chunk_id:set(entities(c.text)) for c in d.chunks}
        for e in d.elements:
            if eligibility(d,e):continue
            b=e.block
            for a,z,q in source_sentences(b.text):
                if not 8<=len(q.split())<=75 or not q[0].isupper() or '\n' in q:continue
                if re.match(r'^(It|They|This|These|Those|Their|He|She|However|Therefore|For example|Figure|Table)\b',q):continue
                if re.search(r'[{}=<>]|https?://|\b[A-Za-z]+\d+[A-Za-z]+\b',q):continue
                # Must be reconstructible from authoritative primary source spans.
                spans=[s for c in d.chunks for s in c.primary if s.block_id==b.block_id]
                cursor=a
                for x,y in sorted((s.start,s.end) for s in spans):
                    if x<=cursor<y:cursor=min(y,z)
                if cursor!=z:continue
                neighbors=set().union(*(chunk_entities[c.chunk_id] for c in d.chunks if any(s.block_id==b.block_id for s in c.primary)))
                candidates.append(dict(source=name,doc_id=d.doc_id,source_sha256=d.doc_id.removeprefix('sha256-'),
                    structure_sha256=structure_sha,block_id=b.block_id,start=a,end=z,text=q,
                    evidence=q,evidence_sha256=sha(q),family_id=name+':'+b.block_id,
                    original_gold_id=None,dev_registration=name,
                    provenance='code-selected exact quote from registered dev structure; operator labels by construction; not human gold',
                    neighbors=sorted(neighbors)))
        candidates.sort(key=lambda c:(c['doc_id'],c['block_id'],c['start'],c['end']))
        rng=random.Random(SEED);rng.shuffle(candidates)
        # Do not select parents based on model/rule scores or force operator quotas.
        parents+=candidates
        exclusions.append({'source':name,'eligible_sentences':len(candidates),'eligible_families':len({c['family_id'] for c in candidates})})
    splits=family_split(parents)
    parents=[{**p,'split':splits[p['family_id']]} for p in parents]
    items=choose_items(parents)
    local=ROOT/'synthetic-v1.json';save(local,items)
    counts={k:sum(i['type']==k for i in items) for k in TYPES}
    metadata=[{k:v for k,v in i.items() if k in ('item_id','family_id','source','doc_id','source_sha256','structure_sha256','block_id','start','end','split','type','label','seed','status','evidence_sha256','provenance','annotator','adjudicator','original_gold_id','dev_registration')}|
        {'claim_sha256':sha(i['claim']),'edit_sha256':sha(json.dumps(i['edit'],sort_keys=True))} for i in items]
    manifest=dict(version='synthetic-v1',seed=SEED,requested_items=480,actual_items=len(items),counts=counts,
        shortfalls={k:60-v for k,v in counts.items() if v<60},state='FROZEN_WITH_SHORTFALLS' if len(items)<480 else 'FROZEN',
        decisions=['No forced mutations. Operator-ineligible siblings omitted before scoring.',
        'One block per family including all sentence targets; source-balanced 4 tune / 8 check positive families. Negative types may use other eligible parents, source round-robin, target 20 tune / 40 check per type.',
        'Reviewer may drop bad items later, never relabel; no model scores used in construction.'],
        exclusions=exclusions,local_artifact=str(local),local_sha256=sha(local.read_bytes()),items=metadata)
    save('eval/verification/synthetic/manifest-v1.json',manifest)
    rng=random.Random(SEED);lines=['# Synthetic v1 — seeded reviewer spot-check','Local source text; do not publish. Drop bad items, never relabel.']
    for kind in TYPES:
        rows=sorted((i for i in items if i['type']==kind),key=lambda i:i['item_id']);sample=rng.sample(rows,min(5,len(rows)))
        lines += [f'\n## {kind}: {len(sample)}/5']
        for i in sample:lines += [f"\n### {i['item_id']} — {i['source']} / {i['split']} / {i['label']}",f"Evidence: {i['evidence']}",f"Claim: {i['claim']}",f"Span: {i['block_id']} [{i['start']},{i['end']})",f"Edit: {json.dumps(i['edit'],ensure_ascii=False)}"]
    (ROOT/'synthetic-spotcheck.md').write_text('\n\n'.join(lines)+'\n')
    return manifest


if __name__=='__main__':print(json.dumps({k:v for k,v in build().items() if k!='items'},indent=2))
