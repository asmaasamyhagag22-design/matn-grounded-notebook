"""Local readiness and isolated subprocess execution; never search during startup."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time

from .store import read, write

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = Path(os.environ.get("MATN_VAULT_ROOT", str(ROOT))).resolve()
DATA_ROOT = Path(os.environ.get("MATN_WORK_ROOT", str(ROOT / ".matn-data"))).resolve()


def drain_generator(client):
    """Bounded unload confirmation, including after a disconnected model call."""
    from matn_chat.generation import MODEL
    from matn_chat.memory import sample_memory
    previous = getattr(client, 'deadline', None)
    client.deadline = time.time() + 25
    try:
        raw = client.request("/api/generate", {"model": MODEL, "keep_alive": 0})
        if not raw.get("done") or raw.get("done_reason") != "unload":
            raise RuntimeError("MODEL_UNLOAD_UNCONFIRMED")
        while time.time() < client.deadline:
            if not client.request("/api/ps").get("models") and not sample_memory()["ollama_runner_rss_bytes"]:
                return
            time.sleep(.1)
        raise RuntimeError("MODEL_DRAIN_UNCONFIRMED")
    finally:
        # Unload has its own deadline; it must not replace the turn's budget
        # before an existing failed-only redraft after native verification.
        if previous is None:
            del client.deadline
        else:
            client.deadline = previous


def preflight(*, fake=False, search_budget=0):
    rows = []
    for module in ("pydantic", "pptx", "pdfplumber", "pypdfium2", "PIL"):
        rows.append(dict(check=module, ok=importlib.util.find_spec(module) is not None))
    rows.append(dict(check="LibreOffice", ok=bool(shutil.which("libreoffice"))))
    try:
        from matn_deck.measure import verify_fonts
        problems = verify_fonts()
        rows.append(dict(check="Pinned OFL fonts", ok=not problems, detail=", ".join(problems)))
    except Exception as exc:
        rows.append(dict(check="Pinned OFL fonts", ok=False, detail=str(exc)[:200]))
    model = dict(verdict="NO-GO", detail="Local model has not been checked")
    if fake:
        model = dict(verdict="FIXTURE", detail="Fixture mode — no real model or searches")
    else:
        try:
            from matn_research.preflight import local
            from matn_chat.generation import MODEL, GENERATOR_DIGEST
            tags = local("/api/tags", timeout=3).get("models", [])
            ok = any(m["name"] == MODEL and m["digest"] == GENERATOR_DIGEST for m in tags)
            model = dict(verdict="GO" if ok else "NO-GO", detail="Pinned local qwen3.5:9b" if ok else "Pinned generator missing")
        except Exception as exc:
            model = dict(verdict="NO-GO", detail="Ollama: " + type(exc).__name__)
    return dict(verdict="GO" if all(r["ok"] for r in rows) else "NO-GO", checks=rows, model=model,
                scope="LOCAL: files, replay and deck rendering; provider quota is checked only on explicit research start",
                search_budget=search_budget, search_calls=0, fake=fake)


class Processes:
    def __init__(self):
        self.current = None
        self.children = set()
        self.lock = threading.Lock()
        self.stopped = False

    def run(self, command, folder, emit, *, cwd=ROOT, progress=None, timeout=1800, idle_timeout=600):
        # The evidence worker takes its own answer lease and yields OCR per
        # page. Other foreground pipelines own the lease for their process
        # lifetime, so research/plan/deck jobs cannot overlap background OCR.
        module=str(command[list(command).index('-m')+1]) if '-m' in command else ''
        from contextlib import nullcontext
        from .model_gate import lease
        gated=module.startswith('matn_') and module!='matn_app.evidence_worker'
        with lease(foreground=True,root=os.environ.get('MATN_MODEL_GATE',str(DATA_ROOT/'model-gate'))) if gated else nullcontext():
            return self._run(command,folder,emit,cwd=cwd,progress=progress,timeout=timeout,idle_timeout=idle_timeout)

    def _run(self, command, folder, emit, *, cwd=ROOT, progress=None, timeout=1800, idle_timeout=600):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, PYTHONPATH=str(cwd), PYTHONDONTWRITEBYTECODE="1")
        env.setdefault('MATN_MODEL_GATE', str(DATA_ROOT / 'model-gate'))
        started = time.monotonic()
        last = None
        changed = started
        with (folder / "worker.log").open("w") as log:
            with self.lock:
                if self.stopped:
                    raise RuntimeError("App is stopping")
                process = subprocess.Popen([str(x) for x in command], cwd=cwd, env=env,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                self.current = process
                self.children.add(process)
            try:
                while process.poll() is None:
                    if timeout is not None and time.monotonic() - started > timeout:
                        self._terminate(process)
                        raise TimeoutError("Job time limit reached")
                    if timeout is None and time.monotonic() - changed > idle_timeout:
                        self._terminate(process)
                        raise TimeoutError('No source progress; checkpoints retained for retry')
                    if progress:
                        value = progress()
                        signature = json.dumps(value, sort_keys=True, default=str)
                        if signature != last:
                            changed = time.monotonic()
                            emit(value)
                            last = signature
                    time.sleep(.3)
                return process.returncode
            finally:
                # Every child/sidecar is in the same session as its parent.
                self._terminate(process)
                with self.lock:
                    self.children.discard(process)
                    self.current = next(iter(self.children), None)

    @staticmethod
    def _terminate(process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)

    def close(self):
        with self.lock:
            self.stopped = True
            for process in list(self.children):
                self._terminate(process)


def safe_progress(folder):
    value = read(Path(folder) / "progress.json", {})
    source=value.get('source')
    if source:
        state=read(Path(source)/'progress.json',{})
        if state.get('total_pages'):
            value.update(total=state['total_pages'],completed=len(state.get('extracted_pages',[])),
                         pages=len(state.get('ocr_pages',[])),status=state.get('status'))
            if 'ocr_required_pages' in state:value['ocr_total']=len(state['ocr_required_pages'])
        receipts=list((Path(source)/'catalogs').glob('*/verification-partial.json'))
        if receipts:
            value['units']=sum(len(read(p,{}).get('receipts',[])) for p in receipts)
        if Path(source).is_absolute():value.pop('source',None)
    verified=read(Path(folder)/'verified-progress.json',{})
    if verified.get('sentences'):
        value.update(verified=verified['sentences'])
        if value.get('stage') not in ('planning','drafting','checking'):value['stage']='Verified evidence so far'
    # Never return prompts, model responses or raw worker logs as live steps.
    return {k: value[k] for k in ("stage", "source", "file", "pages", "completed", "total", "units", "status",'verified','ocr_total','sentence','sentences_total') if k in value} or "Reading and verifying sources…"


def worker_result(folder, output):
    value = read(output)
    if value is not None:
        return value
    for line in reversed((Path(folder) / "worker.log").read_text(errors="replace").splitlines()):
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                return value
        except ValueError:
            continue
    raise ValueError("Worker did not return a result; its local log is retained")

