"""Versioned JSON-lines boundary to an isolated, offline fp32 model process."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import selectors
import subprocess
from .contracts import Check, L4Record

from .l4_files import PINS, validate_files


def bundle_text(evidence):
    # Preserve declared evidence order; combine overlapping/adjacent spans in the same block.
    groups=[]
    for e in evidence:
        if groups and groups[-1][0]==e.block_id and groups[-1][2]>=e.start>=groups[-1][1]:
            b,a,z,q=groups[-1]
            if e.end>z:groups[-1]=(b,a,e.end,q+e.quote[max(0,z-e.start):])
        else:groups.append((e.block_id,e.start,e.end,e.quote))
    return '\n'.join(q for _,_,_,q in groups)


class L4Adapter:
    def __init__(self, python=None, model_dir=None, *, transport=None):
        self.transport=transport
        self.process=None
        if transport is None and python and model_dir:
            # No shell; dependencies remain in the owner-approved isolated environment.
            try:
                self.process=subprocess.Popen([str(python),'-m','matn_verification.l4_worker',str(model_dir)],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
            except OSError:
                self.process=None

    def close(self):
        if self.process is not None:
            self.process.stdin.close()
            try:self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:self.process.terminate();self.process.wait(timeout=10)
            self.process.stdout.close()
            self.process=None

    def _call(self,payload):
        if self.transport is not None:return self.transport(payload)
        if self.process is None: return {'protocol':1,'status':'model_unavailable'}
        self.process.stdin.write(json.dumps(payload,allow_nan=False)+'\n');self.process.stdin.flush()
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdout,selectors.EVENT_READ)
            if not selector.select(180):raise TimeoutError('L4 subprocess timeout')
        return json.loads(self.process.stdout.readline())

    def check(self,text,evidence,target):
        try:
            r=self._call({'protocol':1,'text':text,'evidence':bundle_text(evidence)})
            if r.get('protocol')!=1:raise ValueError('protocol mismatch')
            status=r.get('status')
            if status in ('model_unavailable','hash_mismatch','overflow'):
                reason='model_input_overflow' if status=='overflow' else 'model_unavailable'
                return Check(target=target,layer='L4',verdict='unknown',reasons=(reason,))
            s=r.get('score')
            if status!='scored' or type(s) not in (int,float) or not math.isfinite(s) or not 0<=s<=1:
                raise ValueError('invalid score')
            if PINS.get(r['model_id'])!=r['revision'] or not r['file_hashes']:raise ValueError('invalid identity')
            metadata=L4Record(protocol=1,model_id=r['model_id'],revision=r['revision'],file_hashes=r['file_hashes'],
                cutoff=.5,raw_score=float(s),tokens=r['tokens'],seconds=float(r['seconds']))
            return Check(target=target,layer='L4',verdict='pass' if s>.5 else 'reject',
                         reasons=() if s>.5 else ('entailment_failed',),l4=metadata)
        except (OSError,TimeoutError):
            return Check(target=target,layer='L4',verdict='unknown',reasons=('model_unavailable',))
        except Exception:
            return Check(target=target,layer='L4',verdict='unknown',reasons=('model_output_invalid',))
