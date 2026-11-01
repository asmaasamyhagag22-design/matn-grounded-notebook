"""One heavy job across all conversations, including a durable queue message."""
from __future__ import annotations

import fcntl
import queue
import secrets
import threading
import time


class Jobs:
    def __init__(self, store):
        self.store = store
        self.tasks = queue.Queue()
        self.background = queue.Queue()
        self.active = None
        self.stopping = threading.Event()
        self.handle = (store.root / "app.lock").open("a")
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            raise ValueError("Another Matn app is using this data folder") from None
        store.recover()
        self.thread = threading.Thread(target=self._work, daemon=True, name="matn-one-heavy-job")
        self.thread.start()
        self.background_thread = threading.Thread(target=self._work, args=(self.background,), daemon=True,
                                                  name='matn-background-reading')
        self.background_thread.start()

    def submit(self, conversation, kind, action):
        if self.stopping.is_set():
            raise RuntimeError("The app is stopping; retry after restarting")
        job = dict(id=secrets.token_hex(10), kind=kind, status="queued", created_at=time.time())
        self.store.update(conversation, lambda v: v["jobs"].append(job))
        self.store.event(conversation, "step", dict(job=job["id"], summary="Queued — another heavy job is running" if self.active or not self.tasks.empty() else "Queued", kind=kind))
        lane = self.background if kind == 'Reading files' else self.tasks
        lane.put((conversation, job, action))
        return job

    def _set(self, conversation, job, **values):
        self.store.update(conversation, lambda v: next(j for j in v["jobs"] if j["id"] == job["id"]).update(values))

    def _work(self, tasks=None):
        tasks = self.tasks if tasks is None else tasks
        while not self.stopping.is_set():
            try:
                conversation, job, action = tasks.get(timeout=.2)
            except queue.Empty:
                continue
            if self.stopping.is_set():
                self._set(conversation, job, status="interrupted", ended_at=time.time())
                tasks.task_done()
                continue
            self.active = job["id"]
            started = time.time()
            self._set(conversation, job, status="running", started_at=started,
                      queue_seconds=started - job["created_at"])
            def emit(summary):
                self.store.event(conversation, "step", dict(job=job["id"], summary=summary, kind=job["kind"]))
            try:
                emit("Working…")
                action(job, emit)
                self._set(conversation, job, status="interrupted" if self.stopping.is_set() else "complete", ended_at=time.time())
            except Exception as exc:
                status = "interrupted" if self.stopping.is_set() else "failed"
                self._set(conversation, job, status=status, ended_at=time.time(), error=str(exc)[:500])
                self.store.message(conversation, "assistant", "This step stopped: " + str(exc)[:500] + ". Saved partial artifacts and earlier verified evidence remain available.", kind=status)
            finally:
                self.active = None
                self.store.event(conversation, "change", "Job finished")
                tasks.task_done()

    def close(self):
        self.stopping.set()
        self.thread.join(timeout=2)
        self.background_thread.join(timeout=2)
        if self.thread.is_alive() or self.background_thread.is_alive():
            raise RuntimeError("A job is still running; stop its subprocess before closing the app")
        for tasks in (self.tasks, self.background):
            self._interrupt_queue(tasks)
        fcntl.flock(self.handle, fcntl.LOCK_UN)
        self.handle.close()

    def _interrupt_queue(self, tasks):
        while True:
            try:
                conversation, job, _ = tasks.get_nowait()
            except queue.Empty:
                break
            self._set(conversation, job, status="interrupted", ended_at=time.time())
            self.store.event(conversation, "change", "Queued job interrupted; retry explicitly")
            tasks.task_done()
