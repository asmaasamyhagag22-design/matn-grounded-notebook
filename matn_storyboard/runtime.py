"""Local generation/native checks with durable attempts, caps and exact bindings."""
import json
from pathlib import Path
import time
from matn_chat.engine import MiniCheck
from matn_chat.generation import LocalGenerator
from matn_chat.memory import sample_memory
from matn_chat.readiness import write
from matn_verification.contracts import Check
from .core import digest


class Calls:
    def __init__(self, folder, *, phase='experiments'):
        self.phase=phase
        self.folder = Path(folder); self.path=self.folder/'ledger.json'
        self.rows=[]; self.journal=self.folder/'calls.json'
        if self.journal.exists(): self.rows=json.loads(self.journal.read_bytes())

    def call_timeout(self, kind, remaining):
        return 420 if kind=='generation' else 180

    def call_limit(self, kind):
        return {'generation': 4, 'native': 64}[kind]

    def reserve(self, kind, binding):
        ledger=json.loads(self.path.read_bytes())
        if kind=='generation' and self.phase!='experiments':raise ValueError('NO_GENERATION_IN_VALIDATION')
        guarded_deadline=None
        if 'phase_guard' in ledger:
            from .budget import phase_checkpoint
            guarded_deadline=phase_checkpoint(self.folder,self.phase)
        deadline=ledger['validation_deadline' if self.phase=='validation' else 'experiment_deadline']
        if guarded_deadline is not None:deadline=min(deadline,guarded_deadline)
        remaining=deadline-time.time()
        limit=self.call_limit(kind)
        # A new job must fit its timeout with a small save/termination allowance.
        timeout=self.call_timeout(kind,remaining)
        if remaining<timeout+5 or ledger['calls'][kind]>=limit:
            raise TimeoutError('CALL_OR_EXPERIMENT_BUDGET')
        memory=sample_memory()
        minimum=(512 if kind=='native' and memory['l4_worker_rss_bytes'] else 1536)*1024**2
        # Observability only: the threshold and the value it saw, pass or refuse.
        with (self.folder/'memory-guard.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(kind=kind,at=memory.get('wall',time.time()),threshold_bytes=minimum,
                available_bytes=memory['available_bytes'],ollama_runner_rss_bytes=memory.get('ollama_runner_rss_bytes'),
                l4_worker_rss_bytes=memory.get('l4_worker_rss_bytes'),allowed=memory['available_bytes']>=minimum))+'\n')
        if memory['available_bytes']<minimum:
            raise MemoryError('DEFERRED_MEMORY_BEFORE_'+kind.upper())
        ledger['calls'][kind]+=1; write(self.path,ledger)
        row=dict(kind=kind, ordinal=ledger['calls'][kind], binding=binding,
                 started_at=time.time(), complete=False)
        self.rows.append(row); write(self.journal,self.rows); return row

    def finish(self,row,**result):
        row.update(result,seconds=time.time()-row['started_at']);write(self.journal,self.rows)


class DrainedGenerationTimeout(TimeoutError):
    """Failed attempt counted; a confirmed zero-inference unload drained it."""


def unload(calls):
    start=time.time();row=dict(kind='model_unload',started_at=start,complete=False,
        purpose='serialize lifecycle and release generator memory before native verification',fresh_inference=False)
    calls.rows.append(row);write(calls.journal,calls.rows)
    try:
        client=LocalGenerator(timeout=20)
        client.deadline=json.loads(calls.path.read_bytes())['experiment_deadline']
        raw=client.request('/api/generate',dict(model=__import__('matn_chat.generation',fromlist=['MODEL']).MODEL,keep_alive=0))
        if not raw.get('done') or raw.get('done_reason')!='unload':raise ValueError('UNLOAD_NOT_CONFIRMED')
        calls.finish(row,complete=True,raw=raw);return True
    except BaseException as exc:
        calls.finish(row,error=repr(exc));return False


class Generator(LocalGenerator):
    def __init__(self,calls):
        super().__init__(timeout=420);self.journal=calls
        self.deadline=json.loads(calls.path.read_bytes())['experiment_deadline']
    def generate(self,body):
        row=self.journal.reserve('generation',dict(payload_sha256=digest(body),payload=body))
        try:
            raw=super().generate(body);self.journal.finish(row,complete=True,raw=raw)
            if not unload(self.journal):raise MemoryError('GENERATOR_UNLOAD_FAILED')
            return raw
        except BaseException as exc:
            self.journal.finish(row,error=repr(exc))
            if isinstance(exc,TimeoutError) and unload(self.journal):
                raise DrainedGenerationTimeout(str(exc)) from exc
            raise


class Native(MiniCheck):
    def __init__(self,calls,identity):
        super().__init__();self.journal=calls;self.identity=identity
    def check(self,text,evidence,target):
        binding=dict(identity=self.identity,text=text,target=target,
                     evidence=[e.model_dump(mode='json') for e in evidence])
        try: row=self.journal.reserve('native',binding)
        except (TimeoutError,MemoryError):
            return Check(target=target,layer='L4',verdict='unknown',reasons=('model_unavailable',))
        try:
            result=super().check(text,evidence,target)
            self.journal.finish(row,complete=True,check=result.model_dump(mode='json'));return result
        except BaseException as exc:
            self.journal.finish(row,error=repr(exc));raise
