"""Current supervisor/worker lifecycle, with this journey's explicit call caps."""
import json
from pathlib import Path
import time
from contextlib import contextmanager
from matn_chat.readiness import write
from matn_chat.memory import sample_memory
from matn_chat.generation import LocalGenerator
from matn_storyboard.runtime import Calls, Generator, Native
from matn_verification.contracts import Check


def require_initialization(calls):
    from matn_storyboard.budget import phase_checkpoint
    from matn_storyboard.core import digest
    phase_checkpoint(calls.folder, calls.phase)
    ledger = json.loads(calls.path.read_bytes())
    proof = ledger.get('initial_residency')
    path = calls.folder / 'initial-residency.json'
    if not ledger.get('phase_guard', {}).get('running'):
        raise ValueError('SUPERVISED_COMMAND_REQUIRED')
    if not proof or not path.exists():
        raise RuntimeError('INITIAL_RESIDENCY_PROOF_REQUIRED')
    evidence = json.loads(path.read_bytes())
    if (proof != digest(evidence) or evidence.get('empty') is not True
            or evidence.get('command') != ledger['phase_guard']['running']
            or not ledger.get('drained')):
        raise RuntimeError('INITIAL_RESIDENCY_PROOF_INVALID')


@contextmanager
def initialized_session(calls, generator):
    """Serialize the real CLI and evaluation entry using observed residency only."""
    from matn_chat.readiness import lock
    from matn_storyboard.budget import phase_checkpoint
    from matn_storyboard.core import digest
    with lock(calls.folder / 'run.lock'):
        deadline = phase_checkpoint(calls.folder, calls.phase)
        ledger = json.loads(calls.path.read_bytes())
        if not ledger.get('phase_guard', {}).get('running'):
            raise ValueError('SUPERVISED_COMMAND_REQUIRED')
        ledger['drained'] = False
        ledger.pop('initial_residency', None)
        write(calls.path, ledger)
        evidence = dict(started_at=time.time(), command=ledger['phase_guard']['running'], empty=False)
        previous_timeout = generator.timeout
        try:
            generator.deadline = deadline
            generator.timeout = min(5, previous_timeout)
            evidence['ps'] = generator.request('/api/ps')
            evidence['memory'] = sample_memory()
            evidence['empty'] = (evidence['ps']['models'] == []
                and evidence['memory']['runners'] == [] and evidence['memory']['workers'] == [])
            if not evidence['empty'] and getattr(generator, 'resident', False):
                # Live preset: preflight may preload ONLY the pinned generation model. Nothing else may be resident.
                from matn_chat.generation import MODEL
                names = [m.get('name') for m in evidence['ps']['models']]
                evidence['preloaded_generation_model'] = names == [MODEL] and evidence['memory']['workers'] == []
                evidence['empty'] = evidence['preloaded_generation_model']
        except BaseException as exc:
            evidence['error'] = repr(exc)
            raise
        finally:
            generator.timeout = previous_timeout
            evidence['checked_at'] = time.time()
            write(calls.folder / 'initial-residency.json', evidence)
        if not evidence['empty']:
            raise RuntimeError('EXPECTED_EMPTY_MODEL_RESIDENCY')
        phase_checkpoint(calls.folder, calls.phase)
        ledger = json.loads(calls.path.read_bytes())
        ledger.update(drained=True, initial_residency=digest(evidence))
        if evidence.get('preloaded_generation_model'):
            ledger['resident'] = True
        write(calls.path, ledger)
        require_initialization(calls)
        yield


class ResearchCalls(Calls):
    def call_limit(self, kind):
        from .models import LIMITS
        if self is not None and ((self.folder / 'continuation-authorization.json').exists() or (
                self.path.exists() and json.loads(self.path.read_bytes()).get('continuation_authorization'))):
            from .authorization import accounting
            return accounting(self.folder)['additional_cap'][kind]
        return LIMITS[kind]

    def reserve(self, kind, binding):
        ledger = json.loads(self.path.read_bytes())
        if not ledger.get('phase_guard', {}).get('running'):
            raise ValueError('SUPERVISED_COMMAND_REQUIRED')
        if ledger['calls'][kind] >= self.call_limit(kind):
            raise TimeoutError('RESEARCH_CALL_CAP')
        if not ledger.get('drained', False) and not (kind == 'generation' and ledger.get('resident')):
            raise RuntimeError('GENERATOR_NOT_DRAINED')
        if kind != 'generation' and ledger.get('resident'):
            raise RuntimeError('GENERATOR_NOT_DRAINED')
        if kind == 'native' and sample_memory()['runners']:
            raise RuntimeError('GENERATION_NATIVE_OVERLAP_FORBIDDEN')
        row = super().reserve(kind, binding)
        if kind == 'generation':
            ledger = json.loads(self.path.read_bytes()); ledger['drained'] = False
            write(self.path, ledger)
        return row


class ResearchGenerator(Generator):
    """Existing NDJSON transport with separately bounded inference and cleanup.

    420s admission, 375s inference, 40s cleanup, 5s scheduling/save margin.
    Deadlines bound blocking operations; they do not promise realtime scheduling.
    Actual elapsed seconds are always recorded without rounding down.
    """
    attempt_seconds = 420
    cleanup_reserve = 45
    save_margin = 5
    resident = False  # Live preset: keep the pinned model loaded between successful generation calls.

    def _drain(self, cleanup_end):
        from matn_chat.generation import MODEL
        unloaded = self.request('/api/generate', dict(model=MODEL, keep_alive=0))
        if not unloaded.get('done') or unloaded.get('done_reason') != 'unload':
            raise RuntimeError('UNLOAD_NOT_CONFIRMED')
        self.deadline = cleanup_end
        while time.time() < cleanup_end:
            ps = self.request('/api/ps'); memory = sample_memory()
            write(self.journal.folder / 'last-drain.json', dict(ps=ps, memory=memory))
            if not ps['models'] and not memory['runners'] and not memory['workers']:
                return True
            time.sleep(min(.25, max(0, cleanup_end-time.time())))
        raise RuntimeError('GENERATOR_DRAIN_UNCONFIRMED')

    def release(self):
        """Unload and confirm the drain before native checks, embeddings or the end of a run."""
        ledger = json.loads(self.journal.path.read_bytes())
        if ledger.get('drained') and not ledger.get('resident'):
            return False
        phase_deadline = self.deadline; self.timeout = 5
        self.deadline = min(phase_deadline, time.time() + 40)
        try:
            self._drain(self.deadline)
        finally:
            self.deadline = phase_deadline
        ledger = json.loads(self.journal.path.read_bytes()); ledger.update(drained=True, resident=False)
        write(self.journal.path, ledger)
        return True

    def generate(self, body):
        import threading
        from matn_chat.streaming import StreamingGenerator
        from matn_storyboard.core import digest
        from matn_storyboard.runtime import DrainedGenerationTimeout
        start = time.monotonic()
        wall_start = time.time()
        row = self.journal.reserve('generation', dict(payload_sha256=digest(body), payload=body))
        phase_deadline = self.deadline
        self.deadline = min(phase_deadline, wall_start + self.attempt_seconds - self.cleanup_reserve)
        self.timeout = 5
        raw = None; error = None; drained = False
        self.cancel = getattr(self, 'cancel', threading.Event())
        stream_path = self.journal.folder / ('stream-' + str(row['ordinal']) + '.jsonl')
        def emit(event):
            with stream_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(event, ensure_ascii=False) + '\n'); f.flush()
        try:
            ps = self.request('/api/ps'); memory = sample_memory()
            from matn_chat.generation import MODEL
            from matn_chat.memory import MIN_AVAILABLE
            if self.resident and [m.get('name') for m in ps['models']] == [MODEL] and not memory['workers']:
                if memory['available_bytes'] < MIN_AVAILABLE:
                    raise MemoryError('RESIDENT_MEMORY_HEADROOM')
            elif ps['models'] or memory['runners'] or memory['workers']:
                raise RuntimeError('EXPECTED_EMPTY_MODEL_RESIDENCY')
            # generate_stream performs the SAME pinned digest/capability checks
            # as LocalGenerator. Its self.request honours the inference deadline.
            remaining = self.deadline - time.time()
            raw = StreamingGenerator.generate_stream(self, body, emit, total=remaining,
                        connect=min(5, remaining), read_idle=remaining, cancel=self.cancel)
        except BaseException as exc:
            error = exc
        finally:
            inference_seconds = time.monotonic() - start
            # No renewal: unload + process drain share the original attempt cap.
            cleanup_end = min(phase_deadline, wall_start + self.attempt_seconds - self.save_margin)
            self.deadline = min(cleanup_end, time.time() + 10)
            self.timeout = 5
            keep = self.resident and error is None
            if not keep:  # every failure, timeout or non-resident call still unloads and confirms the drain
                try:
                    drained = self._drain(cleanup_end)
                except BaseException as exc:
                    if error is None: error = exc
                    emit(dict(kind='cleanup_failure', error=repr(exc)))
            self.deadline = phase_deadline
            if drained or keep:
                ledger = json.loads(self.journal.path.read_bytes()); ledger.update(drained=drained, resident=keep)
                write(self.journal.path, ledger)
            elapsed = time.monotonic()-start
            if elapsed > self.attempt_seconds and error is None:
                error = TimeoutError('WHOLE_ATTEMPT_BUDGET_DEVIATION')
            self.journal.finish(row, complete=error is None, raw=raw, error=repr(error) if error else None,
                drained=drained, inference_seconds=inference_seconds,
                cleanup_seconds=elapsed-inference_seconds, actual_attempt_seconds=elapsed,
                attempt_cap_seconds=self.attempt_seconds, cleanup_reserve_seconds=self.cleanup_reserve,
                final_statistics=raw.get('final_statistics', 'unknown') if raw else 'unknown')
        if error is not None:
            if isinstance(error, TimeoutError) and drained:
                raise DrainedGenerationTimeout(str(error)) from error
            raise error
        return raw


class ResearchNative(Native):
    """Reuse exact scored pairs from THIS journal only; recompute policy gates."""
    def check(self, text, evidence, target):
        refs = [e.model_dump(mode='json') for e in evidence]
        for row in self.journal.rows:
            b = row.get('binding', {})
            if (row.get('kind') == 'native' and row.get('complete') and row.get('check', {}).get('l4')
                    and b.get('identity') == self.identity and b.get('text') == text and b.get('evidence') == refs):
                return Check.model_validate_json(json.dumps(dict(row['check'], target=target)))
        return super().check(text, evidence, target)
