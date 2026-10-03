"""Optional model phrasing for the demo decks: assertion titles and short item texts, cached and checked.

The demo never depends on the model. `phrase_missing` asks the local Ollama (127.0.0.1 only, through a proxy-free
opener: the audit F-03 fix) to phrase what the planner requests, and stores in out/demo/phrases/<doc_key>.json only
the answers that pass the planner's own checks (`title_problems`, `item_problems`). The planner re-checks every cached
phrasing when it builds a plan, so a stale or edited cache can never put an unchecked number on a slide. When the model
is missing, slow or wrong, the planner's deterministic text is used.

Usage: .venv\\Scripts\\python.exe -m matn_deck.demo_phrasing [--budget-seconds 1800]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from .demo_planner import ITEM_MAX, TITLE_MAX, DemoDoc, item_problems, load_demo_doc, plan_deck, title_problems

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "out" / "demo"
MODEL = "qwen3.5:9b"
BASE_URL = "http://127.0.0.1:11434"
PROMPT_VERSION = "demo-phrasing/1"
_LOOPBACK_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # ignores HTTP(S)_PROXY and GPO

TITLE_SYSTEM = (
    "You write one slide title for a government briefing deck. The title is a single assertion sentence that states "
    f"what the facts below show, at most {TITLE_MAX - 10} characters, sentence case, no final period. Use only the "
    "facts given. Never add a number, year or percentage that is not printed in the facts; copy any number exactly. "
    "Keep hedges (may, likely, not). Answer with JSON only.")
ITEM_SYSTEM = (
    f"You shorten one statement for a slide bullet to at most {ITEM_MAX - 15} characters. Keep its meaning, its "
    "subject and every hedge or negation (may, not, only, significantly). Drop attribution such as 'The report "
    "finds'. Reuse the statement's own words; add no new facts, words of judgement or numbers. Answer with JSON only.")


class PhrasingUnavailable(RuntimeError):
    pass


def _loopback(base_url: str) -> str:
    host = urlparse(base_url).hostname
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise PhrasingUnavailable(f"NOT_LOOPBACK:{host}")
    return base_url.rstrip("/")


def ask(system: str, user: str, *, base_url: str = BASE_URL, model: str = MODEL, timeout: float = 120) -> str:
    payload = {
        "model": model, "stream": False, "think": False,
        "options": {"temperature": 0, "seed": 7, "num_ctx": 2048, "num_predict": 96},
        "format": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    request = urllib.request.Request(_loopback(base_url) + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with _LOOPBACK_OPENER.open(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return str(json.loads(body["message"]["content"])["text"]).strip()
    except (OSError, ValueError, KeyError, urllib.error.URLError) as exc:
        raise PhrasingUnavailable(f"OLLAMA_FAILED:{type(exc).__name__}") from None


def cache_path(doc_key: str) -> Path:
    return OUT / "phrases" / f"{doc_key}.json"


def load_phrases(doc_key: str) -> dict[str, str]:
    path = cache_path(doc_key)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: entry["text"] for key, entry in data.get("accepted", {}).items()}


def _save(doc_key: str, data: dict) -> None:
    path = cache_path(doc_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _prompt(doc: DemoDoc, request: dict) -> tuple[str, str]:
    facts = [doc.fact(fid) for fid in request["fact_ids"]]
    if request["kind"] == "title":
        lines = "\n".join(f"- {f.statement}" for f in facts)
        return TITLE_SYSTEM, f"Facts on this slide:\n{lines}\nWrite the title as {{\"text\": ...}}."
    return ITEM_SYSTEM, f"Statement:\n{facts[0].statement}\nWrite the short bullet as {{\"text\": ...}}."


def phrase_missing(doc: DemoDoc, *, budget_seconds: float, base_url: str = BASE_URL, log=print) -> dict:
    """Ask the model for every requested phrasing not yet cached; keep only answers that pass the checks."""
    path = cache_path(doc.doc_key)
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data.setdefault("model", MODEL)
    data.setdefault("prompt_version", PROMPT_VERSION)
    accepted, refused = data.setdefault("accepted", {}), data.setdefault("refused", {})
    requests = plan_deck(doc).requests
    started = time.monotonic()
    for key, request in requests.items():
        if key in accepted or key in refused:
            continue
        if time.monotonic() - started > budget_seconds:
            log(f"  budget reached; {key} left to the deterministic text")
            break
        system, user = _prompt(doc, request)
        try:
            text = ask(system, user, base_url=base_url)
        except PhrasingUnavailable as exc:
            log(f"  model unavailable ({exc}); stopping, deterministic text stays")
            break
        facts = tuple(doc.fact(fid) for fid in request["fact_ids"])
        text = text.rstrip(".") if request["kind"] == "title" else text
        problems = title_problems(text, facts) if request["kind"] == "title" else item_problems(text, facts[0])
        entry = {"text": text, "kind": request["kind"], "fact_ids": request["fact_ids"]}
        if problems:
            refused[key] = {**entry, "problems": problems}
        else:
            accepted[key] = entry
        log(f"  {'ok ' if not problems else 'REF'} {key[:22]} {text!r} {problems or ''}")
        _save(doc.doc_key, data)
    _save(doc.doc_key, data)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phrase demo titles and items with the local model (optional).")
    parser.add_argument("--budget-seconds", type=float, default=1800)
    args = parser.parse_args(argv)
    for path in sorted((OUT / "facts").glob("*.json")):
        doc = load_demo_doc(path)
        print(doc.doc_key)
        data = phrase_missing(doc, budget_seconds=args.budget_seconds)
        print(f"  accepted {len(data['accepted'])}, refused {len(data['refused'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
