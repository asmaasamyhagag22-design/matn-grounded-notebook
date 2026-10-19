"""C1 → buffered atomic generation → unchanged verifier → one failed-only redraft."""
import hashlib
import json
from pathlib import Path
import time
from jsonschema import Draft202012Validator
from matn_rag.contracts import canonical
from matn_verification.rules import fingerprint, verify
from matn_verification.l4 import L4Adapter
from .handles import build_handles
from .generation import LocalGenerator, payload, PROMPT_VERSION, SCHEMA

INSUFFICIENT='Insufficient verified evidence in the selected sources.'


class MiniCheck:
    """Lazy isolated worker; a guarded collection owns its residency and cleanup."""
    def __init__(self):self.adapter=None
    def check(self,text,evidence,target):
        if self.adapter is None:
            self.adapter=L4Adapter(Path.home()/'.venvs/matn-rerank/bin/python',
                Path(__file__).resolve().parents[1]/'out/v2/acquisition/MiniCheck-RoBERTa-Large')
        return self.adapter.check(text,evidence,target)
    def close(self):
        if self.adapter is not None:
            try:self.adapter.close()
            except OSError:pass
            finally:self.adapter=None


def first_failure(receipt):
    failures=[c for c in receipt['checks'] if c['verdict']!='pass']
    first=min(failures,key=lambda c:int(c['layer'][1])) if failures else None
    return None if first is None else {k:first[k] for k in ('target','layer','verdict','reasons')}


class ChatFailure(ValueError):pass


class ChatEngine:
    def __init__(self,search,documents,*,generator=None,entailment=None,clock=time.perf_counter,memory_guard=None,token_counter=None,num_ctx=16384):
        self.memory_guard=memory_guard;self.token_counter=token_counter;self.num_ctx=num_ctx
        self.search=search;self.documents=tuple(documents);self.generator=generator or LocalGenerator()
        self.entailment=entailment if entailment is not None else MiniCheck()
        self.owns_entailment=entailment is None;self.clock=clock;self.trace=[];self.handles={};self.retrieval=None
        self.fingerprints={d.doc_id:fingerprint(d) for d in self.documents}

    def _generate(self,question,failures,timings):
        body=payload(question,self.handles,failures,num_ctx=self.num_ctx)
        entry={'attempt':len(self.trace),'redraft_slots':[f['slot'] for f in failures] if failures else [],
               'payload':body,'payload_sha256':hashlib.sha256(canonical(body)).hexdigest(),'sentences':[]}
        self.trace.append(entry)
        tokens=self.token_counter(body['prompt']) if self.token_counter else len(body['prompt'].encode())
        entry['prompt_token_budget']=tokens+body['options']['num_predict']+2048
        if entry['prompt_token_budget']>body['options']['num_ctx']:
            raise ChatFailure('context_budget_overflow')
        start=self.clock()
        entry['timings']={'verification_seconds':0.}
        try:raw=self.generator.generate(body);entry['raw']=raw
        finally:timings['generation_seconds']+=self.clock()-start
        entry['timings'].update({'prompt_eval_seconds':raw.get('prompt_eval_duration',0)/1e9,'eval_seconds':raw.get('eval_duration',0)/1e9,'generation_wall_seconds':self.clock()-start})
        if raw.get('done') is not True or raw.get('done_reason')!='stop' or raw.get('thinking'):
            raise ChatFailure('generation_incomplete')
        try:
            generated=json.loads(raw['response']);entry['parsed']=generated
            # Decode uses the enum; independent L0 must still audit a forged backend response.
            structural=json.loads(json.dumps(SCHEMA))
            structural['properties']['sentences']['maxItems']=body['format']['properties']['sentences']['maxItems']
            Draft202012Validator(structural).validate(generated)
        except Exception as exc:raise ChatFailure('schema_invalid') from exc
        return generated['sentences'],entry

    def _verify(self,sentences,entry,documents,timings,receipts):
        resolved=[]
        retrieved=[{k:c[k] for k in ('block_id','start','end')} for h in self.handles.values() for c in h['citations']]
        for i,sentence in enumerate(sentences):
            refs=[];unknown=[]
            for h in sentence['handles']:
                if h not in self.handles:unknown.append(h);continue
                refs.extend({k:c[k] for k in ('block_id','start','end','quote')} for c in self.handles[h]['citations'])
            if unknown:refs.append(dict(block_id='unknown-chat-handle',start=0,end=1))
            refs=list({(r['block_id'],r['start'],r['end']):r for r in refs}.values())
            req={'sentence':sentence['text'],'claims':[{'text':sentence['text'],'citations':refs}],
                 'selected_doc_ids':[d.doc_id for d in documents],
                 'fingerprints':{d.doc_id:self.fingerprints[d.doc_id] for d in documents},'retrieved_spans':retrieved}
            start=self.clock()
            receipt=verify(documents,req,self.entailment).model_dump(mode='json')
            seconds=self.clock()-start
            timings['verification_seconds']+=seconds
            entry['timings']['verification_seconds']+=seconds
            reasons=sorted({r for c in receipt['checks'] for r in c['reasons']})
            item={**sentence,'receipt':receipt,'first_failure':first_failure(receipt),'reasons':reasons,'unknown_handles':unknown,
                  'citations':[c for h in sentence['handles'] if h in self.handles for c in self.handles[h]['citations']]}
            entry['sentences'].append(item)
            index=len(receipts);receipts.append({'attempt':entry['attempt'],'sentence_index':i,'handles':sentence['handles'],
                                                'first_failure':item['first_failure'],'receipt':receipt})
            resolved.append((item,index))
        return resolved

    def ask(self,notebook,sources,question):
        self.trace=[];self.handles={};self.retrieval=None
        start=self.clock();timings={'retrieval_seconds':0.,'generation_seconds':0.,'verification_seconds':0.,'total_seconds':0.}
        receipts=[];kept=[];initial_count=0;total_candidates=0;error=None
        deferred=False
        try:
            if self.memory_guard is not None and not self.memory_guard.check(getattr(self.entailment,'close',lambda:None)):
                deferred=True;raise ChatFailure('deferred_memory')
            if not isinstance(question,str) or not question.strip():raise ChatFailure('invalid_question')
            self.search.repo.validate_selection(notebook,sources)
            rows=[r for r in self.search.repo.source_rows(notebook) if r['id'] in sources]
            selected_ids={r['doc_id'] for r in rows};documents=tuple(d for d in self.documents if d.doc_id in selected_ids)
            if selected_ids!={d.doc_id for d in documents}:raise ChatFailure('snapshot_missing')
            if any(json.loads(r['metadata'])['fingerprint']!=self.fingerprints[r['doc_id']] for r in rows):
                raise ChatFailure('snapshot_mismatch')
            t=self.clock();self.retrieval=self.search.query(notebook,sources,question,mode='focused',depth=10,ablation='no-prefix')
            timings['retrieval_seconds']=self.clock()-t
            self.handles=build_handles(documents,self.retrieval['hits'])
            if self.handles:
                generated,entry=self._generate(question,None,timings);initial_count=len(generated);total_candidates+=len(generated)
                try:first=self._verify(generated,entry,documents,timings,receipts)
                finally:
                    if self.owns_entailment and self.memory_guard is None:self.entailment.close()
                failed=[]
                for slot,(item,index) in enumerate(first):
                    if item['receipt']['status']=='verified':kept.append((slot,item,index))
                    else:failed.append({'slot':slot,'text':item['text'],'handles':item['handles'],'failure_codes':item['reasons']})
                if failed:
                    generated,entry=self._generate(question,failed,timings);total_candidates+=len(generated)
                    try:second=self._verify(generated,entry,documents,timings,receipts)
                    finally:
                        if self.owns_entailment and self.memory_guard is None:self.entailment.close()
                    for failure,(item,index) in zip(failed,second):
                        if item['receipt']['status']=='verified' and not any(item['text']==old['text'] for _,old,_ in kept):kept.append((failure['slot'],item,index))
        except Exception as exc:
            error=str(exc) if isinstance(exc,ChatFailure) else 'chat_error'
            if self.trace:self.trace[-1]['error']={'code':error,'type':type(exc).__name__,'detail':str(exc)}
            if not initial_count and self.trace:
                parsed=self.trace[0].get('parsed',{})
                candidates=parsed.get('sentences',[]) if isinstance(parsed,dict) else []
                initial_count=sum(isinstance(c,dict) and isinstance(c.get('text'),str) for c in candidates) if isinstance(candidates,list) else 0
                total_candidates=max(total_candidates,initial_count)
            kept=[]
        finally:
            if self.owns_entailment and self.memory_guard is None:self.entailment.close()
        # Schema-invalid outputs can still contain identifiable sentences for audit/counts.
        total_candidates=0
        for attempt in self.trace:
            parsed=attempt.get('parsed',{})
            candidates=parsed.get('sentences',[]) if isinstance(parsed,dict) else []
            if isinstance(candidates,list):
                total_candidates+=sum(isinstance(c,dict) and isinstance(c.get('text'),str) for c in candidates)
        kept.sort(key=lambda r:r[0]);sentences=[{'text':item['text'],'handles':item['handles'],'citations':item['citations'],'receipt_index':index} for _,item,index in kept]
        timings['total_seconds']=self.clock()-start
        state='deferred_memory' if deferred or error=='deferred_memory' else 'error' if error else 'answered' if sentences else 'insufficient_evidence'
        return {'schema_version':1,'prompt_version':PROMPT_VERSION,'state':state,'message':INSUFFICIENT if state=='insufficient_evidence' else 'Chat failed closed.' if error else '',
            'memory_samples':self.memory_guard.samples if self.memory_guard else [],
            'sentences':sentences,'receipts':receipts,'dropped_sentences':max(0,initial_count-len(sentences)),
            'discarded_candidates':max(0,total_candidates-len(sentences)),'error':error,'timings':timings}
