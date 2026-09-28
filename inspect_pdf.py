"""Local per-page PDF extraction with raw and structured backends.

The raw backend is diagnostic PyMuPDF text extraction. The structured backend
uses PyMuPDF4LLM Markdown with its layout engine and OCR explicitly disabled.
Neither backend uploads data or invokes an LLM.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pymupdf


EXIT_OK = 0
EXIT_INPUT_ERROR = 2
EXIT_PDF_ERROR = 3
EXIT_OUTPUT_ERROR = 4
EXIT_EXTRACTION_ERROR = 5
EXIT_UNEXPECTED_ERROR = 10
SUPPORTED_EXTRACTORS = ("raw", "structured")
STAGING_MARKER = ".matn-staging.json"


class InspectionError(Exception):
    """Expected user-facing failure with a specific process exit code."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class PageExtractionError(InspectionError):
    """A page failed; staged data must not be published as a completed run."""

    def __init__(self, pdf_page: int, error_type: str) -> None:
        super().__init__(
            f"PDF page {pdf_page} extraction failed ({error_type}); "
            "no final output was published.",
            EXIT_EXTRACTION_ERROR,
        )
        self.pdf_page = pdf_page
        self.error_type = error_type


@dataclass(frozen=True)
class PageSelection:
    """A user selection expressed with 1-based PDF page numbers."""

    raw: str
    pdf_pages: tuple[int, ...]

    @classmethod
    def parse(cls, value: str) -> "PageSelection":
        if not value.strip():
            raise InspectionError("Page selection cannot be empty.", EXIT_INPUT_ERROR)

        pdf_pages: list[int] = []
        seen: set[int] = set()
        for token in value.split(","):
            match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", token)
            if match is None:
                raise InspectionError(
                    f"Invalid page selection {value!r}. Use values such as "
                    "'2', '2-4', or '1,3-4'.",
                    EXIT_INPUT_ERROR,
                )

            start = int(match.group(1))
            end = int(match.group(2) or start)
            if start < 1 or end < 1:
                raise InspectionError(
                    "PDF page numbers are 1-based; page 0 is invalid.",
                    EXIT_INPUT_ERROR,
                )
            if start > end:
                raise InspectionError(
                    f"Invalid reversed page range {token.strip()!r}: start must be <= end.",
                    EXIT_INPUT_ERROR,
                )

            for pdf_page in range(start, end + 1):
                if pdf_page in seen:
                    raise InspectionError(
                        f"PDF page {pdf_page} is selected more than once.",
                        EXIT_INPUT_ERROR,
                    )
                seen.add(pdf_page)
                pdf_pages.append(pdf_page)

        return cls(raw=value, pdf_pages=tuple(pdf_pages))

    def to_zero_based_indices(self, page_count: int) -> list[int]:
        """Validate and perform the sole 1-based -> 0-based conversion."""
        for pdf_page in self.pdf_pages:
            if pdf_page > page_count:
                raise InspectionError(
                    f"PDF page {pdf_page} exceeds the document page count ({page_count}).",
                    EXIT_INPUT_ERROR,
                )
        return [pdf_page - 1 for pdf_page in self.pdf_pages]


class StagedOutput:
    """Own a hidden staging directory and publish it with a same-volume rename."""

    def __init__(self, final_path: Path, run_id: str) -> None:
        self.final_path = final_path.resolve(strict=False)
        self.run_id = run_id
        self.staging_path = self.final_path.parent / (
            f".{self.final_path.name}.{run_id}.staging"
        )
        self._published = False

    def __enter__(self) -> "StagedOutput":
        if self.final_path.exists():
            raise InspectionError(
                f"Output path already exists; refusing to overwrite it: {self.final_path}",
                EXIT_OUTPUT_ERROR,
            )
        created_here = False
        try:
            self.final_path.parent.mkdir(parents=True, exist_ok=True)
            self.staging_path.mkdir(exist_ok=False)
            created_here = True
            marker = {"owner": "matn", "run_id": self.run_id}
            (self.staging_path / STAGING_MARKER).write_text(
                json.dumps(marker), encoding="utf-8"
            )
        except OSError as exc:
            if created_here:
                try:
                    shutil.rmtree(self.staging_path)
                except OSError:
                    pass
            raise InspectionError(
                f"Cannot create staged output directory: {type(exc).__name__}",
                EXIT_OUTPUT_ERROR,
            ) from exc
        return self

    def publish(self) -> None:
        if self.final_path.exists():
            raise InspectionError(
                "Output path appeared during extraction; refusing to overwrite it.",
                EXIT_OUTPUT_ERROR,
            )
        try:
            os.rename(self.staging_path, self.final_path)
            self._published = True
            try:
                (self.final_path / STAGING_MARKER).unlink()
            except OSError:
                pass
        except OSError as exc:
            raise InspectionError(
                f"Cannot publish completed output atomically: {type(exc).__name__}",
                EXIT_OUTPUT_ERROR,
            ) from exc

    def _cleanup_owned_staging(self) -> None:
        if not self.staging_path.exists():
            return
        marker_path = self.staging_path / STAGING_MARKER
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(
                f"warning: staging cleanup skipped because ownership could not be "
                f"verified: {self.staging_path}",
                file=sys.stderr,
            )
            return
        if marker != {"owner": "matn", "run_id": self.run_id}:
            print(
                f"warning: staging cleanup skipped because ownership did not match: "
                f"{self.staging_path}",
                file=sys.stderr,
            )
            return
        try:
            shutil.rmtree(self.staging_path)
        except OSError as exc:
            print(
                f"warning: could not clean owned staging directory "
                f"({type(exc).__name__}): {self.staging_path}",
                file=sys.stderr,
            )

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._published:
            self._cleanup_owned_staging()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_pdf(path: Path) -> pymupdf.Document:
    try:
        document = pymupdf.open(path)
    except Exception as exc:
        raise InspectionError(
            f"Cannot open PDF ({type(exc).__name__}).", EXIT_PDF_ERROR
        ) from exc

    if not document.is_pdf:
        document.close()
        raise InspectionError("Input is not a PDF document.", EXIT_PDF_ERROR)
    if document.needs_pass:
        document.close()
        raise InspectionError(
            "PDF requires a password; password-protected input is not supported.",
            EXIT_PDF_ERROR,
        )
    return document


def write_utf8_atomically(path: Path, text: str) -> None:
    temporary_path = path.with_name(f"{path.name}.tmp")
    try:
        temporary_path.write_bytes(text.encode("utf-8"))
        temporary_path.replace(path)
    except OSError:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def extractor_metadata(extractor: str) -> dict[str, Any]:
    if extractor == "raw":
        return {
            "name": "PyMuPDF Page.get_text",
            "version": pymupdf.__version__,
            "settings": {
                "output_format": "plain_text",
                "get_text_option": "text",
                "sort": False,
                "ocr": False,
                "content_cleaning": False,
                "page_processing": "one_page_per_output_file",
            },
        }

    try:
        import pymupdf4llm
    except ImportError as exc:
        raise InspectionError(
            "Structured extraction requires PyMuPDF4LLM.", EXIT_INPUT_ERROR
        ) from exc

    pymupdf4llm.use_layout(True)
    return {
        "name": "PyMuPDF4LLM to_markdown",
        "version": str(pymupdf4llm.version),
        "settings": {
            "output_format": "markdown",
            "layout_mode": "pymupdf_layout",
            "layout_engine_version": importlib.metadata.version("pymupdf_layout"),
            "page_chunks": True,
            "use_ocr": False,
            "force_ocr": False,
            "header": True,
            "footer": True,
            "write_images": False,
            "embed_images": False,
            "page_processing": "one_requested_page_per_call",
        },
    }


def extract_page_text(
    document: pymupdf.Document,
    page: pymupdf.Page,
    page_index: int,
    extractor: str,
) -> tuple[str, str]:
    """Return page text and its filename suffix."""
    if extractor == "raw":
        return page.get_text("text", sort=False), ".txt"

    import pymupdf4llm

    chunks = pymupdf4llm.to_markdown(
        document,
        pages=[page_index],
        page_chunks=True,
        use_ocr=False,
        force_ocr=False,
        write_images=False,
        embed_images=False,
        header=True,
        footer=True,
        page_separators=False,
        show_progress=False,
    )
    if not isinstance(chunks, list) or len(chunks) != 1:
        raise RuntimeError("PyMuPDF4LLM returned an unexpected page_chunks result")
    chunk = chunks[0]
    metadata = chunk.get("metadata")
    text = chunk.get("text")
    if not isinstance(metadata, dict) or metadata.get("page_number") != page_index + 1:
        raise RuntimeError("PyMuPDF4LLM page metadata did not match the requested page")
    if not isinstance(text, str):
        raise RuntimeError("PyMuPDF4LLM page chunk did not contain Markdown text")
    return text, ".md"


def inspect_page_signals(page: pymupdf.Page) -> tuple[dict[str, int | None], list[str]]:
    signals: dict[str, int | None] = {"image_count": None, "drawing_count": None}
    warnings: list[str] = []
    try:
        signals["image_count"] = len(page.get_image_info())
    except Exception:
        warnings.append("Image signal inspection failed; image presence is unknown.")
    try:
        signals["drawing_count"] = len(page.get_drawings())
    except Exception:
        warnings.append("Drawing signal inspection failed; drawing presence is unknown.")
    return signals, warnings


def page_warnings(status: str, signals: dict[str, int | None]) -> list[str]:
    warnings: list[str] = []
    if status == "text_present":
        warnings.append(
            "Text presence does not prove completeness or correctness; images or "
            "drawings may contain additional information."
        )
    else:
        warnings.append(
            "No text was extracted. Human review is required; this does not prove "
            "that the page is blank or scanned."
        )
    image_count = signals["image_count"]
    if isinstance(image_count, int) and image_count > 0:
        warnings.append(
            f"PyMuPDF reported {image_count} displayed image(s); this signal does "
            "not prove that the page is scanned."
        )
    return warnings


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Reject incomplete manifests before they can be published."""
    required_top = {
        "schema_version",
        "extraction_run_id",
        "run_status",
        "source",
        "extractor",
        "requested_pdf_pages",
        "timing",
        "environment",
        "pages",
    }
    if set(manifest) != required_top:
        raise RuntimeError("Manifest top-level fields do not match schema version 2")
    if manifest["schema_version"] != 2 or manifest["run_status"] != "completed":
        raise RuntimeError("Manifest is not a completed schema version 2 run")
    requested = manifest["requested_pdf_pages"]
    records = manifest["pages"]
    if len(records) != len(requested["pdf_pages"]):
        raise RuntimeError("Manifest page records do not match requested pages")
    for pdf_page, page_index, record in zip(
        requested["pdf_pages"], requested["page_indices"], records, strict=True
    ):
        if record["pdf_page"] != pdf_page or record["page_index"] != page_index:
            raise RuntimeError("Manifest page mapping is inconsistent")
        if record["extraction_status"] not in {"text_present", "no_text"}:
            raise RuntimeError("Completed manifest contains a failed page")
        if record["error"] is not None:
            raise RuntimeError("Completed manifest contains a page error")


def run_extraction(
    pdf_path: Path,
    selection: PageSelection,
    output_dir: Path,
    *,
    extractor: str = "raw",
    preview_chars: int = 0,
) -> dict[str, Any]:
    """Extract selected pages into staged output and atomically publish on success."""
    if extractor not in SUPPORTED_EXTRACTORS:
        raise InspectionError(f"Unsupported extractor: {extractor}", EXIT_INPUT_ERROR)
    if preview_chars < 0:
        raise InspectionError("--preview-chars must be >= 0.", EXIT_INPUT_ERROR)
    if not pdf_path.exists():
        raise InspectionError("PDF file does not exist.", EXIT_INPUT_ERROR)
    if not pdf_path.is_file():
        raise InspectionError("PDF path is not a file.", EXIT_INPUT_ERROR)

    try:
        resolved_pdf = pdf_path.resolve(strict=True)
        resolved_output = output_dir.resolve(strict=False)
        source_size = resolved_pdf.stat().st_size
    except OSError as exc:
        raise InspectionError(
            f"Cannot read input file metadata ({type(exc).__name__}).", EXIT_INPUT_ERROR
        ) from exc

    run_id = str(uuid.uuid4())
    started_at = utc_now()
    started_ns = time.perf_counter_ns()
    extractor_info = extractor_metadata(extractor)
    document = open_pdf(resolved_pdf)
    try:
        page_count = document.page_count
        page_indices = selection.to_zero_based_indices(page_count)
        source_sha256 = sha256_file(resolved_pdf)

        with StagedOutput(resolved_output, run_id) as staged:
            page_records: list[dict[str, Any]] = []
            for pdf_page, page_index in zip(
                selection.pdf_pages, page_indices, strict=True
            ):
                try:
                    page = document.load_page(page_index)
                    signals, signal_warnings = inspect_page_signals(page)
                    try:
                        page_label = page.get_label() or None
                    except Exception:
                        page_label = None
                        signal_warnings.append(
                            "Page-label metadata inspection failed; page_label is null."
                        )

                    text, suffix = extract_page_text(
                        document, page, page_index, extractor
                    )
                    filename = f"page_{pdf_page:04d}{suffix}"
                    write_utf8_atomically(staged.staging_path / filename, text)
                    text_char_count = len(text.strip())
                    status = "text_present" if text_char_count else "no_text"
                    warnings = signal_warnings + page_warnings(status, signals)
                    page_records.append(
                        {
                            "page_index": page_index,
                            "pdf_page": pdf_page,
                            "page_label": page_label,
                            "printed_page": None,
                            "text_path": filename,
                            "text_char_count": text_char_count,
                            "extraction_status": status,
                            "human_review": "not_performed",
                            "signals": signals,
                            "warnings": warnings,
                            "error": None,
                        }
                    )

                    print(
                        f"PDF page {pdf_page} (page_index={page_index}): {status}; "
                        f"text_char_count={text_char_count}; output={filename}"
                    )
                    if preview_chars:
                        print(
                            f"Explicit content preview ({preview_chars} chars): "
                            f"{text[:preview_chars]!r}"
                        )
                except Exception as exc:
                    raise PageExtractionError(pdf_page, type(exc).__name__) from exc

            try:
                ending_size = resolved_pdf.stat().st_size
                ending_sha256 = sha256_file(resolved_pdf)
            except OSError as exc:
                raise InspectionError(
                    f"Cannot revalidate source file ({type(exc).__name__}); "
                    "no final output was published.",
                    EXIT_INPUT_ERROR,
                ) from exc
            if ending_size != source_size or ending_sha256 != source_sha256:
                raise InspectionError(
                    "Source PDF changed during extraction; no final output was published.",
                    EXIT_INPUT_ERROR,
                )

            completed_at = utc_now()
            elapsed_seconds = (time.perf_counter_ns() - started_ns) / 1_000_000_000
            manifest: dict[str, Any] = {
                "schema_version": 2,
                "extraction_run_id": run_id,
                "run_status": "completed",
                "source": {
                    "file_name": resolved_pdf.name,
                    "size_bytes": source_size,
                    "sha256": source_sha256,
                    "page_count": page_count,
                },
                "extractor": extractor_info,
                "requested_pdf_pages": {
                    "input": selection.raw,
                    "pdf_pages": list(selection.pdf_pages),
                    "page_indices": page_indices,
                    "numbering": "pdf_page is 1-based; page_index is 0-based",
                },
                "timing": {
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "elapsed": elapsed_seconds,
                    "unit": "seconds",
                    "clock": "time.perf_counter_ns (monotonic wall-clock)",
                    "scope": (
                        "source validation, hashing, page extraction, signal inspection, "
                        "and staged file writes; excludes final directory rename"
                    ),
                },
                "environment": {
                    "python_version": platform.python_version(),
                    "platform": platform.platform(),
                },
                "pages": page_records,
            }
            validate_manifest(manifest)
            write_utf8_atomically(
                staged.staging_path / "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
            staged.publish()
            return manifest
    finally:
        document.close()


def nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract selected PDF pages locally with raw PyMuPDF text or "
            "PyMuPDF4LLM Markdown."
        )
    )
    parser.add_argument("--pdf", required=True, type=Path, help="Source PDF path")
    parser.add_argument(
        "--pages",
        required=True,
        help="1-based pages, for example 2, 2-4, or 1,3-4",
    )
    parser.add_argument("--out", required=True, type=Path, help="New output directory")
    parser.add_argument(
        "--extractor",
        choices=SUPPORTED_EXTRACTORS,
        default="raw",
        help="raw (PyMuPDF text) or structured (PyMuPDF4LLM Markdown)",
    )
    parser.add_argument(
        "--preview-chars",
        type=nonnegative_int,
        default=0,
        help="Explicitly opt into logging up to N content characters (default: 0)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        selection = PageSelection.parse(args.pages)
        run_extraction(
            args.pdf,
            selection,
            args.out,
            extractor=args.extractor,
            preview_chars=args.preview_chars,
        )
    except InspectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        print(
            f"unexpected error: {type(exc).__name__}; no final output was published.",
            file=sys.stderr,
        )
        return EXIT_UNEXPECTED_ERROR
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
