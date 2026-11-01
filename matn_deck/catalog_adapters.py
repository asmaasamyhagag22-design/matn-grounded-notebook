"""Adapters into the Evidence Catalog (ADR-0021). Each reads saved results only: no model, no network.

- `from_research(folder)`: a Topic→Research result folder (`projection.json` or `v1.json`, `state.json`,
  `reading-status.json`, `gaps.json`, `synthesis.json` when the run enabled synthesis).
- `from_storyboard(folder, ...)`: the document path, a storyboard folder whose `input.json` names its notebook;
  documents come from the notebook's structure manifest, figures from the reader page caches and the original PDFs.
- `from_json(path)`: a saved catalog, or a JSON source bundle whose every value is copied by JSON Pointer.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

from .catalog import (
    Axis, Context, EvidenceCatalog, Figure, Gap, NumericFact, Plan, ReaderTable, Requirement, Source, Span,
    SynthesisSentence, Unit,
)
from .numeric import facts_for_unit

UPLOADED = "uploaded document"
# A caption is a label plus a title ("Figure 2.8 Digital Skills in ..."); "Figure 2.3 provides ..." is body text.
CAPTION_START = re.compile(r"^(?:Figure|Fig\.|Chart|Exhibit|Map|Box)\s+[A-Z]?\d+(?:[.\-]\d+)*\.?:?\s+[A-Z0-9“\"(]")
FIGURE_SHARE = (0.03, 0.60)  # figure region area as a share of the page: smaller is an icon, larger a backdrop
CAPTION_GAP_PT = 72.0


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path: Path, files: dict[str, str]) -> Any:
    files[str(path)] = _sha(path)
    return json.loads(Path(path).read_bytes())


def _span(ref: dict) -> Span:
    bbox = ref.get("bbox")
    return Span(doc_id=ref["doc_id"], block_id=ref["block_id"], start=int(ref["start"]), end=int(ref["end"]),
                quote=ref["quote"], page_index=ref.get("pdf_page_index"), page_label=ref.get("page_label"),
                bbox=tuple(float(x) for x in bbox) if bbox else None)


def _contexts(display: dict) -> tuple[Context, ...]:
    items = []
    for ctx in display.get("context", []):
        refs = ctx.get("citations") or []
        items.append(Context(quote=ctx["quote"], kind="required", origin=ctx.get("origin", ""),
                             span=_span(refs[0]) if refs and "doc_id" in refs[0] else None))
    local = display.get("local_context") or {}
    for heading in local.get("headings", []):
        items.append(Context(quote=heading["quote"], kind="heading", origin="governing heading", span=_span(heading)))
    for ctx in local.get("preceding", []):
        items.append(Context(quote=ctx["quote"], kind="local", origin="local source context", span=_span(ctx)))
    return tuple(items)


def _plan(task: dict, topic: str, audience: str) -> Plan:
    axes = tuple(Axis(f["id"], f["label"], f.get("query", "")) for f in task["facets"])
    requirements = tuple(Requirement(p["id"], p.get("facet", p["id"]), p["description"], bool(p.get("critical")))
                         for p in task.get("required_points", []))
    return Plan(topic=topic, audience=audience or task.get("audience", ""), goal=task.get("goal", ""),
                language=task.get("language", "English"), axes=axes, requirements=requirements)


def _units(version: dict, source_of: dict[str, str], type_of: dict[str, str]) -> tuple[Unit, ...]:
    """Verified displayed units in display order, numbered U1.. exactly as the result page numbers them."""
    from matn_research.preview import unit_index
    ids = unit_index(version)
    requirement_of = {p.get("facet", p["id"]): p["id"] for p in version["task"].get("required_points", [])}
    units = []
    for slide in version["slides"]:
        if not slide["displayed"]:
            continue
        for check in slide["checks"]:
            if check.get("status") != "verified":
                continue
            display = check["display"]
            span = _span(display["support"])
            units.append(Unit(id=ids[check["binding"]], axis=slide["facet"], text=display["text"], span=span,
                              source=source_of[span.doc_id], source_type=type_of[span.doc_id], status="verified",
                              binding=check["binding"], requirement=requirement_of.get(slide["facet"]),
                              context=_contexts(display)))
    return tuple(units)


def _cited_order(version: dict) -> list[str]:
    order = []
    for slide in version["slides"]:
        if slide["displayed"]:
            for check in slide["checks"]:
                if check.get("status") == "verified":
                    doc = check["display"]["support"]["doc_id"]
                    if doc not in order:
                        order.append(doc)
    return order


def _numbers(units: Iterable[Unit]) -> tuple[NumericFact, ...]:
    return tuple(fact for unit in units for fact in facts_for_unit(unit))


def _pages(units: Iterable[Unit], doc_id: str, pdf: bool) -> tuple[int, ...]:
    if not pdf:
        return ()
    return tuple(sorted({u.span.page_index + 1 for u in units if u.span.doc_id == doc_id and u.span.page_index is not None}))


# ---- research results -------------------------------------------------------------------------------------------

def result_version_path(folder: Path) -> Path:
    """The displayed version of a result: the frozen display projection when present, else v1.json."""
    folder = Path(folder)
    for name in ("projection.json", "v1.json"):
        if (folder / name).is_file():
            return folder / name
    raise FileNotFoundError(f"RESULT_HAS_NO_VERSION:{folder}")


def from_research(folder: Path) -> EvidenceCatalog:
    from matn_research.source_type import classify, identities_for_records
    folder = Path(folder)
    files: dict[str, str] = {}
    version = _read(result_version_path(folder), files)
    state = _read(folder / "state.json", files) if (folder / "state.json").is_file() else {}
    brief = state.get("brief") or (_read(folder / "request.json", files) if (folder / "request.json").is_file() else {})
    reads = _read(folder / "reading-status.json", files) if (folder / "reading-status.json").is_file() else []
    features = state.get("features") or {}

    complete = {}
    for record in reads:
        if record.get("status") == "complete":
            complete.setdefault(record["doc_id"], record)
    notes = []
    try:
        identities = identities_for_records(list(complete.values()))
    except ValueError as exc:  # a saved snapshot without its hash: keep classification, leave the title absent
        notes.append(f"SOURCE_TITLES_UNAVAILABLE:{exc}")
        identities = {d: dict(classify(r.get("final_url") or r["url"]), source_title=None) for d, r in complete.items()}

    cited = _cited_order(version)
    order = cited + [d for d in complete if d not in cited]
    sources, source_of, type_of = [], {}, {}
    for n, doc_id in enumerate(order, start=1):
        record = complete.get(doc_id, {})
        info = identities.get(doc_id) or (classify(record.get("final_url") or record["url"]) if record else None)
        fetched = record.get("fetched_at")
        source_of[doc_id] = f"S{n}"
        type_of[doc_id] = info["label"] if info else "other"
        sources.append(Source(
            id=f"S{n}", doc_id=doc_id, type=type_of[doc_id], publisher=info["publisher"] if info else "unknown",
            title=info.get("source_title") if info else None,
            url=(record.get("final_url") or record.get("url")) if record else None,
            accessed=datetime.fromtimestamp(fetched, timezone.utc).date().isoformat() if fetched else None))
    units = _units(version, source_of, type_of)
    pdf_docs = {d for d, r in complete.items() if r.get("coverage", {}).get("kind") == "pdf"}
    sources = [replace(s, pages=_pages(units, s.doc_id, s.doc_id in pdf_docs)) for s in sources]

    synthesis = []
    if features.get("synthesis") and (folder / "synthesis.json").is_file():
        saved = _read(folder / "synthesis.json", files)
        for axis in version["task"]["facets"]:
            for sentence in saved.get("facets", {}).get(axis["id"], {}).get("sentences", []):
                if sentence.get("status") == "shown":
                    synthesis.append(SynthesisSentence(axis["id"], sentence["text"], tuple(sentence["units"])))

    task = version["task"]
    plan = _plan(task, brief.get("topic") or task.get("goal", ""), brief.get("audience", ""))
    gap_record=_read(folder/"gaps.json",files) if (folder/"gaps.json").is_file() else {}
    gaps = _gaps(gap_record, plan)
    searches_by_axis={}
    for name,job in state.get('jobs',{}).items():
        if name.startswith(('search-','gap-search-')) and job.get('status')=='complete' and job.get('path'):
            path=folder/job['path']
            if path.is_file():
                search=_read(path,files)
                if search.get('facet') and search.get('query'):
                    searches_by_axis.setdefault(search['facet'],[]).append(search['query'])
    return EvidenceCatalog(plan=plan, units=units, sources=tuple(sources), synthesis=tuple(synthesis),
                           numbers=_numbers(units), gaps=gaps,
                           origin={"adapter": "research", "folder": str(folder), "files": files,
                                   "features": features, "notes": notes,"axis_coverage":gap_record.get("model_fit",{}),"searches_by_axis":searches_by_axis}).validate()


def _gaps(saved: dict, plan: Plan) -> tuple[Gap, ...]:
    descriptions = {r.id: r.description for r in plan.requirements}
    axis_of = {r.id: r.axis for r in plan.requirements}
    axes = {a.id for a in plan.axes}
    gaps = []
    for gap in saved.get("open", []):
        missing = tuple(descriptions.get(k, k) for k in gap.get("missing_points", []))
        axis = axis_of.get(gap["id"], gap["id"])
        gaps.append(Gap(requirement=gap["id"], axis=axis if axis in axes else plan.axes[0].id,
                        label=gap.get("label", gap["id"]), missing=missing, reason=gap.get("reason", "")))
    return tuple(gaps)


# ---- document path ----------------------------------------------------------------------------------------------

def storyboard_version_path(folder: Path) -> Path:
    """The newest saved version v<N>.json of a storyboard folder."""
    versions = sorted(Path(folder).glob("v*.json"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    if not versions:
        raise FileNotFoundError(f"STORYBOARD_HAS_NO_VERSION:{folder}")
    return versions[-1]


def _documents(notebook: Path, files: dict[str, str]) -> dict[str, dict]:
    manifest_path = Path(str(notebook) + ".structures.json")
    manifest = _read(manifest_path, files)
    documents = {}
    for doc_id, path in manifest["documents"].items():
        path = Path(path) if Path(path).is_absolute() else manifest_path.parent / path
        structure = _read(path, files)
        if structure["doc_id"] != doc_id:
            raise ValueError(f"STRUCTURE_DOC_ID:{doc_id}")
        documents[doc_id] = structure
    return documents


def from_storyboard(folder: Path, *, version: Path | None = None, readings: Iterable[Path] = (),
                    pdfs: Iterable[Path] = (), notebook: Path | None = None) -> EvidenceCatalog:
    folder = Path(folder)
    files: dict[str, str] = {}
    inputs = _read(folder / "input.json", files)
    notebook = Path(notebook or inputs["notebook"])
    if Path(inputs["notebook"]).resolve() != notebook.resolve():
        raise ValueError("NOTEBOOK_MISMATCH")
    saved = _read(Path(version) if version else storyboard_version_path(folder), files)
    documents = _documents(notebook, files)
    pdf_of = {}
    for pdf in pdfs:
        pdf_of["sha256-" + _sha(pdf)] = Path(pdf)
        files[str(pdf)] = _sha(pdf)
    cited = _cited_order(saved)
    order = cited + [d for d in documents if d not in cited]
    source_of = {d: f"S{n}" for n, d in enumerate(order, start=1)}
    type_of = {d: UPLOADED for d in order}
    units = _units(saved, source_of, type_of)
    sources = tuple(Source(id=source_of[d], doc_id=d, type=UPLOADED, publisher=documents[d]["title"] if d in documents
                           else "unknown", title=documents.get(d, {}).get("title"),
                           file=pdf_of[d].name if d in pdf_of else None, pages=_pages(units, d, True))
                    for d in order)
    task = saved["task"]
    plan = _plan(task, task.get("topic") or task.get("goal", ""), task.get("audience", ""))
    figures = _figures(units, documents, readings, pdf_of, source_of, files)
    tables = tuple(ReaderTable(t["table_id"], d, t["pdf_page_index"], tuple(t["bbox"]["coordinates"]))
                   for d, s in documents.items() for t in s.get("tables", []) if d in cited)
    return EvidenceCatalog(plan=plan, units=units, sources=sources, numbers=_numbers(units), gaps=(),
                           figures=figures, tables=tables,
                           origin={"adapter": "storyboard", "folder": str(folder), "notebook": str(notebook),
                                   "files": files}).validate()


def _area(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _figures(units: tuple[Unit, ...], documents: dict[str, dict], readings: Iterable[Path], pdf_of: dict[str, Path],
             source_of: dict[str, str], files: dict[str, str]) -> tuple[Figure, ...]:
    """Reader figure regions paired with a reader caption on the same page, linked to an axis when the caption sits
    on a page cited by a displayed unit of that axis or under the same parent section as that unit (the figure
    accompanies the cited text). Only documents whose original PDF is given (hash = doc_id) can be cropped."""
    path_of = {}
    for doc_id, structure in documents.items():
        for section in structure.get("sections", []):
            for block_id in section["block_ids"]:
                path_of[(doc_id, block_id)] = tuple(section.get("path") or ())

    def related(unit: Unit, doc_id: str, page_index: int, caption_id: str) -> bool:
        if unit.span.page_index == page_index:
            return True
        mine, theirs = path_of.get((doc_id, unit.span.block_id)), path_of.get((doc_id, caption_id))
        if not mine or not theirs:
            return False
        k = max(len(mine) - 1, min(len(mine), 2))  # the parent section, never just the chapter
        return len(theirs) >= k and theirs[:k] == mine[:k]

    figures = []
    for path in readings:
        cache = _read(Path(path), files)
        doc_id = cache["doc_id"]
        if doc_id not in pdf_of:
            continue
        cited = [u for u in units if u.span.doc_id == doc_id]
        for page in cache["pages"]:
            page_area = page["width"] * page["height"]
            regions = [r for r in page["figure_regions"]
                       if FIGURE_SHARE[0] <= _area(r) / page_area <= FIGURE_SHARE[1]]
            captions = [b["block"] for b in page["blocks"]
                        if b["block"]["block_type"] == "caption" and CAPTION_START.match(b["block"]["text"].strip())]
            used = set()
            for caption in captions:
                cb = caption["bbox"]
                cb = (cb["x0"], cb["top"], cb["x1"], cb["bottom"]) if isinstance(cb, dict) else tuple(cb)
                best = None
                for index, region in enumerate(regions):
                    if index in used or min(cb[2], region[2]) <= max(cb[0], region[0]):
                        continue
                    gap = min(abs(region[1] - cb[3]), abs(cb[1] - region[3]))
                    if gap <= CAPTION_GAP_PT and (best is None or gap < best[0]):
                        best = (gap, index)
                if best is None:
                    continue
                used.add(best[1])
                linked = [u for u in cited if related(u, doc_id, page["page_index"], caption["block_id"])]
                if not linked:
                    continue
                figures.append(Figure(
                    id=f"F{len(figures) + 1}", doc_id=doc_id, source=source_of[doc_id], page_index=page["page_index"],
                    bbox=tuple(float(x) for x in regions[best[1]]), caption=caption["text"].strip(),
                    caption_block_id=caption["block_id"], axis=linked[0].axis,
                    unit_ids=tuple(u.id for u in linked if u.axis == linked[0].axis), pdf=str(pdf_of[doc_id])))
    return tuple(figures)


# ---- JSON -------------------------------------------------------------------------------------------------------

def resolve_pointer(document: Any, pointer: str) -> Any:
    """RFC 6901 JSON Pointer lookup; KeyError/IndexError when the path does not exist."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"JSON_POINTER_INVALID:{pointer}")
    value = document
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def from_json(path: Path) -> EvidenceCatalog:
    """A saved catalog (`"version"` + `"plan"` + `"units"`) or a JSON source bundle (`"matn_json_sources": 1`).

    Bundle: {"matn_json_sources": 1, "plan": {topic, audience, goal, axes:[{id,title}], requirements:[...]},
    "sources": [{"file", "title", "publisher"}], "statements": [{"axis", "file", "pointer"}],
    "numbers": [{"file", "pointer", "unit_pointer"?, "period_pointer"?, "population_pointer"?,
    "geography_pointer"?}]}. Every displayed string or number is copied from its source file by JSON Pointer
    (provenance = file + JSON path); the bundle itself never carries slide text or values.
    """
    path = Path(path)
    data = json.loads(path.read_bytes())
    if "matn_json_sources" not in data:
        return EvidenceCatalog.from_json(path.read_bytes()).validate()
    files = {str(path): _sha(path)}
    base = path.parent
    loaded, sources, source_of = {}, [], {}
    for n, spec in enumerate(data["sources"], start=1):
        file = base / spec["file"]
        raw = file.read_bytes()
        files[str(file)] = hashlib.sha256(raw).hexdigest()
        doc_id = "sha256-" + files[str(file)]
        loaded[spec["file"]] = (json.loads(raw), doc_id)
        source_of[spec["file"]] = f"S{n}"
        sources.append(Source(id=f"S{n}", doc_id=doc_id, type="uploaded JSON", publisher=spec.get("publisher") or
                              "unknown", title=spec.get("title"), file=spec["file"]))
    p = data["plan"]
    plan = Plan(topic=p["topic"], audience=p.get("audience", ""), goal=p.get("goal", ""),
                language=p.get("language", "English"),
                axes=tuple(Axis(a["id"], a["title"], a.get("query", "")) for a in p["axes"]),
                requirements=tuple(Requirement(r["id"], r["axis"], r["description"], bool(r.get("critical")))
                                   for r in p.get("requirements", [])))

    def span(file: str, pointer: str, value: Any) -> Span:
        quote = value if isinstance(value, str) else json.dumps(value)
        return Span(doc_id=loaded[file][1], block_id=f"json:{file}#{pointer}", start=0, end=len(quote), quote=quote)

    units = []
    for spec in data.get("statements", []):
        value = resolve_pointer(loaded[spec["file"]][0], spec["pointer"])
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"JSON_STATEMENT_NOT_TEXT:{spec['file']}#{spec['pointer']}")
        units.append(Unit(id=f"U{len(units) + 1}", axis=spec["axis"], text=value,
                          span=span(spec["file"], spec["pointer"], value), source=source_of[spec["file"]],
                          source_type="uploaded JSON", status="verified",
                          binding="json-copy:" + hashlib.sha256(f"{spec['file']}#{spec['pointer']}".encode()).hexdigest()))
    numbers = list(_numbers(units))
    for spec in data.get("numbers", []):
        document = loaded[spec["file"]][0]
        value = resolve_pointer(document, spec["pointer"])
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"JSON_NUMBER_NOT_NUMERIC:{spec['file']}#{spec['pointer']}")
        written = json.dumps(value)

        def text(key: str) -> str:
            return str(resolve_pointer(document, spec[key])) if spec.get(key) else ""
        period = text("period_pointer")
        numbers.append(NumericFact(
            id=f"J{len(numbers) + 1}", unit_id="", value_as_written=written, start=0, end=len(written),
            value=str(value), unit=text("unit_pointer"), span=span(spec["file"], spec["pointer"], value),
            period=(period,) if period else (), population=text("population_pointer"),
            geography=text("geography_pointer") or None, origin="json", source=source_of[spec["file"]]))
    return EvidenceCatalog(plan=plan, units=tuple(units), sources=tuple(sources), numbers=tuple(numbers),
                           origin={"adapter": "json-sources", "file": str(path), "files": files}).validate()
