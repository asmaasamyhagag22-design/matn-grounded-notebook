"""Atomic conversation state and durable, resumable event streams."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import secrets
import threading
import time

DEFAULT_AUDIENCE = "Public policy professionals — introductory briefing"


def read(path, default=None):
    try:
        return json.loads(Path(path).read_bytes())
    except FileNotFoundError:
        return deepcopy(default)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + secrets.token_hex(6) + ".pending")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def folder(self, conversation):
        if not isinstance(conversation, str) or not re.fullmatch(r"[a-f0-9]{24}", conversation):
            raise ValueError("Unknown conversation")
        return self.root / "conversations" / conversation

    def create(self, title="New conversation", audience=None):
        value = dict(id=secrets.token_hex(12), title=str(title)[:140], audience=audience or DEFAULT_AUDIENCE,
                     audience_explicit=bool(audience), created_at=time.time(), updated_at=time.time(), messages=[], events=[], catalogs=[],
                     documents=[], notebooks=[], runs=[], plans=[], decks=[], active_deck=None, jobs=[],
                     deleted=False, metrics={})
        write(self.folder(value["id"]) / "conversation.json", value)
        return value

    def get(self, conversation):
        with self.lock:
            value = read(self.folder(conversation) / "conversation.json")
            if value is None:
                raise ValueError("Unknown conversation")
            return value

    def update(self, conversation, change):
        with self.lock:
            value = self.get(conversation)
            change(value)
            value["updated_at"] = time.time()
            write(self.folder(conversation) / "conversation.json", value)
            return value

    def event(self, conversation, kind, detail):
        def change(value):
            value["events"].append(dict(id=len(value["events"]) + 1, kind=kind, detail=detail, at=time.time()))
        return self.update(conversation, change)["events"][-1]

    def message(self, conversation, role, text, **extra):
        message = dict(id=secrets.token_hex(8), role=role, text=text, at=time.time(), **extra)
        self.update(conversation, lambda value: value["messages"].append(message))
        self.event(conversation, "change", "Message saved")
        return message

    def list(self):
        with self.lock:
            rows = [read(p) for p in (self.root / "conversations").glob("*/conversation.json")]
            return sorted([dict(id=v["id"], title=v["title"], updated_at=v["updated_at"],
                                jobs=v["jobs"], units=v.get("metrics", {}).get("units", 0))
                           for v in rows if v and not v.get("deleted")], key=lambda v: -v["updated_at"])

    def recover(self):
        """Never restart a heavy operation or spend calls merely because the app restarted."""
        for row in self.list():
            interrupted = []
            def change(value):
                for job in value["jobs"]:
                    if job["status"] in ("running", "queued"):
                        job.update(status="interrupted", ended_at=time.time())
                        interrupted.append(job)
            self.update(row["id"], change)
            if interrupted:
                with (self.root / "recovered.jsonl").open("a") as stream:
                    stream.write(json.dumps(dict(status="RECOVERED", cause="App stopped with stale running or queued jobs",
                        action="Marked interrupted; retained evidence and retry controls", conversation=row["id"],
                        jobs=[j["id"] for j in interrupted], at=time.time())) + "\n")
                self.message(row["id"], "assistant", "The app stopped during a job. Saved evidence, files and deck versions are retained. You can retry explicitly or open the partial research result.", kind="interrupted")
