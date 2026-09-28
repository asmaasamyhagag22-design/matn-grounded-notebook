"""Benchmark per-page and batched PyMuPDF4LLM calls on the same PDF pages."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import gc
import hashlib
import json
import platform
import statistics
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Sequence

import pymupdf

from inspect_pdf import (
    EXIT_INPUT_ERROR,
    EXIT_OK,
    EXIT_UNEXPECTED_ERROR,
    InspectionError,
    PageSelection,
    StagedOutput,
    open_pdf,
    sha256_file,
    utc_now,
    write_utf8_atomically,
)


STRATEGIES = ("per_page", "batched")


def structured_settings() -> dict[str, Any]:
    return {
        "page_chunks": True,
        "use_ocr": False,
        "force_ocr": False,
        "write_images": False,
        "embed_images": False,
        "header": True,
        "footer": True,
        "page_separators": False,
        "show_progress": False,
    }


def validate_chunks(
    chunks: Any, page_indices: Sequence[int]
) -> dict[int, str]:
    if not isinstance(chunks, list) or len(chunks) != len(page_indices):
        raise RuntimeError("PyMuPDF4LLM returned an unexpected number of page chunks")
    texts: dict[int, str] = {}
    for expected_index, chunk in zip(page_indices, chunks, strict=True):
        if not isinstance(chunk, dict):
            raise RuntimeError("PyMuPDF4LLM page chunk is not an object")
        metadata = chunk.get("metadata")
        text = chunk.get("text")
        expected_pdf_page = expected_index + 1
        if not isinstance(metadata, dict) or metadata.get("page_number") != expected_pdf_page:
            raise RuntimeError("PyMuPDF4LLM chunk-to-page mapping mismatch")
        if not isinstance(text, str):
            raise RuntimeError("PyMuPDF4LLM page chunk has no Markdown text")
        if expected_pdf_page in texts:
            raise RuntimeError("PyMuPDF4LLM returned a duplicate page chunk")
        texts[expected_pdf_page] = text
    return texts


def extract_per_page(document: pymupdf.Document, page_indices: Sequence[int]) -> dict[int, str]:
    import pymupdf4llm

    texts: dict[int, str] = {}
    for page_index in page_indices:
        chunks = pymupdf4llm.to_markdown(
            document,
            pages=[page_index],
            **structured_settings(),
        )
        texts.update(validate_chunks(chunks, [page_index]))
    return texts


def extract_batched(document: pymupdf.Document, page_indices: Sequence[int]) -> dict[int, str]:
    import pymupdf4llm

    chunks = pymupdf4llm.to_markdown(
        document,
        pages=list(page_indices),
        **structured_settings(),
    )
    return validate_chunks(chunks, page_indices)


def current_working_set_bytes() -> int | None:
    """Return current process working set on Windows without adding a dependency."""
    if sys.platform != "win32":
        return None

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.wintypes.DWORD),
            ("PageFaultCount", ctypes.wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    process = kernel32.GetCurrentProcess()
    ok = psapi.GetProcessMemoryInfo(
        process, ctypes.byref(counters), counters.cb
    )
    if not ok:
        return None
    return int(counters.WorkingSetSize)


def measure_call(call: Callable[[], dict[int, str]]) -> tuple[dict[int, str], dict[str, Any]]:
    gc.collect()
    baseline = current_working_set_bytes()
    samples: list[int] = []
    if baseline is not None:
        samples.append(baseline)
    stop = threading.Event()

    def sample_memory() -> None:
        while not stop.wait(0.005):
            sample = current_working_set_bytes()
            if sample is not None:
                samples.append(sample)

    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()
    started_ns = time.perf_counter_ns()
    try:
        result = call()
    finally:
        elapsed = (time.perf_counter_ns() - started_ns) / 1_000_000_000
        stop.set()
        sampler.join()
    final = current_working_set_bytes()
    if final is not None:
        samples.append(final)
    peak = max(samples) if samples else None
    return result, {
        "elapsed_seconds": elapsed,
        "working_set_before_bytes": baseline,
        "peak_working_set_bytes": peak,
        "peak_working_set_increase_bytes": (
            max(0, peak - baseline)
            if peak is not None and baseline is not None
            else None
        ),
        "memory_method": (
            "GetProcessMemoryInfo WorkingSetSize sampled every 5 ms in the same process"
            if baseline is not None
            else "unavailable on this platform"
        ),
    }


def text_digest(texts: dict[int, str]) -> str:
    digest = hashlib.sha256()
    for pdf_page, text in texts.items():
        digest.update(f"{pdf_page}\0".encode("ascii"))
        digest.update(text.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def run_benchmark(
    pdf_path: Path,
    selection: PageSelection,
    output_dir: Path,
) -> dict[str, Any]:
    if not pdf_path.is_file():
        raise InspectionError("PDF file does not exist.", EXIT_INPUT_ERROR)

    import pymupdf4llm
    import pymupdf4llm.helpers.document_layout as document_layout

    pymupdf4llm.use_layout(True)
    resolved_pdf = pdf_path.resolve(strict=True)
    run_id = str(uuid.uuid4())
    with open_pdf(resolved_pdf) as document:
        page_indices = selection.to_zero_based_indices(document.page_count)

        warmup_started = time.perf_counter_ns()
        warmup_chunks = pymupdf4llm.to_markdown(
            document,
            pages=[page_indices[0]],
            **structured_settings(),
        )
        validate_chunks(warmup_chunks, [page_indices[0]])
        warmup_elapsed = (time.perf_counter_ns() - warmup_started) / 1_000_000_000

        extractors: dict[str, Callable[[], dict[int, str]]] = {
            "per_page": lambda: extract_per_page(document, page_indices),
            "batched": lambda: extract_batched(document, page_indices),
        }
        run_order = [
            "per_page",
            "batched",
            "batched",
            "per_page",
            "per_page",
            "batched",
        ]
        runs: dict[str, list[dict[str, Any]]] = {name: [] for name in STRATEGIES}
        retained_texts: dict[str, dict[int, str]] = {}

        for strategy in run_order:
            parse_calls = 0
            original_parse_document = document_layout.parse_document

            def counted_parse_document(*args: Any, **kwargs: Any) -> Any:
                nonlocal parse_calls
                parse_calls += 1
                return original_parse_document(*args, **kwargs)

            document_layout.parse_document = counted_parse_document
            try:
                texts, measurement = measure_call(extractors[strategy])
            finally:
                document_layout.parse_document = original_parse_document

            expected_pages = list(selection.pdf_pages)
            if list(texts) != expected_pages:
                raise RuntimeError("Strategy output order did not match selected PDF pages")
            measurement.update(
                {
                    "run": len(runs[strategy]) + 1,
                    "parse_document_calls": parse_calls,
                    "output_sha256": text_digest(texts),
                    "mapping_valid": True,
                }
            )
            runs[strategy].append(measurement)
            retained_texts.setdefault(strategy, texts)

    per_page_texts = retained_texts["per_page"]
    batched_texts = retained_texts["batched"]
    page_comparison = [
        {
            "pdf_page": pdf_page,
            "per_page_sha256": hashlib.sha256(
                per_page_texts[pdf_page].encode("utf-8")
            ).hexdigest(),
            "batched_sha256": hashlib.sha256(
                batched_texts[pdf_page].encode("utf-8")
            ).hexdigest(),
            "exact_text_equal": per_page_texts[pdf_page] == batched_texts[pdf_page],
        }
        for pdf_page in selection.pdf_pages
    ]

    medians: dict[str, dict[str, float | int | None]] = {}
    for strategy in STRATEGIES:
        elapsed_values = [run["elapsed_seconds"] for run in runs[strategy]]
        memory_values = [
            run["peak_working_set_increase_bytes"]
            for run in runs[strategy]
            if run["peak_working_set_increase_bytes"] is not None
        ]
        medians[strategy] = {
            "elapsed_seconds": statistics.median(elapsed_values),
            "peak_working_set_increase_bytes": (
                int(statistics.median(memory_values)) if memory_values else None
            ),
        }

    report = {
        "schema_version": 1,
        "benchmark_run_id": run_id,
        "source": {
            "file_name": resolved_pdf.name,
            "size_bytes": resolved_pdf.stat().st_size,
            "sha256": sha256_file(resolved_pdf),
        },
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "pymupdf_version": pymupdf.__version__,
            "pymupdf4llm_version": str(pymupdf4llm.version),
        },
        "api_verified": {
            "pages_numbering": "0-based",
            "page_chunks": True,
            "chunk_mapping_field": "metadata.page_number (1-based)",
            "installed_entry_point": "pymupdf4llm.to_markdown",
        },
        "selected_pdf_pages": list(selection.pdf_pages),
        "warmup": {
            "performed": True,
            "pdf_page": selection.pdf_pages[0],
            "elapsed_seconds": warmup_elapsed,
            "excluded_from_measured_runs": True,
        },
        "measurement": {
            "clock": "time.perf_counter_ns (monotonic wall-clock)",
            "run_order": run_order,
            "runs_per_strategy": 3,
            "median_definition": "middle value after sorting the three measurements",
            "memory": "process working-set increase from pre-call baseline; 5 ms sampling",
            "parse_document_calls": "directly counted calls; not asserted to equal model-load count",
        },
        "runs": runs,
        "medians": medians,
        "quality_comparison": {
            "all_page_mappings_valid": all(
                run["mapping_valid"] for values in runs.values() for run in values
            ),
            "all_measured_outputs_deterministic": all(
                len({run["output_sha256"] for run in runs[strategy]}) == 1
                for strategy in STRATEGIES
            ),
            "all_pages_exact_text_equal": all(
                page["exact_text_equal"] for page in page_comparison
            ),
            "pages": page_comparison,
        },
        "completed_at": utc_now(),
    }

    with StagedOutput(output_dir, run_id) as staged:
        for strategy, texts in retained_texts.items():
            strategy_dir = staged.staging_path / strategy
            strategy_dir.mkdir()
            for pdf_page, text in texts.items():
                write_utf8_atomically(strategy_dir / f"page_{pdf_page:04d}.md", text)
        write_utf8_atomically(
            staged.staging_path / "benchmark.json",
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
        staged.publish()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--pages", required=True)
    parser.add_argument("--out", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_benchmark(args.pdf, PageSelection.parse(args.pages), args.out)
    except InspectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(f"unexpected error: {type(exc).__name__}", file=sys.stderr)
        return EXIT_UNEXPECTED_ERROR
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
