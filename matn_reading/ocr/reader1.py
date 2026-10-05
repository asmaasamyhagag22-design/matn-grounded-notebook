"""Reader 1 client: starts the RapidOCR worker in ``.venv-ocr-rapid`` and talks JSON lines with it.

Standard library only, so the worker process can import ``load_settings`` and ``check_models`` too. The worker
refuses to start when a model file is missing or its sha256 differs from ``rapidocr_settings.json``.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SETTINGS = Path(__file__).with_name("rapidocr_settings.json")
WORKER_PYTHON = REPO / ".venv-ocr-rapid" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def load_settings() -> dict:
    return json.loads(SETTINGS.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_models(settings: dict, model_dir: Path | None = None) -> list[str]:
    """Problems with the local model files (empty list = every file present with the pinned sha256)."""
    folder = model_dir or REPO / settings["model_dir"]
    problems = []
    for name, expected in settings["model_sha256"].items():
        path = folder / name
        if not path.is_file():
            problems.append(f"{name}: missing in {folder}")
        elif _sha256(path) != expected:
            problems.append(f"{name}: sha256 differs from rapidocr_settings.json")
    return problems


class WorkerError(RuntimeError):
    pass


class RapidOcrWorker:
    """``with RapidOcrWorker() as worker: worker.read(png_path)`` -> {"lines": [...], "seconds": ...}."""

    def __init__(self, python: Path = WORKER_PYTHON):
        self.python = python
        self.process: subprocess.Popen | None = None
        self.ready: dict = {}
        self.log = None

    def __enter__(self) -> "RapidOcrWorker":
        if not self.python.is_file():
            raise WorkerError(f"reader 1 venv missing: {self.python} (docs/ocr_setup.md section 8.2)")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        self.log = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        self.process = subprocess.Popen(
            [str(self.python), "-m", "matn_reading.ocr.worker"], cwd=REPO, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=self.log, text=True, encoding="utf-8", bufsize=1)
        self.ready = self._receive()
        if not self.ready.get("ready"):
            raise WorkerError(f"reader 1 worker did not start: {self.ready}")
        return self

    def _receive(self) -> dict:
        assert self.process is not None and self.process.stdout is not None
        line = self.process.stdout.readline()
        if not line:
            raise WorkerError(f"reader 1 worker exited with code {self.process.wait(timeout=30)}: {self.log_tail()}")
        return json.loads(line)

    def log_tail(self, chars: int = 2000) -> str:
        if self.log is None:
            return ""
        self.log.seek(0)
        return self.log.read()[-chars:]

    def read(self, image_path: Path) -> dict:
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write(json.dumps({"image": str(Path(image_path).resolve())}) + "\n")
        self.process.stdin.flush()
        reply = self._receive()
        if not reply.get("ok"):
            raise WorkerError(f"reader 1 failed on {image_path}: {reply.get('error')}")
        return reply

    def __exit__(self, *exc) -> None:
        if self.process is None:
            return
        try:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.kill()
        finally:
            if self.process.stdout:
                self.process.stdout.close()
            if self.log:
                self.log.close()
