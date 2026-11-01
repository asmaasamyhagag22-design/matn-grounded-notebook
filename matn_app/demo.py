"""Explicit offline doubles for the app's end-to-end research smoke tests.

The real ``run_v2`` reader, checkpoints, writer and verification code execute;
search, generation and native entailment are fake and labelled throughout.
No content here is evidence about the user's topic.
"""
from __future__ import annotations

from html import escape
from dataclasses import replace
import json
from pathlib import Path
import time

from matn_chat.readiness import write
from matn_verification.contracts import Check

LABEL = "OFFLINE FIXTURE: fake search, fake generation and fake native verification. Not research evidence."


def plan_for(topic: str) -> dict:
    return dict(facets=[dict(id=f"axis{i}", label=label, success=f"Explain {label.lower()} from the supplied sources",
                             searches=[f"{topic} {label.lower()}"])
                       for i, label in enumerate(("Scope", "Requirements", "Options", "Evaluation"), 1)])


class FakeSearch:
    name = "app-offline-fixture"

    def __init__(self):
        self.calls = []

    def search(self, query):
        self.calls.append(query)
        return dict(provider=self.name, query=query, at=time.time(), response=dict(results=[
            dict(url="https://fixture.example/source", title="Offline synthetic source", content="Snippet is not evidence")]))


class FakeGenerator:
    def __init__(self, plan):
        self.plan = plan
        self.calls = []

    def generate(self, body):
        self.calls.append(body)
        props = body["format"]["properties"]
        if "facets" in props:
            value = self.plan
        else:
            # Selection output is schema-constrained rN -> enum letters.
            value = {}
            for key, prop in props.items():
                choices = prop["properties"]["pick"]
                letters = choices["items"]["enum"]
                picked = [letters[0]] if choices.get("maxItems", 0) else []
                value[key] = dict(pick=picked, fit="full" if picked else "none")
        return dict(done=True, done_reason="stop", response=json.dumps(value), thinking="")


class FakeNative:
    def __init__(self):
        self.calls = []

    def check(self, text, evidence, target):
        self.calls.append(dict(target=target, text=text))
        return Check(target=target, layer="L4", verdict="pass")

    def close(self):
        pass


def research(folder, topic, audience="General audience", plan=None):
    """Write normal saved-run artifacts using only explicitly labelled doubles."""
    from matn_research.fast import run_v2
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    plan = plan or plan_for(topic)
    brief = dict(topic=topic, audience=audience, goal="Prepare an offline synthetic app demonstration",
                 scope=LABEL, language="English", public_topic=True)
    provider, generator, native = FakeSearch(), FakeGenerator(plan), FakeNative()
    paragraphs = [f"The synthetic source explains {facet['label'].lower()} through exact original passages."
                  for facet in plan["facets"]]
    html = ("<html><head><title>Offline synthetic source</title></head><body><main>" +
            "".join("<p>" + escape(p) + "</p>" for p in paragraphs) + "</main></body></html>")

    def fetch(url, **kwargs):
        return dict(body=html.encode(), final_url=url, content_type="text/html; charset=utf-8",
                    fetched_at=time.time(), redirects=[])

    result = run_v2(folder, brief, provider=provider, generator=generator, native=native,
                    counter=lambda text: max(1, len(text) // 4), fetch=fetch, plan_override=plan,
                    config=dict(embeddings=False, gap=False, synthesis=False, search_cap=4, source_cap=4,
                                search_workers=1, read_workers=1), classification=LABEL)
    result.update(classification=LABEL, fake=True, generation=0, native=0, live_search=0,
                  fake_search_attempts=len(provider.calls), fake_generation_attempts=len(generator.calls),
                  fake_native_attempts=len(native.calls), full_journey_accepted=False)
    write(folder / "outcome.json", result)
    if (folder / "v1.json").exists():
        from matn_deck.catalog_adapters import from_research
        catalog = from_research(folder)
        catalog = replace(catalog, origin=dict(catalog.origin, fake=True, classification=LABEL))
        write(folder / "catalog.json", json.loads(catalog.to_json()))
    return result
