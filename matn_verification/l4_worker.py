"""Isolated worker: no torch/transformers imports in the main environment."""
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time
from .l4_files import validate_files, validate_foundation


def score_pair(model,tokenizer,evidence,text,hhem,torch):
    start=time.perf_counter()
    args=([model.prompt.format(text1=evidence,text2=text)],) if hhem else ([evidence],[text])
    inputs=tokenizer(*args,padding=True,truncation=False,return_tensors='pt')
    n=inputs['input_ids'].shape[1]
    if n>512:return {'protocol':1,'status':'overflow','tokens':n}
    with torch.inference_mode():score=torch.softmax(model(**inputs).logits,dim=-1)[0,1].float().item()
    return {'protocol':1,'status':'scored','score':score,'tokens':n,'seconds':time.perf_counter()-start}


def main():
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',CUDA_VISIBLE_DEVICES='')
    error=None;meta={}
    try:
        import torch
        from transformers import AutoTokenizer,AutoModelForSequenceClassification
        torch.set_num_threads(4);torch.set_num_interop_threads(1);torch.manual_seed(20261017)
        root=Path(sys.argv[1]);manifest_bytes=(root/'acquisition.json').read_bytes()
        approved={
            'MiniCheck-RoBERTa-Large':'ca617cb5d612c538fc02db7ba732e39b0d40bcef8e08137cf459fb6818d3b026',
            'hallucination_evaluation_model':'63ce4e9f6e7f0581200260ca90922d77737d9f910a55b8ed65120c152bd0032d',
        }
        if hashlib.sha256(manifest_bytes).hexdigest()!=approved.get(root.name):raise ValueError('model manifest drift')
        manifest=json.loads(manifest_bytes);validate_files(root,manifest)
        hhem=manifest['repo']=='vectara/hallucination_evaluation_model'
        if hhem:
            review=json.loads(Path('out/v2/remote-code-review.json').read_text())
            if not review['reviewed_before_execution'] or review['revision']!=manifest['revision']:raise ValueError('HHEM review missing')
            foundation_bytes=Path('out/v3/foundation-acquisition.json').read_bytes()
            if hashlib.sha256(foundation_bytes).hexdigest()!='aceb987a97782e02bc6c9224e891d7cad9ea8daa757922f6f9c5568471c0e935':raise ValueError('foundation manifest drift')
            foundation=json.loads(foundation_bytes)
            validate_foundation(foundation)
        start=time.perf_counter()
        model=AutoModelForSequenceClassification.from_pretrained(str(root),local_files_only=True,trust_remote_code=hhem,torch_dtype=torch.float32).cpu().eval()
        tokenizer=model.tokenzier if hhem else AutoTokenizer.from_pretrained(str(root),local_files_only=True)
        meta={'model_id':manifest['repo'],'revision':manifest['revision'],'file_hashes':{**manifest['files'],**({'foundation/'+k:v['sha256'] for k,v in foundation['files'].items()} if hhem else {})},
              'foundation':foundation if hhem else None,'load_seconds':time.perf_counter()-start}
    except Exception as exc:
        error={'protocol':1,'status':'model_unavailable','error':str(exc),'error_type':type(exc).__name__}
    for line in sys.stdin:
        try:
            p=json.loads(line)
            if p.get('protocol')!=1 or not isinstance(p.get('text'),str) or not isinstance(p.get('evidence'),str):raise ValueError('invalid request')
            r=error or score_pair(model,tokenizer,p['evidence'],p['text'],hhem,torch)
            r={**r,**meta,'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
        except Exception as exc:r={'protocol':1,'status':'invalid','error':str(exc)}
        print(json.dumps(r,allow_nan=False),flush=True)


if __name__=='__main__':main()
