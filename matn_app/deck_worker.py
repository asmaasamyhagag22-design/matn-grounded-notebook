"""Isolated app deck job: a saved catalog and optional typed edit become a new deck.

Run with ``python -B -m matn_app.deck_worker REQUEST.json``. Outputs stay in a
new folder; a failed request cannot overwrite a previously delivered version.
Stdout and ``output/result.json`` carry the same small response. Raw model text
is local diagnostic data only and never a displayed factual answer.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys
import time

from matn_deck.catalog import EvidenceCatalog
from matn_deck.edits import (
    DeckEdit, EditKind, UnsupportedEdit, apply_edit, edit_payload, fake_edit,
    load_storyboard, explicit_edit, validate_edit_intent,
)
from matn_deck.storyboard_v2 import Controls


def _path(value: str, workdir: Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else workdir / path).resolve()


def _template_id(value: str) -> str:
    value = value.split("|", 1)[0].strip().lower().replace("-", "_").replace(" ", "_")
    return {"dark": "midnight", "light": "ministry_light", "ministry": "ministry_light"}.get(value, value)


def _drain(client) -> None:
    """Confirm the generator is gone before returning the single heavy-job slot."""
    from matn_chat.generation import MODEL
    from matn_chat.memory import sample_memory
    client.deadline = time.time() + 25
    raw = client.request("/api/generate", {"model": MODEL, "keep_alive": 0})
    if not raw.get("done") or raw.get("done_reason") != "unload":
        raise RuntimeError("EDIT_MODEL_UNLOAD_UNCONFIRMED")
    deadline = time.monotonic() + 20
    while True:
        ps = client.request("/api/ps")
        if not ps.get("models") and not sample_memory()["ollama_runner_rss_bytes"]:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("EDIT_MODEL_DRAIN_UNCONFIRMED")
        time.sleep(.1)


def map_edit(instruction: str, catalog: EvidenceCatalog, storyboard, *, generator=None, trace: Path | None = None):
    from matn_chat.streaming import StreamingGenerator
    client = generator if generator is not None else StreamingGenerator(timeout=420)
    body = edit_payload(instruction, catalog, storyboard)
    raw = None
    try:
        # Chunk text is not forwarded to the app event stream. Only the final
        # schema-constrained operation can affect the storyboard.
        if hasattr(client, "generate_stream"):
            raw = client.generate_stream(body, lambda event: None, total=420, connect=10, read_idle=420)
        else:
            raw = client.generate(body)
        if not raw.get("done") or raw.get("done_reason") != "stop":
            raise UnsupportedEdit("The local model did not complete a supported edit operation.")
        operation = DeckEdit.from_dict(json.loads(raw["response"]))
        validate_edit_intent(instruction,operation)
        return operation
    finally:
        if trace is not None:
            trace.write_text(json.dumps({"schema": body["format"], "response": raw,
                                         "kind": "local typed edit mapping, not factual content"},
                                        ensure_ascii=False, indent=1), encoding="utf-8")
        if generator is None:
            _drain(client)


def run_request(request: dict, *, generator=None, renderer=None) -> dict:
    started = time.monotonic()
    workdir = Path(request.get("workdir", ".")).resolve()
    output = _path(request["output"], workdir)
    if output.exists() and any(output.iterdir()):
        raise ValueError("DECK_VERSION_ALREADY_EXISTS")
    output.mkdir(parents=True, exist_ok=True)
    calls = 0
    operation = None
    mapping = "none"
    try:
        catalog_path = _path(request["catalog"], workdir)
        catalog = EvidenceCatalog.from_json(catalog_path.read_bytes()).validate()
        for filename, digest in catalog.origin.get("files", {}).items():
            source = Path(filename)
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                raise UnsupportedEdit("A source or verification artifact changed. Restore it or rebuild from the current evidence.")
        mode = request.get("operation", "build")
        storyboard = None
        if mode not in ("build", "edit"):
            raise UnsupportedEdit("Choose build or edit for a deck job.")
        template_id = _template_id(request.get("template", "ministry_light"))
        if mode == "edit":
            storyboard = load_storyboard(_path(request["parent_storyboard"], workdir).read_bytes())
            if request.get("edit") is not None:
                operation = DeckEdit.from_dict(request["edit"])
                mapping = "typed"
            elif request.get("fake"):
                operation = fake_edit(request.get("instruction", ""), catalog, storyboard)
                mapping = "fake mapper (test mode)"
            elif request.get("instruction", "").strip():
                operation=explicit_edit(request['instruction'])
                if operation is not None:
                    mapping='explicit instruction'
                else:
                    mapping = "local model"
                    calls = 1
                    operation = map_edit(request["instruction"], catalog, storyboard,
                                         generator=generator, trace=output / "edit-mapping.json")
            else:
                raise UnsupportedEdit("Describe an edit or choose a typed operation.")
            storyboard = apply_edit(storyboard, catalog, operation)
            if operation.op is EditKind.CHANGE_TEMPLATE:
                template_id = operation.template
            elif "template" not in request:
                template_id = _template_id(storyboard.template)
        from matn_deck.product_templates import product_template
        from matn_deck.make_deck import make_deck
        template = product_template(template_id)
        controls = Controls(**request.get("controls", {}))
        qa = (renderer or make_deck)(catalog, template, output, controls=controls,
                                    fonts="template", pdf=True, label=catalog.plan.topic,
                                    storyboard=storyboard)
        story_path = output / "storyboard.json"
        rendered_story = load_storyboard(story_path.read_bytes())
        result = {
            "ok": qa["status"] == "QA_PASS", "status": qa["status"], "qa": qa,
            "delivery": qa.get("delivery", {}).get("status", "UNKNOWN"),
            "pptx": str(output / "deck.pptx"), "pdf": str(output / "deck.pdf"),
            "storyboard": str(story_path), "catalog": str(output / "catalog.json"),
            "preview": str(output / "contact-sheet.png"), "qa_report": str(output / "deck_qa.html"),
            "slides": len(rendered_story.slides), "template": template_id,
            "edit": operation.to_dict() if operation else None, "mapping": mapping,
            "verification": "Retained verified units and required contexts; deck QA rerun.",
        }
    except UnsupportedEdit as exc:
        result = {"ok": False, "status": "UNSUPPORTED_EDIT", "reason": exc.reason,
                  "alternatives": list(exc.alternatives), "edit": operation.to_dict() if operation else None,
                  "mapping": mapping}
    except Exception as exc:
        result = {"ok": False, "status": "DECK_FAILED", "reason": str(exc), "error": type(exc).__name__,
                  "edit": operation.to_dict() if operation else None, "mapping": mapping,
                  "partial": str(output)}
    result["metrics"] = {"generation_calls": calls, "native_calls": 0,
                         "seconds": round(time.monotonic() - started, 3)}
    (output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True),
                                        encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(json.dumps({"ok": False, "status": "DECK_FAILED", "reason": "One request JSON path is required."}))
        return 2
    try:
        request = json.loads(Path(argv[0]).read_bytes())
        result = run_request(request)
    except Exception as exc:
        result = {"ok": False, "status": "DECK_FAILED", "reason": str(exc), "error": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in ("QA_PASS", "UNSUPPORTED_EDIT") else 1


if __name__ == "__main__":
    raise SystemExit(main())
