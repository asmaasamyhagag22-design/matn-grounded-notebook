"""Process-safe model ownership; foreground answers precede the next OCR page.

flock releases ownership after crashes. No stale-lock deletion or overlapping
generator/native/OCR model families is needed to dispatch a question promptly.
"""
from contextlib import contextmanager, nullcontext
import fcntl
import os
from pathlib import Path
import time


@contextmanager
def lease(*, foreground=False, root=None):
    root = root or os.environ.get('MATN_MODEL_GATE')
    if not root:
        with nullcontext():
            yield 0.
        return
    folder = Path(root)
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with (folder / 'foreground.lock').open('a') as intent, (folder / 'model.lock').open('a') as model:
        # Shared intent spans background ownership, so a foreground waiter
        # blocks later readers once the bounded current page releases it.
        fcntl.flock(intent, fcntl.LOCK_EX if foreground else fcntl.LOCK_SH)
        fcntl.flock(model, fcntl.LOCK_EX)
        if not foreground:
            fcntl.flock(intent, fcntl.LOCK_UN)
        try:
            yield time.monotonic() - started
        finally:
            fcntl.flock(model, fcntl.LOCK_UN)
            fcntl.flock(intent, fcntl.LOCK_UN)
