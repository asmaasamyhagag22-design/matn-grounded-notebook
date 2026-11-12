"""Conversation actions composed from the existing reading, research, chat and deck engines."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time

from git_environment import git_environment

from .jobs import Jobs
from .runtime import DATA_ROOT, ORIGINAL, ROOT, Processes, preflight, safe_progress, worker_result
from .store import DEFAULT_AUDIENCE, Store, read, write

class App:
    def __init__(self, data=DATA_ROOT / "app", *, fake=False, search_budget=0, process_runner=None, research_v2=False, answer_profile=None):
        if type(search_budget) is not int or search_budget < 0:
            raise ValueError("Search budget must be a nonnegative integer")
        if ORIGINAL.resolve() != ROOT.resolve() and Path(data).resolve().is_relative_to(ORIGINAL.resolve()):
            raise ValueError("Choose an app data directory outside the read-only vault")
        self.store = Store(data)
        self.fake = fake
        self.answer_profile = answer_profile
        self.processes = process_runner or Processes()
        self.jobs = Jobs(self.store)
        self.search_budget = search_budget
        # Research is frozen on the delivery code; v2 is a developer option.
        self.research_v2 = research_v2 is True
        self.readiness = preflight(fake=fake, search_budget=search_budget)

    @property
    def labels(self):
        from .labels import LabelStore
        return LabelStore()

    def close(self):
        self.processes.close()
        self.jobs.close()

    def bootstrap(self):
        try:
            from matn_deck.product_templates import product_templates
            templates = [dict(id=t.id, name=t.meta.get("name_en", t.id)) for t in product_templates()]
        except ImportError:
            templates = []
        return dict(conversations=self.store.list(), preflight=self.readiness, templates=templates,
                    replays=[], busy=bool(self.jobs.active), fake=self.fake,
                    search_remaining=self._search_remaining(), default_audience=DEFAULT_AUDIENCE,
                    research_v2=self.research_v2)

    def _search_remaining(self):
        budget = read(self.store.root / "search-reservations.json", {"reserved": 0})
        grants = read(self.store.root / "search-grants.json", {"cap": 0})
        return max(0, self.search_budget + grants["cap"] - budget["reserved"])

    def _grant_searches(self, conversation):
        with self.store.lock:
            grants = read(self.store.root / "search-grants.json", {"cap": 0, "grants": []})
            grants["cap"] += 12
            grants["grants"].append(dict(searches=12, conversation=conversation, at=time.time(),
                                         authority="Explicit plan checkbox and Start research action"))
            write(self.store.root / "search-grants.json", grants)
        self.store.message(conversation, "user", "Approved up to 12 web searches for this research run.")

    def _reserve_searches(self):
        with self.store.lock:
            if self._search_remaining() < 12:
                raise ValueError("NO-GO: an explicit 12-search allowance is required. Approve up to 12 web searches in the plan before starting. An operator can also set an app allowance with --search-budget N. Meeting ledgers are never used")
            budget = read(self.store.root / "search-reservations.json", {"reserved": 0})
            budget["reserved"] += 12
            write(self.store.root / "search-reservations.json", budget)

    def _job_folder(self, conversation, job):
        folder = self.store.folder(conversation) / "jobs" / job["id"]
        folder.mkdir(parents=True, exist_ok=True)
        self.store.update(conversation, lambda v: next(j for j in v["jobs"] if j["id"] == job["id"]).update(folder=str(folder)))
        return folder

    def _worker(self, module, request, folder, emit, *, timeout=1800):
        request = dict(request, output=str(folder / "result.json"), workdir=str(folder), fake=self.fake)
        write(folder / "request.json", request)
        try:
            rc = self.processes.run([sys.executable, "-B", "-m", module, folder / "request.json"], folder, emit,
                                    progress=lambda: safe_progress(folder), timeout=timeout)
        except (TimeoutError, RuntimeError) as exc:
            partial = read(folder / "partial-result.json")
            if partial and partial.get("catalog"):
                return dict(partial, status="partial", text="The job stopped; completed source evidence is retained.",
                            failures=partial.get("failures", []) + [dict(error=type(exc).__name__, detail=str(exc))])
            raise
        value = worker_result(folder, folder / "result.json")
        if rc and value.get("partial"):
            value = dict(value["partial"], status="partial", failures=value.get("failures", []))
        if rc and not value.get("catalog") and value.get("status") == "failed":
            raise ValueError("; ".join(x.get("detail", x.get("error", "Worker failed")) for x in value.get("failures", [])))
        return value

    def _remember_evidence(self, conversation, result):
        def change(v):
            for key in ("catalogs", "documents", "notebooks"):
                singular = {"catalogs": "catalog", "documents": "document", "notebooks": "notebook"}[key]
                values = result.get(key, []) or ([result[singular]] if result.get(singular) else [])
                for item in values:
                    if item and item not in v[key]:
                        v[key].append(item)
        self.store.update(conversation, change)
        self._refresh_metrics(conversation, result.get("metrics", {}))

    def _refresh_metrics(self, conversation, measured=None):
        value = self.store.get(conversation)
        catalog = None
        if value["catalogs"]:
            from .evidence import merge_catalogs
            catalog = merge_catalogs(value["catalogs"], topic=value["title"], audience=value["audience"])
        def change(v):
            old = v.get("metrics", {})
            old.update(sources=len(catalog.sources) if catalog else 0, units=len(catalog.units) if catalog else 0,
                       vendor_sources=sum(s.type == "commercial-vendor" for s in catalog.sources) if catalog else 0,
                       vendor_share=(sum(s.type == "commercial-vendor" for s in catalog.sources) / len(catalog.sources)
                                     if catalog and catalog.sources else 0),
                       source_types={s.id: s.type for s in catalog.sources} if catalog else {},
                       last_step=measured or {})
            if measured:
                old["seconds"] = round(old.get("seconds", 0) + measured.get("seconds", 0), 2)
                calls = measured.get("generation_calls", measured.get("model_calls"))
                if calls is not None:
                    old["generation_calls"] = old.get("generation_calls", 0) + calls
                else:
                    old["generation_calls_incomplete"] = True
                old["verification_blocks"] = old.get("verification_blocks", 0) + measured.get("verification_blocks", 0)
                for key in ("native_calls", "search_calls"):
                    if measured.get(key) is not None:
                        old[key] = old.get(key, 0) + measured[key]
            v["metrics"] = old
        self.store.update(conversation, change)

    def evidence(self, conversation):
        value = self.store.get(conversation)
        if not value["catalogs"]:
            return dict(citations=[], axes=[], gaps=[])
        from .evidence import catalog_citations, merge_catalogs
        catalog = merge_catalogs(value["catalogs"], topic=value["title"], audience=value["audience"])
        return dict(citations=catalog_citations(catalog), axes=[dict(id=a.id, title=a.title,
                    units=[u.id for u in catalog.units if u.axis == a.id]) for a in catalog.plan.axes],
                    gaps=[dict(axis=g.axis, label=g.label, reason=g.reason, missing=g.missing) for g in catalog.gaps],
                    regions=catalog.origin.get('region_summaries',{}),source_metadata=catalog.origin.get('source_metadata',{}))

    def _scoreboard(self):
        from eval.research.dashboard.data import collect,summarize
        result=collect(ORIGINAL)
        seen={Path(r['folder']).resolve() for r in result['runs']}
        for row in self.store.list():
            for run in self.store.get(row['id'])['runs']:
                folder=Path(run['folder']).resolve()
                if folder in seen or not folder.is_relative_to(self.store.root) or not folder.is_dir():continue
                if any('sealed' in part.casefold() for part in folder.parts):continue
                key='app/'+row['id']+'/'+folder.parent.name
                result['runs'].append(summarize(key,folder,ORIGINAL));seen.add(folder)
        return result

    def _saved_run(self, name):
        from eval.research.dashboard.data import collect
        row = next((r for r in self._scoreboard()["runs"] if r["id"] == name), None)
        if row:
            folder = Path(row["folder"]).resolve()
            if (folder.is_relative_to((ORIGINAL / "out").resolve()) or folder.is_relative_to(self.store.root)) and not any("sealed" in p.lower() for p in folder.parts):
                return folder
        raise ValueError("Choose a saved run from Evaluation")

    def action(self, conversation, value):
        state = self.store.get(conversation)
        action = value.get("action", "message")
        if action == "audience":
            audience = str(value.get("audience", "")).strip()
            if not 1 <= len(audience) <= 500 or "\x00" in audience:
                raise ValueError("Audience must contain 1–500 characters")
            self.store.update(conversation, lambda v: v.update(audience=audience,audience_explicit=True))
            self.store.message(conversation, "assistant", "Audience set to: " + audience + ". Existing evidence is retained; the next research plan or presentation rebuild will use this audience.")
            return {"ok": True}
        if action == "clarify":
            from .clarification import resolve
            pending=state.get('pending_research')
            if not pending:raise ValueError('No clarification is pending')
            topic,audience=resolve(pending,value,state['audience'] if state.get('audience_explicit') else '')
            self.store.update(conversation,lambda v:v.update(audience=audience,audience_explicit=True,pending_research=None))
            self.store.message(conversation,'user','Research '+topic+'; audience: '+audience)
            return self.jobs.submit(conversation,'Planning research',lambda j,e:self._plan(conversation,topic,j,e,clarified=True))
        if action == "rename":
            title = str(value.get("title", "")).strip()
            if not title:
                raise ValueError("Conversation title is required")
            self.store.update(conversation, lambda v: v.update(title=title[:140]))
            return {"ok": True}
        if action == "delete":
            self.store.update(conversation, lambda v: v.update(deleted=True))
            return {"ok": True}
        if action == "restore":
            index = int(value.get("version", 0))
            if not 1 <= index <= len(state["decks"]):
                raise ValueError("Unknown deck version")
            self.store.update(conversation, lambda v: v.update(active_deck=index))
            self.store.message(conversation, "assistant", "Restored presentation version " + str(index) + ".", kind="deck", version=index)
            return {"ok": True}
        if action == "upload":
            uploads = value.get("files", [])
            if not 1 <= len(uploads) <= 8:
                raise ValueError("Attach one to eight PDF or JSON files")
            inputs = []
            for upload in uploads:
                name = Path(str(upload.get("name", ""))).name
                if Path(name).suffix.lower() not in (".pdf", ".json"):
                    raise ValueError("Only PDF and JSON files are supported")
                data = base64.b64decode(upload.get("data", ""), validate=True)
                if not data or len(data) > 50 * 1024 * 1024:
                    raise ValueError("Each file must contain 1 byte to 50 MiB")
                target = self.store.folder(conversation) / "uploads" / hashlib.sha256(data).hexdigest()[:16] / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(data)
                inputs.append(str(target))
            self.store.message(conversation, "user", "Attached " + ", ".join(Path(p).name for p in inputs), files=[Path(p).name for p in inputs])
            if state["title"] == "New conversation":
                self.store.update(conversation, lambda v: v.update(title=Path(inputs[0]).stem[:100]))
            return self.jobs.submit(conversation, "Reading files", lambda j, e: self._ingest(conversation, inputs, j, e))
        if action == "replay":
            name = value.get("run")
            run = self._saved_run(name)
            return self.jobs.submit(conversation, "Opening saved research", lambda j, e: self._replay(conversation, run, j, e, name))
        if action == "open_partial":
            index = int(value.get("run", len(state["runs"]) - 1))
            if not 0 <= index < len(state["runs"]):
                raise ValueError("Choose a saved conversation run")
            run = Path(state["runs"][index]["folder"])
            if not any((run / name).is_file() for name in ("v1.json", "projection.json")):
                raise ValueError("This attempt has not saved a verified result yet. Its source files and progress are retained")
            return self.jobs.submit(conversation, "Opening partial research", lambda j, e: self._replay(
                conversation, run, j, e, None, add_run=False))
        if action == "start":
            if not state["plans"]:
                raise ValueError("Create a research plan first")
            code = value.get("code", "delivery")
            if code not in ("v2", "delivery"):
                raise ValueError("Choose v2 or delivery research")
            if code == "v2" and not self.research_v2:
                raise ValueError("Research v2 is a developer option; start the app with --dev-research-v2")
            if value.get("plan"):
                from matn_research.fast import PlanV2
                plan = PlanV2.model_validate(value["plan"]).model_dump(mode="json")
                self.store.update(conversation, lambda v: v["plans"][-1].update(plan=plan))
            if not self.fake:
                if self._search_remaining() < 12 and value.get("approve_searches") is True:
                    self._grant_searches(conversation)
                self._reserve_searches()
            approved = json.loads(json.dumps(self.store.get(conversation)["plans"][-1]))
            return self.jobs.submit(conversation, "Researching public sources", lambda j, e: self._research(conversation, j, e, code, approved))
        if action == "bench":
            return self.jobs.submit(conversation, "Running offline bench", lambda j, e: self._bench(conversation, j, e))
        if action in ("build", "edit"):
            return self.jobs.submit(conversation, "Building presentation" if action == "build" else "Editing presentation",
                                    lambda j, e: self._deck(conversation, value, j, e))
        if action == "plan":
            instruction = str(value.get("instruction", "")).strip()
            return self.jobs.submit(conversation, "Updating research plan", lambda j, e: self._edit_plan(conversation, instruction, j, e))
        if action != "message":
            raise ValueError("Unknown action")
        text = str(value.get("text", "")).strip()
        if not text or len(text) > 8000:
            raise ValueError("Message must contain 1–8000 characters")
        self.store.message(conversation, "user", text)
        if state.get('pending_research'):
            parts=text.rsplit(';',1)
            if len(parts)==2:
                return self.action(conversation,dict(action='clarify',choice='other',topic=parts[0].strip(),audience=parts[1].strip()))
            self.store.message(conversation,'assistant','Use the choices below, or reply “intended topic; audience”.',kind='clarification',clarification=state['pending_research'])
            return dict(ok=True,needs_clarification=True)
        audience_edit = re.match(r"(?:change|set)\s+(?:the\s+)?audience\s+(?:to\s+)?(.+)", text, re.I | re.S)
        if audience_edit:
            return self.action(conversation, dict(action="audience", audience=audience_edit.group(1)))
        if re.search(r"\b(make|create|build|generate|update|rebuild)\b.*\b(presentation|deck|slides)\b", text, re.I):
            return self.action(conversation, dict(action="build", template=value.get("template", "ministry_light")))
        if state["active_deck"] and re.search(r"\b(slide|slides|template|shorten|retitle|reorder)\b", text, re.I):
            return self.action(conversation, dict(action="edit", instruction=text))
        deeper = re.match(r"(?:dig deeper(?: on| into)?|research|investigate)\s+(.+)", text, re.I | re.S)
        if not state['catalogs'] and any(j['kind']=='Reading files' and j['status'] in ('running','queued') for j in state['jobs']):
            message='The first source is still being read. No answer evidence is ready yet; retry this question when reading finishes.'
            return self.jobs.submit(conversation,'Checking source readiness',lambda j,e:self.store.message(
                conversation,'assistant',message,kind='answer',result=dict(status='processing',text=message,
                question=text,retryable=True,citations=[],failures=[],metrics=dict(model_calls=0,native_calls=0,search_calls=0))))
        if deeper or (not state["catalogs"] and not state["plans"]):
            topic = deeper.group(1) if deeper else text
            if state["title"] == "New conversation":
                self.store.update(conversation, lambda v: v.update(title=topic[:100]))
            return self.jobs.submit(conversation, "Planning research", lambda j, e: self._plan(conversation, topic, j, e))
        if state["plans"] and (state.get("pending_plan") or not state["catalogs"]):
            return self.action(conversation, dict(action="plan", instruction=text))
        return self.jobs.submit(conversation, "Answering from evidence", lambda j, e: self._answer(conversation, text, j, e))

    def _ingest(self, conversation, inputs, job, emit):
        folder = self._job_folder(conversation, job)
        old = self.store.get(conversation)
        coverage={}
        for notebook in old['notebooks']:
            coverage.update(read(Path(str(notebook)+'.structures.json'),{}).get('source_coverage',{}))
        result = self._worker("matn_app.evidence_worker", dict(operation="ingest", inputs=inputs,
                              source_cache=str(self.store.root / "source-cache"),
                              source_coverage=coverage,
                              catalogs=old["catalogs"], documents=old["documents"], audience=old["audience"]), folder, emit, timeout=None)
        self._remember_evidence(conversation, result)
        if result.get("catalog"):
            # Ingestion already returns all previous evidence plus the new files.
            # Keeping cumulative historical catalogs would duplicate empty axes
            # and numeric facts even though unit/source IDs are deduplicated.
            self.store.update(conversation, lambda v: v.update(catalogs=[result["catalog"]]))
        self.store.message(conversation, "assistant", result.get("text", "Sources read."), kind="overview", result=result)
        if old["active_deck"]:
            self.store.message(conversation, "assistant", "The new source is available for questions. Say ‘update the presentation’ to rebuild against all current evidence.")

    def _answer(self, conversation, question, job, emit):
        folder = self._job_folder(conversation, job)
        state = self.store.get(conversation)
        result = self._worker("matn_app.evidence_worker", dict(operation="answer", catalogs=state["catalogs"],
                             notebooks=state["notebooks"], question=question, session=conversation,
                             session_dir=str(self.store.folder(conversation) / "answer-sessions"),
                             **(dict(answer_profile=self.answer_profile) if self.answer_profile else {})), folder, emit)
        self._refresh_metrics(conversation, result.get("metrics"))
        self.store.message(conversation, "assistant", result["text"], kind="answer", result=result)

    def _plan(self, conversation, topic, job, emit, *, clarified=False):
        folder = self._job_folder(conversation, job)
        state = self.store.get(conversation)
        run = folder / "plan"
        clarification_calls=0
        if not self.fake and not clarified:
            from .clarification import known_senses,question
            senses=known_senses(topic)
            sense_failed=False
            if not senses:
                emit('Checking the intended subject before planning; no web searches')
                try:
                    result=self._worker('matn_app.research_worker',dict(operation='clarify',topic=topic),folder/'sense-check',emit)
                    senses=result['senses'];clarification_calls=result['metrics']['generation_calls']
                except Exception as exc:
                    # A failed check cannot silently choose a subject.
                    senses=['The meaning I will specify','Another meaning I will specify'];sense_failed=True
                    emit('Sense check did not complete; asking for explicit scope: '+type(exc).__name__)
                    with (self.store.root/'recovered.jsonl').open('a') as stream:
                        stream.write(json.dumps(dict(status='RECOVERED',cause='Local topic sense check failed: '+type(exc).__name__,action='Asked for explicit subject and audience before planning; no search',at=time.time()))+'\n')
            pending=question(topic,senses,state.get('audience_explicit',False))
            if pending:
                if sense_failed:pending['require_topic']=True
                self.store.update(conversation,lambda v:v.update(pending_research=pending))
                self.store.message(conversation,'assistant',pending['question'],kind='clarification',clarification=pending)
                self._refresh_metrics(conversation,dict(generation_calls=clarification_calls,search_calls=0))
                return dict(status='needs_clarification')
        if self.fake:
            plan = {"facets": [dict(id=k, label=label, success="Find cited public evidence for " + label.lower(), searches=[topic + " " + label.lower()]) for k, label in (("context", "Context"), ("evidence", "Evidence"), ("applications", "Applications"), ("limits", "Limitations"))]}
            calls = 0
        else:
            emit("Planning four research axes with the pinned local model; no web searches")
            rc = self.processes.run([sys.executable, "-B", "-m", "matn_research", "live", "--out", run,
                                    "--topic", topic, "--audience", state["audience"], "--ledger", folder / "ledger", "--plan-only"], folder, emit,
                                   progress=lambda: self._research_progress(run, folder / "ledger"), timeout=1200)
            outcome = read(run / "outcome.json", {})
            if rc or not outcome.get("plan"):
                raise ValueError("Local planning did not complete. No search was made")
            plan = outcome["plan"]
            calls = read(folder / "ledger/ledger.json", {}).get("calls", {}).get("generation", 0)
        item = dict(topic=topic, audience=state["audience"], plan=plan, searches=12, generation_calls=calls+clarification_calls,
                    created_at=time.time(), folder=str(folder))
        self.store.update(conversation, lambda v: (v["plans"].append(item), v.update(pending_plan=True)))
        self.store.message(conversation, "assistant", "I understand the topic as “" + topic + "”. Audience: " + state["audience"] + ". I propose these four axes. Edit them here or by chat, then start research. Budget: up to 12 searches; approximately 10 minutes on this CPU (new v2 quality is unmeasured).", kind="plan", plan=item)
        self._refresh_metrics(conversation, dict(generation_calls=calls+clarification_calls))

    def _edit_plan(self, conversation, instruction, job, emit):
        state = self.store.get(conversation)
        if not state["plans"]:
            raise ValueError("No plan to edit")
        folder = self._job_folder(conversation, job)
        value = self._worker("matn_app.research_worker", dict(plan=state["plans"][-1]["plan"], instruction=instruction), folder, emit)
        item = dict(state["plans"][-1], plan=value["plan"], created_at=time.time())
        self.store.update(conversation, lambda v: (v["plans"].append(item), v.update(pending_plan=True)))
        self.store.message(conversation, "assistant", "Updated the research plan. Review the axes before starting.", kind="plan", plan=item)
        self._refresh_metrics(conversation, value.get("metrics"))

    def _research_progress(self, run, ledger):
        from matn_research.progress import snapshot
        from matn_research.models import LIMITS
        from matn_research.source_type import classify
        result = snapshot(run, ledger, planned={k: LIMITS[k] for k in ("generation", "native")})
        result.pop("updated_at", None)
        reads = read(Path(run) / "reading-status.json", [])
        result["sources"] = [dict(url=r.get("final_url") or r.get("url"), status=r.get("status"),
                                  source_type=classify(r.get("final_url") or r.get("url") or "")["label"],
                                  format=r.get("coverage", {}).get("kind", "unknown")) for r in reads]
        return result

    def _delivery_tree(self):
        folder = self.store.root / "runtime/delivery-2026-10-30"
        if not (folder / "matn_research/__main__.py").exists():
            folder.mkdir(parents=True, exist_ok=True)
            archive = self.store.root / "runtime/delivery.tar"
            with archive.open("wb") as output:
                subprocess.run(["git", "archive", "delivery-2026-10-30"], cwd=ROOT, env=git_environment(), stdout=output, check=True)
            with tarfile.open(archive) as stream:
                stream.extractall(folder, filter="data")
        return folder

    def _research(self, conversation, job, emit, code, approved=None):
        started = time.monotonic()
        folder = self._job_folder(conversation, job)
        state = self.store.get(conversation)
        item = approved or state["plans"][-1]
        run = folder / "research"
        write(folder / "approved-plan.json", item["plan"])
        self.store.update(conversation, lambda v: v["runs"].append(dict(folder=str(run), code=code, status="running", topic=item["topic"])))
        self.store.update(conversation, lambda v: v.update(pending_plan=False))
        if self.fake:
            from .demo import research
            research(run, item["topic"], item.get("audience", state["audience"]), item["plan"])
            rc = 0
        else:
            tree = ROOT if code == "v2" else self._delivery_tree()
            # Frozen delivery code predates ADR-0035; the launcher applies the current
            # search retention policy to it without changing the frozen tree.
            launch = [] if tree == ROOT else [str(ROOT / "matn_app/frozen_research.py"), "--tree", str(tree)]
            try:
                rc = self.processes.run([sys.executable, "-B", *launch, "-m", "matn_research", "live", "--topic", item["topic"],
                                        "--audience", item.get("audience", state["audience"]), "--out", run, "--ledger", folder / "ledger", "--plan", folder / "approved-plan.json"],
                                       folder, emit, cwd=tree, progress=lambda: self._research_progress(run, folder / "ledger"), timeout=1250)
            except (TimeoutError, RuntimeError) as exc:
                rc = 1
                emit("Research stopped; reopening any completed verified evidence: " + str(exc)[:200])
        ledger = read(folder / "ledger/ledger.json", {})
        calls = ledger.get("calls", {})
        self._refresh_metrics(conversation, dict(generation_calls=0 if self.fake else calls.get("generation"),
                              native_calls=0 if self.fake else calls.get("native"),
                              search_calls=0 if self.fake else read(run / "state.json", {}).get("search_attempts"),
                              seconds=time.monotonic() - started))
        self.store.update(conversation, lambda v: next(r for r in v["runs"] if r["folder"] == str(run)).update(status="partial" if rc else "complete"))
        self._replay(conversation, run, job, emit, None, add_run=False)
        outcome = read(run / "outcome.json", {})
        self.store.update(conversation, lambda v: next(r for r in v["runs"] if r["folder"] == str(run)).update(status="partial" if rc else outcome.get("status", "complete")))

    def _replay(self, conversation, run, job, emit, name, *, add_run=True):
        from matn_deck.catalog_adapters import from_research
        folder = self._job_folder(conversation, job)
        emit("Opening saved verified units; zero model and search calls")
        if not any((Path(run) / filename).exists() for filename in ("v1.json", "projection.json")):
            outcome = read(Path(run) / "outcome.json", {})
            if add_run:
                self.store.update(conversation, lambda v: v["runs"].append(dict(folder=str(run), replay=name, status="saved failure")))
            self.store.message(conversation, "assistant", "This saved run did not publish a verified result. " + str(outcome.get("detail") or outcome.get("error") or outcome.get("status") or "Its reading/progress artifacts are retained.")[:400],
                               kind="failure", result=dict(status="saved failure", citations=[], generation_calls=0, search_calls=0))
            self._refresh_metrics(conversation, dict(model_calls=0))
            return
        catalog = from_research(run)
        if not self.fake:
            from matn_research.quality import filter_saved_catalog
            catalog=filter_saved_catalog(catalog)
        path = folder / "catalog.json"
        path.write_text(catalog.to_json(), encoding="utf-8")
        notebook = None
        # Research index import is lexical and uses saved structures only.
        if not self.fake:
            rc = self.processes.run([sys.executable, "-B", "-m", "matn_research.notebook_import", "--run", run,
                                    "--out", folder / "notebook"], folder, emit, timeout=180)
            if rc == 0:
                notebook = str(folder / "notebook/notebook.db")
        self._remember_evidence(conversation, dict(catalog=str(path), notebook=notebook, metrics=dict(model_calls=0)))
        if add_run:
            self.store.update(conversation, lambda v: v["runs"].append(dict(folder=str(run), replay=name, status="saved")))
        if name:
            self.store.update(conversation, lambda v: v.update(title=catalog.plan.topic[:100] or name))
        from .evidence import catalog_citations
        groups = []
        for axis in catalog.plan.axes:
            units = [u for u in catalog.units if u.axis == axis.id]
            groups.append(axis.title + "\n" + ("\n".join("• " + u.text + " [" + u.id + "]" for u in units) if units else "No verified units were displayed for this axis."))
        from matn_research.quality import commercial_warning
        vendor=commercial_warning(catalog.sources,catalog.units)
        if vendor['warning']:groups.insert(0,vendor['warning'])
        self.store.message(conversation, "assistant", "Saved research replay — no new calls.\n\n" + "\n\n".join(groups) if add_run else "\n\n".join(groups), kind="findings",
                           result=dict(vendor=vendor,citations=catalog_citations(catalog), gaps=[dict(axis=g.axis, reason=g.reason) for g in catalog.gaps], status="partial" if catalog.gaps else "verified evidence; completeness unmeasured"))

    def _deck(self, conversation, request, job, emit):
        from .evidence import merge_catalogs
        state = self.store.get(conversation)
        if not state["catalogs"]:
            raise ValueError("Add files or open verified research before building a deck")
        folder = self._job_folder(conversation, job)
        catalog = merge_catalogs(state["catalogs"], folder / "merged-catalog.json", topic=state["title"], audience=state["audience"])
        parent = state["decks"][state["active_deck"] - 1] if state["active_deck"] else None
        operation = request.get("action", "build")
        if operation == "edit" and not parent:
            raise ValueError("Build a presentation before editing it")
        # An edit uses its parent's unchanged catalog identity. A rebuild adopts new sources explicitly.
        if operation == "edit":
            catalog = parent["catalog"]
        value = dict(operation=operation, catalog=str(catalog), template=request.get("template") or (parent or {}).get("template", "ministry_light"),
                     parent_storyboard=(parent or {}).get("storyboard"))
        for key in ("instruction", "edit"):
            if request.get(key) is not None:
                value[key] = request[key]
        output = folder / "deck"
        output.mkdir()
        write(folder / "deck-request.json", dict(value, output=str(output), workdir=str(folder), fake=self.fake))
        emit("Composing exact verified sentences, rendering PPTX and PDF, then running both QA engines")
        rc = self.processes.run([sys.executable, "-B", "-m", "matn_app.deck_worker", folder / "deck-request.json"], folder, emit, timeout=600)
        result = worker_result(folder, output / "result.json")
        self._refresh_metrics(conversation, result.get("metrics"))
        if not result.get("ok"):
            if result.get("status") == "UNSUPPORTED_EDIT":
                text = result.get("reason", "The presentation operation was not supported.") + " " + " ".join(result.get("alternatives", []))
                kind = "unsupported"
            else:
                gates = result.get("qa", {}).get("failing_slides", {})
                text = "Presentation rendering or QA did not pass. " + result.get("reason", "Failed slide checks: " + json.dumps(gates)) + ". The previous version is retained; this attempt's partial artifacts are saved."
                kind = "failure"
            self.store.message(conversation, "assistant", text, kind=kind, result=result)
            return
        if rc:
            raise ValueError(result.get("reason", "Deck worker failed"))
        number = len(self.store.get(conversation)["decks"]) + 1
        result.update(version=number, template=result.get("template") or value["template"], created_at=time.time())
        self.store.update(conversation, lambda v: (v["decks"].append(result), v.update(active_deck=number)))
        self.store.message(conversation, "assistant", "Presentation version " + str(number) + " is ready for review. Every content statement is copied from verified evidence. " + str(result.get("status", "")), kind="deck", version=number)

    def _bench(self, conversation, job, emit):
        folder = self._job_folder(conversation, job)
        emit("Running the offline shortlist/screening bench; zero model or search calls")
        rc = self.processes.run([sys.executable, "-B", "-m", "eval.research.bench.run", "--data-root", ORIGINAL, "--out", folder / "bench"], folder, emit, timeout=600)
        result = dict(status="PASS" if rc == 0 else "FAILED", folder=str(folder / "bench"), at=time.time())
        write(self.store.root / "bench.json", result)
        self.store.message(conversation, "assistant", "Offline bench: " + result["status"] + ". Results are available in Evaluation.", kind="bench", result=result)

    def evaluation(self):
        from eval.research.dashboard.data import collect
        return dict(owner_labels=self.labels.summary(),labelling_url="/labels/",scoreboard=self._scoreboard(), bench=read(self.store.root / "bench.json"),
                    conversations=[dict(id=r["id"], title=r["title"], metrics=self.store.get(r["id"])["metrics"]) for r in self.store.list()],
                    holdouts=read(self.store.root/"holdout-verdict.json",dict(status="UNMEASURED",search_allowance=self.search_budget)), review="Saved AI review, not human gold")
