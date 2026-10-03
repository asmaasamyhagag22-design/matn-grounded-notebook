"""Build the overnight demo decks: plan (demo_planner) -> render (template_renderer) -> PowerPoint PNG + PDF export.

Inputs are out/demo/facts/<doc_key>.json (eval/gold_to_facts.py) and the optional cached model phrasings
(out/demo/phrases/). Outputs, all under out/demo/ (git-ignored):

  decks/<doc_key>/plan.json                      DeckPlan + per-slide meta (title source, abridged items)
  decks/<doc_key>/<template>/deck.pptx           editable deck
  decks/<doc_key>/<template>/deck.pdf            PowerPoint PDF export (trick 28, PDF part)
  decks/<doc_key>/<template>/png/slide_NN.png    PowerPoint slide export, 1280x720
  decks/<doc_key>/<template>/render.json         layouts, warnings, overflows
  manifest.json                                  what exists, for the dashboard

Usage: .venv\\Scripts\\python.exe -m matn_deck.demo_build [--no-export] [--doc KEY] [--template ID]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .demo_phrasing import load_phrases
from .demo_planner import DemoDoc, load_demo_doc, plan_deck
from .template_renderer import render

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "out" / "demo"
TEMPLATES = REPO / "design" / "templates"
EXPORT_PS1 = REPO / "scripts" / "export_deck.ps1"
DEMO_MATRIX = {
    "wb_eem_2021_12": ["modulo", "nile-night", "film-burn-dark", "facet-dark", "integral-dark"],
    "gao_21_519sp": ["modulo", "nile-night-teal"],
    "2601.14525v1": ["papyrus", "modulo"],
}


def deck_dir(doc_key: str, template_id: str, root: Path = OUT) -> Path:
    return root / "decks" / doc_key / template_id


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def build_plan(doc: DemoDoc, *, use_model_phrases: bool = True):
    phrases = load_phrases(doc.doc_key) if use_model_phrases else {}
    demo = plan_deck(doc, phrases)
    write_json(OUT / "decks" / doc.doc_key / "plan.json",
               {"plan": demo.plan.model_dump(mode="json"), "meta": [asdict(m) for m in demo.meta]})
    return demo


def render_deck(doc: DemoDoc, demo, template_id: str, out_dir: Path) -> dict:
    """Render one deck; returns its render record (never raises on overflow: overflows are reported)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    template = TEMPLATES / template_id / "template.pptx"
    tmp = out_dir / "deck.part.pptx"
    started = time.monotonic()
    report = render(demo.plan, doc.facts, doc.tables, template, tmp)
    tmp.replace(out_dir / "deck.pptx")
    record = {
        "doc_key": doc.doc_key, "template": template_id, "slides": len(report.layouts),
        "layouts": list(report.layouts), "warnings": list(report.warnings),
        "overflows": [asdict(o) for o in report.overflows],
        "hard_violations": [w for w in report.warnings if w.startswith("HARD_VIOLATION")],
        "render_seconds": round(time.monotonic() - started, 2),
        "rendered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    write_json(out_dir / "render.json", record)
    return record


def export(decks: list[Path], *, timeout: float = 1800) -> tuple[bool, str]:
    """PowerPoint PNG + PDF export of several decks in one session. Returns (ok, log)."""
    if not decks:
        return True, ""
    pngs = [str(d / "png") for d in decks]
    pdfs = [str(d / "deck.pdf") for d in decks]
    ppts = [str(d / "deck.pptx") for d in decks]
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(EXPORT_PS1),
             "-Pptx", ",".join(ppts), "-OutDir", ",".join(pngs), "-Pdf", ",".join(pdfs)],
            capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"EXPORT_FAILED:{type(exc).__name__}"
    return result.returncode == 0, (result.stdout + result.stderr)[-2000:]


def manifest() -> dict:
    """What the dashboard can show: every deck folder with its files, read back from disk."""
    docs = {}
    for facts_path in sorted((OUT / "facts").glob("*.json")):
        data = json.loads(facts_path.read_text(encoding="utf-8"))
        key = data["doc_key"]
        decks = {}
        for template_id in DEMO_MATRIX.get(key, []):
            d = deck_dir(key, template_id)
            if not (d / "deck.pptx").is_file():
                continue
            rel = lambda p: p.relative_to(REPO).as_posix()  # noqa: E731
            decks[template_id] = {
                "pptx": rel(d / "deck.pptx"),
                "pdf": rel(d / "deck.pdf") if (d / "deck.pdf").is_file() else None,
                "pngs": [rel(p) for p in sorted((d / "png").glob("slide_*.png"))],
                "render": json.loads((d / "render.json").read_text(encoding="utf-8")),
            }
        docs[key] = {"title": data["title"], "publisher": data["publisher"], "license": data["license"],
                     "facts": len(data["facts"]),
                     "verified": sum(f["status"] == "verified" for f in data["facts"]),
                     "number_facts": sum(f["kind"] == "number" for f in data["facts"]),
                     "templates": DEMO_MATRIX.get(key, []), "decks": decks}
    return {"schema": "matn-demo-manifest/1", "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "documents": docs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the demo decks.")
    parser.add_argument("--doc", action="append", choices=sorted(DEMO_MATRIX))
    parser.add_argument("--template", action="append")
    parser.add_argument("--no-export", action="store_true", help="skip the PowerPoint PNG/PDF export")
    parser.add_argument("--no-model-phrases", action="store_true", help="ignore cached model phrasings")
    args = parser.parse_args(argv)
    built: list[Path] = []
    for key in args.doc or list(DEMO_MATRIX):
        doc = load_demo_doc(OUT / "facts" / f"{key}.json")
        demo = build_plan(doc, use_model_phrases=not args.no_model_phrases)
        sources = [m.title_source for m in demo.meta]
        print(f"{key}: {len(demo.plan.slides)} plan slides; titles {dict((s, sources.count(s)) for s in set(sources))}")
        for template_id in DEMO_MATRIX[key]:
            if args.template and template_id not in args.template:
                continue
            record = render_deck(doc, demo, template_id, deck_dir(key, template_id))
            built.append(deck_dir(key, template_id))
            print(f"  {template_id}: {record['slides']} slides, {len(record['overflows'])} overflows, "
                  f"{len(record['hard_violations'])} hard violations, {record['render_seconds']} s")
    if not args.no_export:
        ok, log = export(built)
        print(log.strip())
        if not ok:
            print("EXPORT FAILED: the decks are rendered; PNG/PDF are missing or stale")
    write_json(OUT / "manifest.json", manifest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
