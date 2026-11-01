"""One isolated evidence job: python -m matn_app.evidence_worker REQUEST.json.

The request's ``output`` names the result JSON, written atomically even on failure.
No stdout contains model responses or source excerpts; app SSE consumes summaries.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import time

from .evidence import run_request, _write
from .profiling import collect
from .model_gate import lease
from contextlib import nullcontext


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        raise SystemExit("Usage: python -m matn_app.evidence_worker REQUEST.json")
    request = json.loads(Path(args[0]).read_bytes())
    output = Path(request["output"])
    started = time.monotonic()
    def stopped(signum, frame):
        # Publish before model/reader cleanup: the app's process-group watchdog
        # may need to escalate after a short grace period.
        partial = Path(request["workdir"]) / "partial-result.json"
        retained = json.loads(partial.read_bytes()) if partial.exists() else dict(
            catalogs=request.get("catalogs", []), documents=request.get("documents", []),
            notebooks=request.get("notebooks", []))
        _write(output, dict(operation=request.get("operation"), status="interrupted",
                            text="The source job was interrupted; completed evidence is retained.",
                            citations=[], partial=retained, failures=[dict(error="SIGTERM", detail="Job interrupted")],
                            metrics=dict(seconds=round(time.monotonic() - started, 3))))
        raise KeyboardInterrupt("SIGTERM")
    previous = signal.signal(signal.SIGTERM, stopped)
    try:
        with collect(request["workdir"], enabled=os.environ.get("MATN_PROFILE") == "1"):
            gate = lease(foreground=True) if request.get('operation') == 'answer' and not request.get('fake') else nullcontext(0.)
            with gate as waiting:
                value = run_request(request)
                value.setdefault('metrics', {})['resource_wait_seconds'] = waiting
    except BaseException as exc:
        partial = Path(request["workdir"]) / "partial-result.json"
        value = dict(operation=request.get("operation"), status="interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed",
                     text="The source job stopped. Completed evidence is retained.", citations=[],
                     failures=[dict(error=type(exc).__name__, detail=str(exc)[:300])],
                     partial=json.loads(partial.read_bytes()) if partial.exists() else None,
                     metrics=dict(seconds=round(time.monotonic() - started, 3)))
        _write(output, value)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)
    _write(output, value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
