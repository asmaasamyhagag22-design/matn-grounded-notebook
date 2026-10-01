from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator


class Phase03Error(RuntimeError):
    """Expected failure whose message is safe to show (never source text)."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase03Error(f"INVALID_JSON:{path.name}:{type(exc).__name__}") from None
    if not isinstance(value, dict):
        raise Phase03Error(f"INVALID_JSON_OBJECT:{path.name}")
    return value


def load_schema(project_root: Path, name: str) -> dict[str, Any]:
    return read_json(project_root / "schemas" / name)


def validate_schema(instance: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        location = ".".join(str(item) for item in first.path) or "$"
        raise Phase03Error(f"SCHEMA_VALIDATION_FAILED:{label}:{location}:{first.validator}")


def _validate_source_files(store_path: Path, store: dict[str, Any], selected_ids: set[str]) -> None:
    chunks = {item["chunk_id"]: item for item in store["chunks"]}
    checked: set[Path] = set()
    store_root = store_path.parent.resolve()
    for chunk_id in selected_ids:
        chunk = chunks[chunk_id]
        source_path = (store_root / chunk["source_text_path"]).resolve()
        if not source_path.is_relative_to(store_root):
            raise Phase03Error("SOURCE_PATH_OUTSIDE_DOCUMENT_STORE")
        if source_path in checked:
            continue
        checked.add(source_path)
        try:
            source = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise Phase03Error(f"SOURCE_FILE_UNREADABLE:{source_path.name}:{type(exc).__name__}") from None
        page_chunks = [item for item in store["chunks"] if item["source_text_path"] == chunk["source_text_path"]]
        for item in page_chunks:
            if source[item["start_offset"]:item["end_offset"]] != item["text"]:
                raise Phase03Error(f"SOURCE_FILES_CHANGED:{source_path.name}")


def load_and_validate_inputs(
    project_root: Path, selection_path: Path, store_path: Path, pdf_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    selection = read_json(selection_path)
    store = read_json(store_path)
    validate_schema(selection, load_schema(project_root, "source-selection.schema.json"), "selection")
    validate_schema(store, load_schema(project_root, "document-store.schema.json"), "document-store")
    if selection["confirmation_status"] != "confirmed":
        raise Phase03Error("SELECTION_NOT_CONFIRMED")
    if selection["document_id"] != store["document"]["document_id"]:
        raise Phase03Error("SELECTION_DOCUMENT_IDENTITY_MISMATCH")
    if not pdf_path.is_file() or sha256_file(pdf_path) != store["document"]["sha256"]:
        raise Phase03Error("DOCUMENT_SOURCE_IDENTITY_MISMATCH")
    store_chunks = {item["chunk_id"]: item for item in store["chunks"]}
    selection_chunks = {item["chunk_id"]: item for item in selection["chunks"]}
    ordered = selection["included_chunk_ids"]
    if len(ordered) != len(set(ordered)) or set(ordered) != set(selection_chunks):
        raise Phase03Error("SELECTION_CHUNK_SET_MISMATCH")
    for chunk_id in ordered:
        if chunk_id not in store_chunks:
            raise Phase03Error("UNKNOWN_SELECTED_CHUNK")
        source_chunk = store_chunks[chunk_id]
        chosen = selection_chunks[chunk_id]
        if chosen.get("original_text") != source_chunk["text"]:
            raise Phase03Error("SELECTION_SOURCE_TEXT_MISMATCH")
        if chosen.get("selection_text", "") not in source_chunk["text"]:
            raise Phase03Error("SELECTION_TRANSFORMATION_MISMATCH")
    _validate_source_files(store_path, store, set(ordered))
    return selection, store


@contextmanager
def atomic_output_directory(target: Path) -> Iterator[Path]:
    if target.exists():
        raise Phase03Error("OUTPUT_PATH_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = target.parent / f".{target.name}.{uuid.uuid4().hex}.staging"
    stage.mkdir()
    marker = stage / ".matn-phase03-owned"
    marker.write_text("owned\n", encoding="utf-8")
    try:
        yield stage
        marker.unlink()
        os.replace(stage, target)
    except Exception:
        if stage.is_dir() and marker.is_file():
            shutil.rmtree(stage)
        raise


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
