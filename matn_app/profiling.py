"""Opt-in local stage profiles, with model statistics separate from Python time.

No prompts, quotes, generated text or token IDs are copied into the summary.
Inclusive stage times overlap; they must never be added as exclusive totals.
"""
from __future__ import annotations

from contextlib import contextmanager
import functools
import importlib
import inspect
import json
from pathlib import Path
import sys
import threading
import time

from .store import read, write

STAGES = {
    "pdf_text_extraction": ("matn_reading.pdf_page", "OpenPdf.page"),
    "ocr": ("matn_reading.ocr.route", "read_scan_page"),
    "reading_cleaning": ("matn_reading.read", "reading_from_pages"),
    "structure_assembly": ("matn_reading.structure.document", "assemble"),
    "chunking": ("matn_reading.structure.chunks", "build_chunks"),
    "chunk_preparation": ("matn_rag.ingest", "prepare"),
    "embedding": ("matn_rag.embedding", "Embedder.embed"),
    "source_index_writes": ("matn_rag.sqlite", "SQLiteRepository.add_source"),
    "vector_writes": ("matn_rag.sqlite", "SQLiteRepository.put_embedding"),
    "vector_links": ("matn_rag.sqlite", "SQLiteRepository.link_embedding"),
    "overview_selection_verification": ("matn_app.evidence", "_pdf_catalog"),
    "overview_formatting": ("matn_app.evidence", "_overview"),
    "retrieval": ("matn_rag.search", "Search.query"),
    "candidate_selection": ("matn_chat.block_rank", "LexicalBlockRanker.rank"),
    "context_selection": ("matn_chat.reliable", "pack_ranked"),
    "native_verification": ("matn_verification.l4", "L4Adapter.check"),
}


class StageTimers:
    """Time only stage boundaries, avoiding per-Python-call profiler overhead.

    Wrappers preserve arguments, results and exceptions and are removed on exit.
    Source files, verification policies and model payloads are never changed.
    """
    def __init__(self):
        self.stages = {name: dict(calls=0, self_seconds=0., inclusive_seconds=0.) for name in STAGES}
        self.restores = []
        self.local = threading.local()
        self.lock = threading.Lock()

    def patch(self, owner, name, value):
        self.restores.append((owner, name, inspect.getattr_static(owner, name)))
        setattr(owner, name, value)

    def install(self):
        modules = {module: importlib.import_module(module) for module, _ in STAGES.values()}
        for name, (module, path) in STAGES.items():
            owner = modules[module]
            for component in path.split(".")[:-1]:
                owner = getattr(owner, component)
            attribute = path.split(".")[-1]
            function = getattr(owner, attribute)
            def wrap(fn, stage):
                @functools.wraps(fn)
                def measured(*args, **kwargs):
                    stack = getattr(self.local, "stack", [])
                    self.local.stack = stack
                    frame = dict(children=0.)
                    stack.append(frame)
                    start = time.monotonic()
                    try:
                        return fn(*args, **kwargs)
                    finally:
                        elapsed = time.monotonic() - start
                        stack.pop()
                        if stack:
                            stack[-1]["children"] += elapsed
                        with self.lock:
                            row = self.stages[stage]
                            row["calls"] += 1
                            row["inclusive_seconds"] += elapsed
                            row["self_seconds"] += max(0., elapsed - frame["children"])
                return measured
            measured = wrap(function, name)
            self.patch(owner, attribute, measured)
            # Already-imported function aliases (e.g. document.build_chunks)
            # must use the same timer; later imports naturally see the wrapper.
            if inspect.ismodule(owner):
                for module_name, loaded in list(sys.modules.items()):
                    if module_name.startswith("matn_") and loaded is not None:
                        for alias, value in list(vars(loaded).items()):
                            if value is function:
                                self.patch(loaded, alias, measured)
            if name == "context_selection":
                self.patch(modules[module].ReliableChatEngine, "_select_handles", staticmethod(measured))

    def restore(self):
        for owner, name, value in reversed(self.restores):
            setattr(owner, name, value)


def summarize(stages, folder, wall_seconds):
    folder = Path(folder)
    sources = []
    roots=read(folder/'profile-sources.json',None)
    for source in sorted(map(Path,roots)) if roots is not None else sorted((folder / "sources").glob("*")):
        progress = read(source / "progress.json", {})
        events = [json.loads(line) for line in (source / "events.jsonl").read_text().splitlines()] if (source / "events.jsonl").exists() else []
        events=[r for r in events if r.get('time',0)>=time.time()-wall_seconds-1]
        ocr = []
        if (source / "digital.json.gz").exists():
            from matn_chat.readiness import load_page
            from matn_reading.structure.cache import OCR_ROUTES
            for page in load_page(source / "digital.json.gz")["pages"]:
                if page["route"] in OCR_ROUTES:
                    ocr.append(dict(page=page["page_index"] + 1, route=page["route"], reasons=page["reasons"],
                                    text_layer_characters=sum(len(b["block"]["text"]) for b in page["blocks"])))
        batches = [r for r in events if r["stage"] == "embedding_batch"]
        sources.append(dict(id=source.name, pages=progress.get("total_pages"), status=progress.get("status"),
                            embedding=progress.get("embedding"), embedding_batch_size=8,
                            embedding_batches=len(batches), embedding_seconds=sum(r["seconds"] for r in batches),
                            extraction_seconds=sum(r["seconds"] for r in events if r["stage"] == "page_extracted"),
                            ocr_decisions=ocr,
                            ocr_seconds=sum(r["seconds"] for r in events if r["stage"] == "ocr_page")))
    receipts = read(folder / "answer-receipts.json", {})
    generations = []
    for attempt in receipts.get("trace", []):
        if not attempt.get("payload"):
            continue
        raw = attempt.get("raw", {})
        final = raw.get("final_statistics", raw)
        final = final if isinstance(final, dict) else {}
        def seconds(key):
            value = final.get(key)
            return value / 1e9 if type(value) in (int, float) else None
        generations.append(dict(attempt=attempt["attempt"], prompt_characters=len(attempt["payload"]["prompt"]),
                                prompt_tokens=final.get("prompt_eval_count"), output_tokens=final.get("eval_count"),
                                prompt_eval_seconds=seconds("prompt_eval_duration"), generation_seconds=seconds("eval_duration"),
                                load_seconds=seconds("load_duration"), first_content_seconds=raw.get("first_content_seconds"),
                                selection=attempt.get("catalog_selection"), error=attempt.get("error")))
    return dict(schema_version=1, wall_seconds=wall_seconds, timing_scope="inclusive; stages overlap",
                stages=stages, sources=sources, generations=generations,
                answer_timings=receipts.get("response", {}).get("timings"),
                answer_state=receipts.get("response", {}).get("state"),
                answer_error=receipts.get("response", {}).get("error"))


@contextmanager
def collect(folder, *, enabled=False):
    if not enabled:
        yield
        return
    timers = StageTimers()
    start = time.monotonic()
    try:
        timers.install()
        yield
    finally:
        timers.restore()
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        write(folder / "profile.json", summarize(timers.stages, folder, time.monotonic() - start))
