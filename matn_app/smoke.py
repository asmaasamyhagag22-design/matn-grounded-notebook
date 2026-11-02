"""Offline HTTP smoke: saved research and attached JSON, real deck QA and edits.

No fresh research is started. Fixture mode disables model/search/native calls;
original saved research and the exact attached JSON are the evidence. Decks use
the real renderer, LibreOffice and both QA engines, without rendering stubs.
"""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import urllib.request

from .server import make_server
from .service import App
from .store import Store


class _Client:
    def __init__(self, server):
        self.base = "http://127.0.0.1:" + str(server.server_port)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.token = self.json("/api/bootstrap")["token"]

    def open(self, path, body=None):
        headers = {"X-Matn-Token": self.token} if body is not None else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path,
            data=json.dumps(body).encode() if body is not None else None, headers=headers)
        return self.opener.open(request, timeout=15)

    def json(self, path, body=None):
        with self.open(path, body) as response:
            return json.load(response)

    def create(self, title):
        return self.json("/api/conversations", {"title": title})["id"]

    def action(self, conversation, body):
        return self.json("/api/conversations/" + conversation, body)

    def state(self, conversation):
        return self.json("/api/conversations/" + conversation)

    def complete(self, conversation, body, *, timeout=600):
        job = self.action(conversation, body)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.state(conversation)
            current = next(j for j in state["jobs"] if j["id"] == job["id"])
            if current["status"] not in ("running", "queued"):
                if current["status"] != "complete":
                    raise ValueError("APP_SMOKE_JOB_FAILED:" + json.dumps(current))
                return state
            time.sleep(.1)
        raise TimeoutError("APP_SMOKE_JOB_TIMEOUT:" + job["id"])


def _zero_calls(app, state):
    for key in ("generation_calls", "native_calls", "search_calls"):
        if state["metrics"].get(key, 0) != 0:
            raise ValueError("APP_SMOKE_SPENT_CALLS:" + key)
    if any((app.store.root / name).exists() for name in ("search-reservations.json", "search-grants.json")):
        raise ValueError("APP_SMOKE_RESERVED_SEARCHES")


def _deck(client, conversation, state):
    if not state["decks"] or state["messages"][-1]["kind"] != "deck":
        raise ValueError("APP_SMOKE_DECK_CARD_MISSING:" + str(state["messages"][-1]))
    deck = state["decks"][state["active_deck"] - 1]
    if deck["status"] != "QA_PASS" or not deck["ok"]:
        raise ValueError("APP_SMOKE_DECK_QA_FAILED")
    artifacts = {}
    for key, magic in (("pptx", b"PK"), ("pdf", b"%PDF"), ("preview", b"\x89PNG")):
        local = Path(deck[key])
        with client.open(f"/artifacts/{conversation}/{deck['version']}/{local.name}") as response:
            downloaded = response.read()
        if not downloaded.startswith(magic) or downloaded != local.read_bytes():
            raise ValueError("APP_SMOKE_DOWNLOAD_FAILED:" + key)
        artifacts[key] = hashlib.sha256(downloaded).hexdigest()
    return dict(version=deck["version"], template=deck["template"], slides=deck["slides"],
                status=deck["status"], delivery=deck["delivery"], edit=deck["edit"],
                mapping=deck["mapping"], downloaded_sha256=artifacts)


def run_replay_smoke():
    started = time.monotonic()
    rows, journeys = [], []
    with tempfile.TemporaryDirectory(prefix="matn-app-replay-smoke-") as folder:
        app = App(folder, fake=True)
        server = make_server(app, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = _Client(server)
            bootstrap = client.json("/api/bootstrap")
            if not bootstrap["fake"] or bootstrap["search_remaining"] != 0:
                raise ValueError("APP_SMOKE_FIXTURE_MODE_REQUIRED")
            for path in ("/", "/app.js", "/app.css"):
                with client.open(path) as response:
                    if not response.read():
                        raise ValueError("APP_SMOKE_STATIC_MISSING:" + path)
            # Planning is an explicitly labelled fixture, never a fresh topic run.
            plan = client.create("Offline plan review")
            planned = client.complete(plan, {"text": "Public service access"})
            if len(planned["plans"][-1]["plan"]["facets"]) != 4 or not planned["pending_plan"]:
                raise ValueError("APP_SMOKE_PLAN_FAILED")
            _zero_calls(app, planned)
            topic = None
            for name in ("devH", "H", "A"):
                conversation = client.create("Replay " + name)
                state = client.complete(conversation, {"action": "replay", "run": name})
                if not state["catalogs"] or not state["evidence"]["citations"]:
                    raise ValueError("APP_REPLAY_SMOKE_FAILED:" + name)
                _zero_calls(app, state)
                rows.append(dict(run=name, units=state["metrics"]["units"], sources=state["metrics"]["sources"],
                                 generation_calls=0, native_calls=0, search_calls=0))
                if name == "devH":
                    topic = conversation
            # The topic journey reopens actual saved evidence and renders a deck.
            state = client.complete(topic, {"text": "How can administrative changes reduce queue waiting times in government offices?"})
            if state["messages"][-1]["kind"] != "answer" or state["messages"][-1]["result"]["citations"]:
                raise ValueError("APP_SMOKE_REPLAY_ANSWER_FAILED")
            topic_answer_kind = state["messages"][-1]["result"]["answer_kind"]
            state = client.complete(topic, {"action": "build", "template": "ministry_light"})
            journeys.append(dict(journey="topic_saved_research", answer_kind=topic_answer_kind,
                                 deck=_deck(client, topic, state)))
            _zero_calls(app, state)
            # The file journey reads real exact JSON pointers, with no invented findings.
            files = client.create("Public service files")
            source = json.dumps({"access": {"booking": "Appointment booking is available online.",
                    "hours": "Offices publish their opening times."}}).encode()
            state = client.complete(files, {"action": "upload", "files": [dict(name="public-access.json",
                                              data=base64.b64encode(source).decode())]})
            if state["messages"][-1]["kind"] != "overview" or not state["evidence"]["citations"]:
                raise ValueError("APP_SMOKE_FILE_OVERVIEW_FAILED")
            state = client.complete(files, {"text": "What is available online?"})
            answer = state["messages"][-1]["result"]
            if answer["status"] != "abstained" or answer["citations"] or "Appointment booking is available online." in answer["text"]:
                raise ValueError("APP_SMOKE_FIXTURE_GENERATED_ANSWER_BOUNDARY_FAILED")
            state = client.complete(files, {"action": "build", "template": "editorial"})
            first = _deck(client, files, state)
            original_hashes = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
                               for p in (state["decks"][0]["pptx"], state["decks"][0]["storyboard"])}
            state = client.complete(files, {"action": "edit", "edit": {"op": "change_template", "template": "midnight"}})
            edited = _deck(client, files, state)
            if edited["version"] != 2 or edited["template"] != "midnight" or edited["mapping"] != "typed":
                raise ValueError("APP_SMOKE_TYPED_EDIT_FAILED")
            if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != digest for p, digest in original_hashes.items()):
                raise ValueError("APP_SMOKE_EDIT_OVERWROTE_PARENT")
            client.action(files, {"action": "restore", "version": 1})
            restored = client.state(files)
            if restored["active_deck"] != 1 or len(restored["decks"]) != 2:
                raise ValueError("APP_SMOKE_RESTORE_FAILED")
            if Store(folder).get(files)["decks"] != restored["decks"]:
                raise ValueError("APP_SMOKE_PERSISTENCE_FAILED")
            with client.open("/api/conversations/" + files + "/events") as response:
                sse = b"".join(response.readline() for _ in range(5))
                if b"id: " not in sse or b"data: " not in sse:
                    raise ValueError("APP_SMOKE_SSE_FAILED")
            _zero_calls(app, restored)
            journeys.append(dict(journey="attached_json", answer_kind=answer["answer_kind"],
                                 citation_pointer="/access/booking", deck=first, edited_deck=edited,
                                 parent_unchanged=True, restored_version=1, persisted=True, sse=True))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            app.close()
    return dict(status="APP_REPLAY_SMOKE_PASS", runs=rows, journeys=journeys,
                http=True, real_rendering=True, generation_calls=0, native_calls=0, search_calls=0,
                scope="Saved research and exact attached JSON; fixture plan; no new research or model inference",
                seconds=round(time.monotonic() - started, 2))
