"""Isolated, offline CPU fp32 TUNE pilot. No runtime integration or model selection."""
from collections import defaultdict
import argparse
import json
import math
import os
from pathlib import Path
import resource
import statistics
import time
from .v2 import save,sha


def tune_only(rows):
    if any(r['split']!='tune' for r in rows):raise ValueError('TUNE only; check scoring forbidden')
    return rows


def variation(*runs):
    if not runs or any(set(r)!=set(runs[0]) for r in runs):raise ValueError('self-variation inputs differ')
    return max((max(r[k] for r in runs)-min(r[k] for r in runs) for k in runs[0]),default=0.)


def propose_cutoff(rows):
    positive=[r for r in rows if r['label']=='supported']
    negative=[r for r in rows if r['label'] in ('unsupported','partial')]
    scores=[r['score'] for r in negative if r['score'] is not None]
    cutoff=math.nextafter(max(scores),math.inf) if scores else 0.
    return {'cutoff':cutoff,'comparison':'>=','status':'proposal_pending_reviewer; no model selected',
            'silent_accepts':sum(r['score'] is not None and r['score']>=cutoff for r in negative),
            'negative_denominator':len(negative),
            'false_blocks':sum(r['score'] is None or r['score']<cutoff for r in positive),
            'positive_denominator':len(positive),'unclear_excluded':sum(r['label']=='unclear' for r in rows)}


def prepare():
    realistic=json.loads(Path('out/v2/realistic-v1.json').read_text())
    synthetic=json.loads(Path('out/v2/synthetic-v1.json').read_text())
    rows=[]
    for c in realistic:
        if c['split']!='tune':continue
        evidence=[r['declared_quote'] for r in c['citations']]
        rows.append({'id':c['question_id']+':'+c['atomic_claim'],'split':c['split'],'set':'realistic-v1',
            'label':c['reviewer']['label'],'type':'natural','claim':c['text'],
            'evidence':'\n'.join(evidence) if evidence and all(q is not None for q in evidence) else None})
    for c in synthetic:
        if c['split']=='tune':rows.append({'id':c['item_id'],'split':c['split'],'set':'synthetic-v1',
            'label':c['label'],'type':c['type'],'claim':c['claim'],'evidence':c['evidence']})
    tune_only(rows);save('out/v2/tune-inputs.json',rows)
    return rows


def quantiles(values):
    values=sorted(values)
    if not values:return None
    def q(p):
        x=(len(values)-1)*p;a=int(x);b=min(a+1,len(values)-1)
        return values[a]+(values[b]-values[a])*(x-a)
    return dict(n=len(values),min=values[0],p05=q(.05),p50=q(.5),p95=q(.95),max=values[-1])


def run(model_name):
    # Must be set before importing any HF modules, including dynamic HHEM code.
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',CUDA_VISIBLE_DEVICES='')
    import torch
    from transformers import AutoTokenizer,AutoModelForSequenceClassification
    import transformers
    torch.set_num_threads(4);torch.set_num_interop_threads(1);torch.manual_seed(20261017)
    rows=tune_only(json.loads(Path('out/v2/tune-inputs.json').read_text()))
    dest=Path('out/v2/acquisition')/model_name
    acquisition=json.loads((dest/'acquisition.json').read_text())
    assert acquisition['status']=='downloaded'
    for file,digest in acquisition['files'].items():assert sha((dest/file).read_bytes())==digest,'MODEL_FILE_DRIFT'
    start=time.perf_counter();hhem=model_name=='hallucination_evaluation_model'
    if hhem:
        review=json.loads(Path('out/v2/remote-code-review.json').read_text())
        assert review['reviewed_before_execution'] and review['revision']==acquisition['revision']
    model=AutoModelForSequenceClassification.from_pretrained(str(dest),local_files_only=True,trust_remote_code=hhem,torch_dtype=torch.float32).cpu().eval()
    tokenizer=model.tokenzier if hhem else AutoTokenizer.from_pretrained(str(dest),local_files_only=True)
    load_time=time.perf_counter()-start
    limit=512;eligible=[];scores=[];latencies=[]
    def tokenize(batch):
        if hhem:
            text=[model.prompt.format(text1=r['evidence'],text2=r['claim']) for r in batch]
            return tokenizer(text,padding=True,truncation=False,return_tensors='pt')
        return tokenizer([r['evidence'] for r in batch],[r['claim'] for r in batch],padding=True,truncation=False,return_tensors='pt')
    for r in rows:
        if r['evidence'] is None:scores.append({**r,'score':None,'status':'unresolved_evidence'});continue
        inputs=tokenize([r]);length=inputs['input_ids'].shape[1]
        if length>limit:scores.append({**r,'score':None,'status':'model_input_overflow','tokens':length});continue
        eligible.append(r)
    def score_pass(batch_size,reverse=False):
        output={};order=list(reversed(eligible)) if reverse else eligible
        for i in range(0,len(order),batch_size):
            batch=order[i:i+batch_size]
            if reverse and len(batch)==1 and len(order)>1:batch=batch+[order[0]]
            started=time.perf_counter();inputs=tokenize(batch)
            with torch.inference_mode():prob=torch.softmax(model(**inputs).logits,dim=-1)[:,1].float().tolist()
            elapsed=time.perf_counter()-started
            for r,p in zip(batch,prob):
                if r['id'] not in output:output[r['id']]=p
            if batch_size==1 and not reverse:latencies.append(elapsed)
        return output
    # Calibrate before thresholds/equivalence; no proposed equivalence tolerance here.
    first=score_pass(1);save(f'out/v2/{model_name}-self-variation-pass1.json',first)
    second=score_pass(1);save(f'out/v2/{model_name}-self-variation-pass2.json',second)
    third=score_pass(2,True);noise=variation(first,second,third)
    save(f'out/v2/{model_name}-self-variation-pass3.json',third)
    for r in eligible:scores.append({**r,'score':first[r['id']],'status':'scored'})
    groups=defaultdict(list)
    for r in scores:
        for key in (r['set']+'/label/'+r['label'],r['set']+'/type/'+r['type']):groups[key].append(r['score'])
    summary={'model':acquisition['repo'],'revision':acquisition['revision'],'dtype':'fp32','device':'cpu','threads':{'intra_op':4,'inter_op':1},
        'environment':{'torch':torch.__version__,'transformers':transformers.__version__},'offline':True,'check_scored':0,
        'input_sha256':sha(Path('out/v2/tune-inputs.json').read_bytes()),'load_seconds':load_time,
        'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'latency_seconds':quantiles(latencies),
        'latency_scope':'per-pair tokenize+forward across both identical single-pair fp32 reference passes; excludes load, preflight, different-batch pass and other resident processes',
        'self_variation':{'identical_passes':2,'different_batch_composition':2,'max_score_delta':noise,'pairs':len(first)},
        'token_limit':limit,'no_truncation':True,'coverage':{'total':len(rows),'scored':len(eligible),'unavailable':len(rows)-len(eligible)},
        'distributions':{k:{'scores':quantiles([v for v in vs if v is not None]),'unavailable':vs.count(None)} for k,vs in groups.items()},
        'pooled_proposal':propose_cutoff(scores),
        'per_set_proposals':{s:propose_cutoff([r for r in scores if r['set']==s]) for s in {r['set'] for r in scores}},
        'scope':'Raw L4 claim-bundle pilot only; rules not bypassed for product receipts. No final sentence or check measurement; no equivalence/export or model selection.'}
    save(f'out/v2/{model_name}-scores.json',scores);save(f'out/v2/{model_name}-pilot.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('model',choices=['prepare','MiniCheck-RoBERTa-Large','hallucination_evaluation_model']);args=parser.parse_args()
    if args.model=='prepare':print(len(prepare()))
    else:
        try:print(json.dumps(run(args.model),indent=2))
        except Exception as e:
            import traceback
            error={'status':'DEFERRED','model':args.model,'error':str(e),'type':type(e).__name__,'traceback':traceback.format_exc(),'check_scored':0}
            save(f'out/v2/{args.model}-pilot.json',error);print(json.dumps(error,indent=2))
