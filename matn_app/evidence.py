"""Local app adapters for source ingestion and grounded, source-scoped answers.

This module never searches the web. PDFs retain the reader/index/verifier contracts;
JSON uses the existing deck adapter's exact JSON Pointer copy contract. Run it in
``evidence_worker`` rather than an HTTP thread: reader egress guards are process-wide.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any


def _write(path: Path, value: Any) -> None:
    from matn_chat.readiness import write
    write(path, value)


def _event(folder: Path, stage: str, **fields: Any) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    value = dict(stage=stage, at=time.time(), **fields)
    _write(folder / "progress.json", value)
    with (folder / "events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + "\n")


def _leaves(value: Any, pointer: str = ""):
    """Original scalar values and RFC 6901 addresses, including escaped keys."""
    if isinstance(value, dict):
        for key, child in value.items():
            token = str(key).replace("~", "~0").replace("/", "~1")
            yield from _leaves(child, pointer + "/" + token)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaves(child, pointer + "/" + str(index))
    else:
        yield pointer, value


def _load_catalog(path: str | Path):
    from matn_deck.catalog import EvidenceCatalog
    catalog = EvidenceCatalog.from_json(Path(path).read_bytes()).validate()
    for filename, digest in catalog.origin.get("files", {}).items():
        file = Path(filename)
        if file.exists() and hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError("SOURCE_OR_RECEIPT_CHANGED:" + file.name)
    return catalog


def merge_catalogs(catalogs, output: str | Path | None = None, *, topic: str = "Source briefing", audience: str = "General audience"):
    """Merge catalog objects or paths; return EvidenceCatalog, or Path when output is supplied.

    ``merge_catalogs(paths, output_path, topic=..., audience=...)`` is the public
    app deck-build adapter. Source text, spans and numeric provenance are retained.
    """
    from matn_deck.catalog import EvidenceCatalog, Plan
    axes, requirements, sources, units, numbers, gaps, figures, tables, synthesis = [], [], [], [], [], [], [], [], []
    by_document = {}
    by_axis = {}
    files = {}
    fake = False
    region_labels,source_metadata,region_summaries={},{},{}
    axis_coverage,searches_by_axis={},{}
    seen_catalogs = set()
    for serial, catalog in enumerate(catalogs, 1):
        if isinstance(catalog, (str, Path)):
            catalog = _load_catalog(catalog)
        identity = catalog.sha256()
        if identity in seen_catalogs:
            continue
        seen_catalogs.add(identity)
        axis_ids = {}
        for axis in catalog.plan.axes:
            key = (axis.title, axis.query)
            if key not in by_axis:
                by_axis[key] = f"a{serial}_{axis.id}"
                axes.append(replace(axis, id=by_axis[key]))
            axis_ids[axis.id] = by_axis[key]
        unit_ids, number_ids, source_ids = {}, {}, {}
        requirements.extend(replace(r, id=f"r{serial}_{r.id}", axis=axis_ids[r.axis])
                            for r in catalog.plan.requirements)
        for source in catalog.sources:
            if source.doc_id not in by_document:
                sid = f"S{len(sources) + 1}"
                by_document[source.doc_id] = sid
                sources.append(replace(source, id=sid))
            source_ids[source.id] = by_document[source.doc_id]
        for unit in catalog.units:
            duplicate = next((u for u in units if u.span == unit.span and u.text == unit.text
                              and u.context == unit.context and u.axis == axis_ids[unit.axis]), None)
            if duplicate:
                unit_ids[unit.id] = duplicate.id
                continue
            uid = f"U{len(units) + 1}"
            unit_ids[unit.id] = uid
            units.append(replace(unit, id=uid, axis=axis_ids[unit.axis], source=source_ids[unit.source],
                                 requirement=f"r{serial}_{unit.requirement}" if unit.requirement else None))
        for number in catalog.numbers:
            normalized=replace(number,id='',unit_id=unit_ids.get(number.unit_id,''),
                               source=source_ids.get(number.source,number.source))
            duplicate=next((n for n in numbers if replace(n,id='')==normalized),None)
            if duplicate:
                number_ids[number.id]=duplicate.id
                continue
            nid = f"N{len(numbers) + 1}"
            number_ids[number.id] = nid
            numbers.append(replace(number, id=nid, unit_id=unit_ids.get(number.unit_id, ""),
                                   source=source_ids.get(number.source, number.source)))
        gaps.extend(replace(g, requirement=f"r{serial}_{g.requirement}", axis=axis_ids[g.axis]) for g in catalog.gaps)
        figure_base = len(figures)
        figures.extend(replace(f, id=f"F{figure_base + index}", source=source_ids[f.source],
                               axis=axis_ids[f.axis], unit_ids=tuple(unit_ids[u] for u in f.unit_ids))
                       for index, f in enumerate(catalog.figures, 1))
        synthesis.extend(replace(s, axis=axis_ids[s.axis], unit_ids=tuple(unit_ids[u] for u in s.unit_ids))
                         for s in catalog.synthesis)
        tables.extend(replace(t, id=f"T{serial}_{t.id}") for t in catalog.tables)
        files.update(catalog.origin.get("files", {}))
        region_labels.update(catalog.origin.get('regions',{}))
        source_metadata.update(catalog.origin.get('source_metadata',{}))
        region_summaries.update(catalog.origin.get('region_summaries',{}))
        for old,status in catalog.origin.get('axis_coverage',{}).items():
            if old in axis_ids:axis_coverage[axis_ids[old]]=status
        for old,queries in catalog.origin.get('searches_by_axis',{}).items():
            if old in axis_ids:searches_by_axis[axis_ids[old]]=list(queries)
        fake = fake or bool(catalog.origin.get("fake"))
    # Empty sources may still have a useful, explicit missing-evidence axis.
    if not axes:
        from matn_deck.catalog import Axis
        axes.append(Axis("sources", "Source evidence", ""))
    plan = Plan(topic=topic, audience=audience, goal="Prepare a source-grounded presentation", language="English",
                axes=tuple(axes), requirements=tuple(requirements))
    merged = EvidenceCatalog(plan=plan, units=tuple(units), sources=tuple(sources), numbers=tuple(numbers),
                           gaps=tuple(gaps), figures=tuple(figures), tables=tuple(tables),
                           synthesis=tuple(synthesis),
                           origin=dict(adapter="app-merged", files=files, fake=fake,regions=region_labels,
                                       source_metadata=source_metadata,region_summaries=region_summaries,axis_coverage=axis_coverage,searches_by_axis=searches_by_axis)).validate()
    if output is not None:
        _write(Path(output), json.loads(merged.to_json()))
        return Path(output)
    return merged


def catalog_citations(catalog) -> list[dict]:
    def pointer(span):
        if not span.block_id.startswith("json:"):
            return None
        # '#' is legal in filenames and JSON keys. The source hash inventory
        # gives an unambiguous filename boundary before the RFC6901 pointer.
        for filename in sorted(catalog.origin.get("files", {}), key=len, reverse=True):
            prefix = "json:" + filename + "#"
            if span.block_id.startswith(prefix):
                return span.block_id[len(prefix):]
        return span.block_id.partition("#")[2]
    rows = []
    for unit in catalog.units:
        source = catalog.source(unit.source)
        path = pointer(unit.span)
        rows.append(dict(id=unit.id, unit_id=unit.id, axis=unit.axis, text=unit.text, quote=unit.span.quote,
                         source=unit.source, source_id=unit.source, doc_id=unit.span.doc_id,
                         title=source.title or source.publisher, file=source.file, url=source.url,
                         source_type=source.type, fetched=source.accessed, status=unit.status,
                         region=catalog.origin.get('regions',{}).get(unit.span.block_id,'body'),
                         page=unit.span.page_index + 1 if unit.span.page_index is not None else None,
                         page_label=unit.span.page_label, path=path,
                         span=dict(block_id=unit.span.block_id, start=unit.span.start, end=unit.span.end,
                                   quote=unit.span.quote, bbox=unit.span.bbox),
                         spans=[dict(block_id=s.block_id, start=s.start, end=s.end, quote=s.quote,
                                     page=s.page_index + 1 if s.page_index is not None else None,
                                     bbox=s.bbox) for s in (unit.span, *(c.span for c in unit.context if c.span))],
                         binding=unit.binding))
    for number in catalog.numbers:
        if number.origin != "json":
            continue
        source = catalog.source(number.source)
        rows.append(dict(id=number.id, unit_id=None, axis=None, text=number.value_as_written,
                         quote=number.span.quote, source=source.id, source_id=source.id, doc_id=source.doc_id,
                         title=source.title or source.publisher, file=source.file, url=source.url,
                         source_type=source.type, fetched=source.accessed, status="exact_json_copy",
                         page=None, page_label=None, path=pointer(number.span),
                         span=dict(block_id=number.span.block_id, start=number.span.start, end=number.span.end,
                                   quote=number.span.quote, bbox=None), binding="exact-json-pointer"))
    return rows


def _json_catalog(path: Path, folder: Path):
    """Delegate string/number provenance to deck-v2's established JSON adapter."""
    from matn_deck.catalog_adapters import from_json
    def nonfinite(value):
        raise ValueError("NONFINITE_JSON_NUMBER:" + value)
    data = json.loads(path.read_bytes(), parse_constant=nonfinite)
    # Uploaded JSON is data, even if it resembles a saved catalog. Never accept
    # an uploaded "verified" status or a local file reference supplied by it.
    leaves = list(_leaves(data))
    spec = dict(matn_json_sources=1,
                plan=dict(topic=path.stem, audience="General audience", goal="Review uploaded source evidence",
                          axes=[dict(id="source", title=path.stem)]),
                sources=[dict(file=str(path.resolve()), title=path.name, publisher=path.name)],
                statements=[dict(axis="source", file=str(path.resolve()), pointer=pointer)
                            for pointer, value in leaves if isinstance(value, str) and value.strip()],
                numbers=[dict(file=str(path.resolve()), pointer=pointer)
                         for pointer, value in leaves if type(value) in (int, float)])
    manifest = folder / "json-source-bundle.json"
    _write(manifest, spec)
    catalog = from_json(manifest)
    catalog = replace(catalog, sources=tuple(replace(s, file=path.name) for s in catalog.sources))
    # Scalar-only JSON remains inspectable; bare numbers are never rewritten as
    # a factual sentence or assigned an invented unit, year or population.
    coverage = dict(file=path.name, doc_id=catalog.sources[0].doc_id, kind="json", complete=True, scalar_values=len(leaves),
                    text_values=len(catalog.units), numeric_values=len(catalog.numbers),
                    index_mode="exact-json-pointer", status="complete",
                    scalar_citations=[dict(path=p, value=v, quote=v if isinstance(v, str) else json.dumps(v),
                                           file=path.name, status="exact_json_copy") for p, v in leaves])
    return catalog, coverage


class _FakeEntailment:
    """Test-only exact-source native stand-in; its use stays visible in receipts."""
    def check(self, text, evidence, target):
        from matn_verification.contracts import Check
        from matn_verification.prose import surface
        source = " ".join(e.quote for e in evidence)
        ok = surface(text) in surface(source)
        return Check(target=target, layer="L4", verdict="pass" if ok else "reject",
                     reasons=() if ok else ("entailment_failed",))

    def close(self):
        pass


def _fake_pdf(path: Path, folder: Path):
    """Read real digital pages with existing reader; no model/OCR stand-in bytes."""
    from matn_reading.read import read_document
    from matn_reading.structure.cache import OCR_ROUTES
    from matn_reading.structure.document import from_reading
    from matn_reading.cli import test_split_hashes
    if hashlib.sha256(path.read_bytes()).hexdigest() in test_split_hashes():
        raise ValueError("SEALED_TEST_SPLIT_REFUSED")
    reading = read_document(path)
    pages = [p for p in reading.pages if p.route.value not in OCR_ROUTES]
    if not pages:
        raise ValueError("NO_DIGITAL_PAGES_FAKE_MODE_DOES_NOT_RUN_OCR")
    document = from_reading(path, folder, reading, pages)
    docpath = folder / "runs" / document.doc_id / "document.json"
    coverage = dict(file=path.name, doc_id=document.doc_id, kind="pdf", total_pages=len(reading.pages),
                    ready_pages=[p.page_index + 1 for p in pages],
                    pending_pages=[p.page_index + 1 for p in reading.pages if p.route.value in OCR_ROUTES],
                    complete=len(pages) == len(reading.pages), index_mode="bm25", fake=True)
    return document, docpath, coverage, []


def _read_pdf(path: Path, folder: Path, *, fake: bool):
    from matn_contracts.structure import DocumentStructure
    if fake:
        return _fake_pdf(path, folder)
    from matn_chat.readiness import prepare_pdf, load_ready
    failures = []
    try:
        prepare_pdf(path, folder, publish_every=32, lexical_only=True)
    except Exception as exc:
        failures.append(dict(file=path.name, stage="reading_or_indexing", error=type(exc).__name__, detail=str(exc)[:300]))
    ready = folder / "ready.json"
    if not ready.exists():
        raise ValueError("NO_READABLE_PAGES:" + path.name)
    receipt = load_ready(ready)
    docpath = Path(receipt["notebook"]).parent / "document.json"
    document = DocumentStructure.model_validate_json(docpath.read_bytes())
    coverage = dict(receipt["coverage"], file=path.name, doc_id=document.doc_id, kind="pdf", revision=receipt["revision"])
    return document, docpath, coverage, failures


def _source_cache(path, root):
    """Content and implementation bound: never reuse an older verifier's receipts."""
    from matn_chat.readiness import binding
    code = Path(__file__).resolve().parents[1]
    packages = tuple(p.name for p in sorted(code.glob('matn_*')) if p.is_dir())+('checks',)
    implementation = {str(p.relative_to(code)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for name in packages for p in sorted((code / name).rglob('*.py'))}
    key = hashlib.sha256(json.dumps(dict(reader=binding(path), code=implementation,
                                        mode='app-bm25-v1'), sort_keys=True).encode()).hexdigest()
    folder = Path(root) / key
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _bundle_sources(documents, coverage, target, cache_root=None):
    from matn_chat.notebooks import bundle
    inputs={str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in documents}
    key=hashlib.sha256(json.dumps(dict(inputs=inputs,coverage=coverage),sort_keys=True).encode()).hexdigest()
    pointer=None
    if cache_root:
        pointer=Path(cache_root)/'notebooks'/(key+'.json')
        if pointer.exists():
            saved=json.loads(pointer.read_bytes())
            for raw,digest in saved['files'].items():
                if hashlib.sha256(Path(raw).read_bytes()).hexdigest()!=digest:
                    raise ValueError('CACHED_NOTEBOOK_HASH')
            return saved['notebook']
        target=pointer.parent/key
    # Keep any crashed unpublished attempt for diagnosis, then rebuild cleanly.
    if target.exists():
        target=target.with_name(target.name+'-retry-'+str(time.time_ns()))
    notebook=str(bundle(documents,target))
    manifest_path=Path(notebook+'.structures.json')
    manifest=json.loads(manifest_path.read_bytes())
    manifest['source_coverage']=coverage
    manifest['source_revisions']={d:c.get('revision') for d,c in coverage.items()}
    _write(manifest_path,manifest)
    if pointer:
        _write(pointer,dict(notebook=notebook,files={str(p):hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in target.iterdir() if p.is_file()}))
    return notebook


def _pdf_catalog(document, file: Path, folder: Path, *, fake: bool, max_units: int = 8, reading_folder=None):
    from contextlib import nullcontext
    from .model_gate import lease
    with nullcontext() if fake else lease():
        folder.mkdir(parents=True,exist_ok=True)
        return _pdf_catalog_owned(document, file, folder, fake=fake, max_units=max_units,reading_folder=reading_folder)


def _pdf_catalog_owned(document, file: Path, folder: Path, *, fake: bool, max_units: int = 8, reading_folder=None):
    from matn_chat.engine import MiniCheck
    from matn_chat.reliable import build_reliable_handles
    from matn_deck.catalog import Axis, Context, EvidenceCatalog, Plan, Source, Span, Unit
    from matn_deck.numeric import facts_for_unit
    from matn_rag.ingest import prepare
    from matn_verification.rules import fingerprint
    from matn_verification.scope import verify_scope
    handles = build_reliable_handles((document,), prepare(document)[1])
    from .reading_hygiene import regions,summary,eligible_handles
    labels=regions(document)
    handles=eligible_handles(handles,document)
    # A source always receives its own candidate budget. Choose across the
    # document rather than taking the first source's first retrieval results.
    candidates = [h for h in handles.values() if all(labels.get(c['block_id'])=='body' for c in h['citations'])]
    metadata=dict(publisher=None,date=None,type=None)
    ranking=dict(generation_calls=0,error=None)
    if not fake and len(candidates)>5:
        from .overview import rank
        candidates,metadata,ranking=rank(document,handles,folder)
        max_units=5
    if len(candidates) > max_units * 3:
        count = max_units * 3
        indices = sorted({round(i * (len(candidates) - 1) / (count - 1)) for i in range(count)})
        candidates = [candidates[i] for i in indices]
    native_calls = 0
    class CountedNative(MiniCheck):
        def check(self, text, evidence, target):
            nonlocal native_calls
            native_calls += 1
            return super().check(text, evidence, target)
    native = _FakeEntailment() if fake else CountedNative()
    receipts, units, blocked = [], [], []
    native_error = None
    by_block = {e.block.block_id: e for e in document.elements}
    try:
        for candidate in candidates:
            if len(units) >= max_units:
                break
            text = candidate["text"].strip()
            if not text or len(text) > 1200 or not text.rstrip().rstrip(')\"”').endswith((".", "!", "?")):
                continue
            refs = [{k: c[k] for k in ("block_id", "start", "end", "quote")} for c in candidate["citations"]]
            request = dict(sentence=text, claims=[dict(text=text, citations=refs)], selected_doc_ids=[document.doc_id],
                           fingerprints={document.doc_id: fingerprint(document)}, retrieved_spans=refs)
            try:
                from .verification import deterministic_first
                receipt = deterministic_first((document,), request, native).model_dump(mode="json")
            except Exception as exc:
                native_error = dict(error=type(exc).__name__, detail=str(exc)[:200])
                blocked.append(dict(text=text, status="abstained", reasons=["model_unavailable"]))
                break
            receipt["app_backend"] = "fake_native" if fake else "native_L0_L4_preserved_scope"
            receipts.append(receipt)
            _write(folder / "verification-partial.json", dict(fake=fake, receipts=receipts, blocked=blocked))
            if receipt["status"] != "verified":
                reasons = sorted({r for c in receipt["checks"] for r in c["reasons"]})
                blocked.append(dict(text=text, status=receipt["status"], reasons=reasons))
                if {"model_unavailable", "model_output_invalid"} & set(reasons):
                    native_error = dict(error="NativeVerificationUnavailable", detail="Local native verification is unavailable; completed units were retained.")
                    break
                continue
            ref = candidate["citations"][0]
            element = by_block[ref["block_id"]]
            span = Span(doc_id=document.doc_id, block_id=ref["block_id"], start=ref["start"], end=ref["end"],
                        quote=ref["quote"], page_index=element.block.page_index, page_label=element.block.page_label,
                        bbox=tuple(element.bbox.coordinates))
            binding = "app-source-copy:" + hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
            context = []
            for extra in candidate["citations"][1:]:
                other = by_block[extra["block_id"]]
                extra_span = Span(doc_id=document.doc_id, block_id=extra["block_id"], start=extra["start"],
                                  end=extra["end"], quote=extra["quote"], page_index=other.block.page_index,
                                  page_label=other.block.page_label, bbox=tuple(other.bbox.coordinates))
                context.append(Context(quote=extra["quote"], kind="required", origin="source continuation", span=extra_span))
            units.append(Unit(id=f"U{len(units) + 1}", axis="source", text=text, span=span, source="S1",
                              source_type="uploaded document", status="verified", binding=binding, context=tuple(context)))
    finally:
        native.close()
    _write(folder / "verification.json", dict(fake=fake, receipts=receipts, blocked=blocked, native_error=native_error))
    plan = Plan(topic=document.title or file.stem, audience="General audience", goal="Review uploaded source evidence",
                language="English", axes=(Axis("source", document.title or file.stem, ""),))
    files = {str(file.resolve()): hashlib.sha256(file.read_bytes()).hexdigest(),
             str(folder / "verification.json"): hashlib.sha256((folder / "verification.json").read_bytes()).hexdigest()}
    if (folder/'overview-ranking.json').exists():
        files[str(folder/'overview-ranking.json')]=hashlib.sha256((folder/'overview-ranking.json').read_bytes()).hexdigest()
    figures, figure_failures = (), []
    reading_folder=Path(reading_folder or folder)
    try:
        # Reuse deck-v2's reader-caption/page/region checks. It crops the source
        # image later; it never interprets numbers from a figure.
        from matn_deck.catalog_adapters import _figures
        from matn_chat.readiness import load_page
        reading = folder / "figure-reading.json"
        if (reading_folder / "digital.json.gz").exists():
            pages = {p["page_index"]: p for p in load_page(reading_folder / "digital.json.gz")["pages"]}
            for checkpoint in (reading_folder / "ocr").glob("*.json.gz"):
                page = load_page(checkpoint)
                pages[page["page_index"]] = page
            _write(reading, dict(doc_id=document.doc_id, pages=list(pages.values())))
        else:
            existing = reading_folder / "runs" / document.doc_id / "00_structure_input.json"
            if existing.exists():
                reading = existing
        if reading.exists():
            figures = _figures(tuple(units), {document.doc_id: document.model_dump(mode="json")}, (reading,),
                               {document.doc_id: file}, {document.doc_id: "S1"}, files)
    except Exception as exc:
        figure_failures.append(dict(stage="figure_adapter", error=type(exc).__name__, detail=str(exc)[:200]))
    catalog = EvidenceCatalog(plan=plan, sources=(Source(id="S1", doc_id=document.doc_id, type="uploaded document",
                              publisher=metadata.get('publisher') or document.title or file.name, title=document.title, file=file.name,
                              pages=tuple(sorted({u.span.page_index + 1 for u in units}))),), units=tuple(units),
                              numbers=tuple(n for u in units for n in facts_for_unit(u)),
                              figures=tuple(figures),
                              origin=dict(adapter="app-pdf-source-copy", fake=fake,
                                          files=files, figure_failures=figure_failures,
                                          regions=labels,source_metadata={document.doc_id:metadata},
                                          region_summaries={document.doc_id:summary(document,labels)},
                                          overview_ranking=ranking,
                                          verification=str(folder / "verification.json"))).validate()
    return catalog, dict(candidates=len(candidates), attempted=len(receipts), verified=len(units),
                         blocked=len(blocked), native_calls=native_calls, native_error=native_error,
                         generation_calls=ranking['generation_calls'],ranking_error=ranking.get('error'))


def _overview(catalog):
    citations = catalog_citations(catalog)
    sources = []
    for source in catalog.sources:
        excerpts = [c for c in citations if c["source"] == source.id and c.get('region','body')=='body']
        sources.append(dict(id=source.id, title=source.title or source.publisher or source.file,
                            file=source.file, excerpts=excerpts[:5],metadata=catalog.origin.get('source_metadata',{}).get(source.doc_id,{}),
                            verified_units=sum(c["unit_id"] is not None for c in excerpts)))
    exact = {}
    for citation in citations:
        if citation["unit_id"] is not None:
            exact.setdefault(citation["text"].strip(), []).append(citation)
    agreements = [dict(label="The same exact passage appears in these sources.", citations=values)
                  for values in exact.values() if len({v["doc_id"] for v in values}) > 1]
    paths = {}
    for citation in citations:
        if citation["path"] is not None:
            paths.setdefault(citation["path"], []).append(citation)
    differences = [dict(label="Different text at the same JSON path; comparability is not established.", path=path,
                        citations=values) for path, values in paths.items()
                   if len({v["doc_id"] for v in values}) > 1 and len({v["text"] for v in values}) > 1]
    def identity(source):
        meta=source.get('metadata',{})
        return ' · '.join((meta.get('publisher') or 'Publisher not stated',meta.get('date') or 'Date not stated',meta.get('type') or 'Uploaded document'))
    text = "\n\n".join((str(s["title"]) + "\n"+identity(s)+'\n' + ("\n".join(c["text"] + " [" + c["id"] + "]" for c in s["excerpts"])
                        or "No verified presentation units are available from this source.")) for s in sources)
    return dict(text=text or "No readable source evidence is available yet.", sources=sources,
                citations=citations, agreements=agreements, disagreements=differences,
                comparison_status="Only exact matches and explicit JSON-path differences are shown. Semantic agreement or disagreement has not been established." if citations else None,
                proposal=dict(angle="A source-grounded briefing", audience=catalog.plan.audience or "General audience",
                              outline=["Purpose and sources", *[str(s["title"]) for s in sources],
                                       "Evidence gaps", "Sources and methods"]) if citations else None)


def ingest(request: dict) -> dict:
    started = time.monotonic()
    folder = Path(request["workdir"]).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    fake = bool(request.get("fake", False))
    catalogs = [_load_catalog(p) for p in request.get("catalogs", [])]
    coverage, failures, documents, readies, metrics = [], [], list(request.get("documents", [])), [], []
    inputs = request.get("inputs") or request.get("paths") or []
    if request.get("input"):
        inputs = [*inputs, request["input"]]
    profile_sources=[]
    for raw in inputs:
        path = Path(raw).resolve()
        source_folder = folder / "sources" / hashlib.sha256(str(path).encode()).hexdigest()[:16]
        if path.suffix.lower() == '.pdf' and request.get('source_cache') and not fake:
            source_folder = _source_cache(path, request['source_cache'])
        source_folder.mkdir(parents=True, exist_ok=True)
        profile_sources.append(str(source_folder))
        _write(folder/'profile-sources.json',profile_sources)
        _event(folder, "reading_source", file=path.name, source=str(source_folder),kind=path.suffix.lower().lstrip("."))
        try:
            if path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError("UPLOAD_EXCEEDS_64_MIB")
            if path.suffix.lower() == ".json":
                catalog, item_coverage = _json_catalog(path, source_folder)
            elif path.suffix.lower() == ".pdf":
                if not path.read_bytes().startswith(b"%PDF-"):
                    raise ValueError("INVALID_PDF_HEADER")
                document, docpath, item_coverage, item_failures = _read_pdf(path, source_folder, fake=fake)
                documents.append(str(docpath))
                failures.extend(item_failures)
                if (source_folder / "ready.json").exists():
                    readies.append(str(source_folder / "ready.json"))
                _event(folder, "verifying_source_units", file=path.name,source=str(source_folder))
                catalog_folder=source_folder/'catalogs'/hashlib.sha256(Path(docpath).read_bytes()).hexdigest()
                cached = catalog_folder / 'catalog.json'
                # load_ready above validates immutable document/index bytes;
                # _load_catalog validates all saved source and receipt hashes.
                reusable=None
                if item_coverage.get('complete') and cached.exists() and not item_failures:
                    reusable = _load_catalog(cached)
                    saved_verification=json.loads(Path(reusable.origin['verification']).read_bytes())
                    if saved_verification.get('native_error'):
                        reusable=None
                    if reusable and reusable.origin.get('overview_ranking',{}).get('error'):
                        reusable=None
                if reusable is not None:
                    catalog = reusable
                    counts = dict(native_calls=0, cache_hit=True, verified=len(catalog.units))
                else:
                    attempt=catalog_folder
                    if (attempt/'verification.json').exists():
                        attempt=attempt.with_name(attempt.name+'-retry-'+str(time.time_ns()))
                    catalog, counts = _pdf_catalog(document, path, attempt, fake=fake,reading_folder=source_folder)
                    if not counts.get('native_error') and not counts.get('ranking_error'):
                        _write(cached,json.loads(catalog.to_json()))
                metrics.append(dict(file=path.name, **counts))
                if counts.get("native_error"):
                    failures.append(dict(file=path.name, stage="verification", **counts["native_error"]))
                if counts.get('ranking_error'):
                    failures.append(dict(file=path.name,stage='overview_ranking',detail=str(counts['ranking_error'])))
                if not catalog.units:
                    failures.append(dict(file=path.name, stage="verification", detail="No source units passed the unchanged verification gates."))
            else:
                raise ValueError("PDF_OR_JSON_REQUIRED")
            catalogs.append(catalog)
            coverage.append(item_coverage)
            if not (source_folder / 'catalog.json').exists() or not item_coverage.get('complete'):
                _write(source_folder / "catalog.json", json.loads(catalog.to_json()))
        except Exception as exc:
            failures.append(dict(file=path.name, stage="ingestion", error=type(exc).__name__, detail=str(exc)[:300]))
        # A process interruption retains every completed source and its evidence.
        if catalogs:
            partial = merge_catalogs(catalogs, topic=request.get("topic", "Source briefing"),
                                     audience=request.get("audience", "General audience"))
            _write(folder / "partial-catalog.json", json.loads(partial.to_json()))
        _write(folder / "partial-result.json", dict(coverage=coverage, failures=failures, documents=documents,
                                                    catalog=str(folder / "partial-catalog.json") if catalogs else None))
    catalog = merge_catalogs(catalogs, topic=request.get("topic", "Source briefing"),
                             audience=request.get("audience", "General audience"))
    catalog_path = folder / "catalog.json"
    _write(catalog_path, json.loads(catalog.to_json()))
    notebook = None
    if documents:
        from matn_chat.notebooks import bundle
        # Validate/dedupe original structures before bundling; source additions
        # build a new immutable revision rather than mutating an open notebook.
        from matn_contracts.structure import DocumentStructure
        seen, unique = set(), []
        for raw in documents:
            document = DocumentStructure.model_validate_json(Path(raw).read_bytes())
            if document.doc_id not in seen:
                seen.add(document.doc_id)
                unique.append(raw)
        documents = unique
        source_coverage = dict(request.get("source_coverage", {}))
        source_coverage.update({c["doc_id"]: c for c in coverage if c.get("kind") == "pdf"})
        notebook=_bundle_sources(documents,source_coverage,folder/'notebook',request.get('source_cache'))
    result = dict(operation="ingest", status="partial" if failures else "complete", fake=fake,
                  catalog=str(catalog_path), catalogs=[str(catalog_path)], documents=documents, notebook=notebook,
                  coverage=coverage, failures=failures, metrics=dict(seconds=round(time.monotonic() - started, 3),
                  sources=len(catalog.sources), units=len(catalog.units), model_calls=sum(row.get('generation_calls',0) for row in metrics),
                  native_calls=sum(row.get("native_calls", 0) for row in metrics),
                  embedding_calls=0 if fake else None,
                  verification=metrics), **_overview(catalog))
    _event(folder, "sources_ready", sources=len(catalog.sources), units=len(catalog.units), failures=len(failures))
    return result


class _PerSourceSearch:
    """Every selected PDF is queried; global top-k cannot erase a source."""
    def __init__(self, search):
        self.search = search
        self.repo = search.repo
        self.coverage = []

    def query(self, notebook, sources, question, **kwargs):
        hits, per_source = {}, []
        for source in sources:
            value = self.search.query(notebook, [source], question, **kwargs)
            per_source.append(dict(source=source, candidates=len(value["hits"])))
            for hit in value["hits"]:
                hits[hit["chunk_id"]] = hit
        self.coverage.append(dict(question=str(question), sources=per_source))
        return dict(hits=list(hits.values()), source_coverage=per_source)


def _notebook_answer(notebook: str, question: str, folder: Path, *, fake: bool, query_plan=None):
    from matn_storyboard.__main__ import load
    from matn_rag.search import Search
    from matn_chat.reliable import ReliableChatEngine
    repo, name, selected, documents, manifest = load(notebook)
    engine = None
    counter = None
    generator = None
    try:
        search = _PerSourceSearch(Search(repo, None, lexical_only=True))
        if not fake:
            from .answer_retrieval import HybridSearch,HybridBlockRanker
            search=HybridSearch(Search(repo,None,lexical_only=True))
        kwargs = dict(source_coverage=manifest.get("source_coverage", {}),
                      source_revisions=manifest.get("source_revisions", {}))
        if fake:
            kwargs.update(generator=_FakeAnswerGenerator(), entailment=_FakeEntailment())
        else:
            from matn_storyboard.budget import open_ledger
            from matn_storyboard.runtime import Calls, Generator, Native
            from matn_storyboard.core import verifier_identity
            ledger = folder / "qa-ledger"
            ledger.mkdir(exist_ok=True)
            if not (ledger / "ledger.json").exists():
                open_ledger(ledger, experiment=1800, validation=180, closure=60)
            calls = Calls(ledger)
            from .runtime import drain_generator, wait_for_memory, memory_allows
            class SerialNative(Native):
                def check(self, text, evidence, target):
                    if generator is not None and generator.resident:
                        drain_generator(generator)
                        generator.resident = False
                    return super().check(text, evidence, target)
            native = SerialNative(calls, verifier_identity())
            class SerialGenerator(Generator):
                resident = False
                def generate(self, body):
                    import http.client
                    for attempt in range(2):
                        try:
                            return self._attempt(body)
                        except (OSError,EOFError,http.client.HTTPException) as exc:
                            if attempt or self.resident or 'BUDGET' in str(exc) or 'COLLECTION_CAP' in str(exc):
                                raise
                            event=dict(status='RECOVERED',at=time.time(),cause=type(exc).__name__,
                                       action='Confirmed model drain; retry the same bound local call once')
                            with (folder/'recovered.jsonl').open('a') as stream:
                                stream.write(json.dumps(event)+'\n')
                            _event(folder,'Recovered local model call; retrying once')

                def _attempt(self, body):
                    # One local model family occupies RAM at a time, including
                    # the engine's failed-only redraft between native checks.
                    native.close()
                    if self.resident and not memory_allows():
                        # Plan -> write: when the resident generator itself
                        # leaves less than the unchanged guard threshold, unload
                        # it so the guard measures real headroom for a reload.
                        drain_generator(self)
                        self.resident = False
                    wait_for_memory(lambda free, need: _event(folder, 'waiting_for_memory',
                        available_gib=round(free / 1024**3, 2), needed_gib=round(need / 1024**3, 2)))
                    from matn_chat.streaming import StreamingGenerator
                    from matn_storyboard.core import digest
                    row = calls.reserve("generation", dict(payload_sha256=digest(body), payload=body))
                    started = time.monotonic()
                    deadline = self.deadline
                    raw, error = None, None
                    try:
                        self.resident = True
                        raw = StreamingGenerator.generate_stream(self, body, lambda event: None,
                            total=min(375, max(1, deadline - time.time() - 45)), connect=10, read_idle=375)
                        return raw
                    except BaseException as exc:
                        error = exc
                        raise
                    finally:
                        try:
                            if error is not None:
                                drain_generator(self)
                                self.resident = False
                        except BaseException as exc:
                            if error is None:
                                error = exc
                                raise
                        finally:
                            self.deadline = deadline
                            calls.finish(row, complete=error is None, raw=raw, error=repr(error) if error else None,
                                         actual_attempt_seconds=time.monotonic() - started)
            generator = SerialGenerator(calls)
            from eval.chat.token_budget import TokenCounter
            counter = TokenCounter()
            kwargs.update(generator=generator, entailment=native,token_counter=counter,num_ctx=4096,reranker=HybridBlockRanker())
        from .answer_engine import AppChatEngine
        progressive=[]
        def verified(item,index):
            refs=item.get('citations',[]);ref=refs[0] if refs else {}
            progressive.append(dict(id=f'P{len(progressive)+1}',text=item['text'],quote=ref.get('quote',''),
                title=next((d.title for d in documents if d.doc_id==ref.get('doc_id')),None),
                doc_id=ref.get('doc_id'),page=ref.get('pdf_page_index',-1)+1,span=ref,spans=refs,
                status='verified',at=time.time(),region=engine.region_labels.get(ref.get('block_id'),'body'),binding=item['receipt']['request_sha256']))
            _write(folder/'verified-progress.json',dict(first_at=progressive[0]['at'],sentences=progressive))
        if not fake:
            kwargs['on_verified']=verified
            kwargs['on_status']=lambda stage,index,total:_event(folder,stage,sentence=index,sentences_total=total)
        engine = (ReliableChatEngine if fake else AppChatEngine)(search, documents, **kwargs)
        value = (engine.ask(name, selected, query_plan["current_question"], query_plan=query_plan)
                 if query_plan else engine.ask(name, selected, question))
        if value.get("error"):
            value["error_detail"] = next((entry["error"].get("detail", "") for entry in reversed(engine.trace) if entry.get("error")), "")
        if not fake:
            _write(folder/'answer-embedding-calls.json',search.audit)
            ledger_value=json.loads((ledger/'ledger.json').read_bytes())
            for field,kind in [('query_embedding','query_inputs'),('corpus_embedding','corpus_inputs')]:
                ledger_value['calls'][field]+=sum(row.get(kind,0) for row in search.audit)
            _write(ledger/'ledger.json',ledger_value)
        value["app_calls"] = dict(generation=0, native=0) if fake else json.loads((ledger / "ledger.json").read_bytes())["calls"]
        _write(folder / "answer-receipts.json", dict(response=value, trace=engine.trace, fake=fake))
        from .reading_hygiene import regions
        value['_region_labels']={k:v for d in documents for k,v in regions(d).items()}
        return value, search.coverage
    finally:
        if engine is not None:
            engine.entailment.close()
        if generator is not None and generator.resident:
            drain_generator(generator)
        if counter is not None:
            counter.close()
        repo.db.close()


def _combine_notebooks(notebooks, folder: Path):
    """One Q&A turn sees the union of source snapshots, once per document."""
    from matn_storyboard.__main__ import load
    from matn_chat.notebooks import bundle
    unique = list(dict.fromkeys(notebooks))
    if len(unique) <= 1:
        return unique
    # Inspect immutable manifest/file hashes before constructing every historic
    # DocumentStructure. The selected snapshot is still validated by load() at
    # answer time, including its index fingerprint and complete source binding.
    best, inventories = {}, []
    for notebook in unique:
        manifest_path=Path(str(notebook)+'.structures.json')
        manifest=json.loads(manifest_path.read_bytes())
        declared=manifest.get('source_coverage',{})
        inventory={}
        for doc_id,raw in manifest['documents'].items():
            path=Path(raw)
            if not path.is_absolute():path=manifest_path.parent/path
            if doc_id not in declared:
                inventory={};break
            score=len(declared[doc_id].get('ready_pages',[]))
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            inventory[doc_id]=(score,digest)
            if doc_id not in best or score>=best[doc_id][0]:best[doc_id]=(score,digest)
        inventories.append((notebook,inventory))
    if inventories and all(inventory for _,inventory in inventories):
        for notebook,inventory in reversed(inventories):
            if inventory==best:
                return [notebook]
    documents, coverage, revisions, snapshots = {}, {}, {}, []
    for notebook in unique:
        repo, _, _, docs, manifest = load(notebook)
        try:
            for document in docs:
                previous = documents.get(document.doc_id)
                # A later fuller publication replaces its earlier partial
                # snapshot; an old short revision cannot erase completed pages.
                if previous is None or len(document.pages) >= len(previous.pages):
                    documents[document.doc_id] = document
            coverage.update(manifest.get("source_coverage", {}))
            revisions.update(manifest.get("source_revisions", {}))
            snapshots.append((notebook, {d.doc_id: d.model_dump(mode='json') for d in docs},
                              manifest.get('source_coverage', {}), manifest.get('source_revisions', {})))
        finally:
            repo.db.close()
    wanted = {key: value.model_dump(mode='json') for key, value in documents.items()}
    for notebook, snapshot, declared, published in reversed(snapshots):
        if snapshot == wanted and declared == coverage and published == revisions:
            return [notebook]
    target = folder / "answer-notebook"
    if not (target / "notebook.db").exists():
        paths = []
        for doc_id, document in documents.items():
            path = folder / "answer-documents" / (doc_id + ".json")
            _write(path, document.model_dump(mode="json"))
            paths.append(path)
        notebook = bundle(paths, target)
        manifest_path = Path(str(notebook) + ".structures.json")
        manifest = json.loads(manifest_path.read_bytes())
        manifest.update(source_coverage=coverage, source_revisions=revisions)
        _write(manifest_path, manifest)
    return [str(target / "notebook.db")]


class _FakeAnswerGenerator:
    """An intentional abstention drives catalog-copy fallback in fake app tests."""
    def generate(self, body):
        return dict(done=True, done_reason="stop", thinking="", response='{"sentences": []}')


def _rank_citations(citations: list[dict], question: str) -> list[dict]:
    from matn_chat.question_scope import question_scope
    from matn_chat.evidence_selection import terms, score_many
    query = getattr(question, "retrieval_text", question)
    words = terms(query)
    # An explicitly named source narrows the displayed fallback, while every
    # selected source still receives its retrieval query. Metadata selects a
    # source; it never establishes factual support for a sentence.
    generic = set("document report source uploaded unknown pdf json http https www com org".split())
    metadata = {}
    for citation in citations:
        metadata.setdefault(citation["doc_id"], set()).update(terms(" ".join(str(citation.get(k) or "") for k in ("title", "file"))) - generic)
    named = set()
    for doc, tokens in metadata.items():
        other = set().union(*(v for k, v in metadata.items() if k != doc))
        if any(t in words and t not in other and not t.isdigit() for t in tokens):
            named.add(doc)
    scores = score_many(query, [c["text"] + " " + str(c.get("path") or "") for c in citations])
    scored = []
    for position, citation in enumerate(citations):
        from .reading_hygiene import allowed
        if not allowed(citation.get('region','body'),question):
            continue
        if named and citation["doc_id"] not in named:
            continue
        text = citation["text"]
        if not question_scope(question, [text])["passed"]:
            continue
        score = scores[position]
        if score:
            scored.append((-score, position, citation))
    # One relevant result per source first, then fill additional context. This is
    # source coverage of relevant evidence, never a claim that every source agrees.
    scored.sort(key=lambda item: item[:2])
    first, rest, seen = [], [], set()
    for _, _, citation in scored:
        if citation["doc_id"] not in seen:
            first.append(citation)
            seen.add(citation["doc_id"])
        else:
            rest.append(citation)
    return (first + rest)[:8]


def _answer(request: dict) -> dict:
    started = time.monotonic()
    folder = Path(request["workdir"]).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    question = str(request.get("question", "")).strip()
    if not question:
        raise ValueError("QUESTION_REQUIRED")
    query_plan = request.get("query_plan")
    if query_plan:
        from matn_chat.reliable import AnswerRequest
        question = AnswerRequest(query_plan["current_question"], query_plan["reference_question"])
    catalogs = [_load_catalog(p) for p in request.get("catalogs", [])]
    if request.get("catalog"):
        catalogs.append(_load_catalog(request["catalog"]))
    catalog = merge_catalogs(catalogs)
    citations = catalog_citations(catalog)
    failures, native_answers, retrieval = [], [], []
    notebooks = list(request.get("notebooks", []))
    if request.get("notebook"):
        notebooks.append(request["notebook"])
    notebooks = _combine_notebooks(notebooks, folder)
    _event(folder, "answering_from_sources", sources=len(catalog.sources))
    fake = bool(request.get("fake", False))
    for notebook in dict.fromkeys(notebooks):
        try:
            value, coverage = _notebook_answer(notebook, question, folder, fake=fake, query_plan=query_plan)
            native_answers.append(value)
            regions=value.pop('_region_labels',{})
            for citation in citations:
                block=citation.get('span',{}).get('block_id')
                if block in regions:citation['region']=regions[block]
            retrieval.extend(coverage)
            if value.get("error"):
                failures.append(dict(stage="grounded_answer", error=value["error"], detail=value.get("error_detail", "")))
        except Exception as exc:
            failures.append(dict(stage="grounded_answer", error=type(exc).__name__, detail=str(exc)[:300]))
    # If the requested fact was not established, draft supported background
    # from a separate bounded retrieval. Never infer report-wide absence from a
    # search miss, and never promote the background to a direct answer.
    coverage_only=False
    def generated(value):
        return any(s.get('kind')=='generated_verified_unit' and s.get('receipt_index') is not None and value.get('receipts',[])[s['receipt_index']].get('receipt',value['receipts'][s['receipt_index']]).get('status')=='verified' for s in value.get('sentences',[]))
    if not fake and not failures and notebooks and not any(generated(v) for v in native_answers):
        from matn_chat.question_scope import YEAR
        background='Summarize supported source background relevant to this request; do not infer missing facts: '+YEAR.sub('',str(question)).replace('?','.')
        for notebook in dict.fromkeys(notebooks):
            child=folder/'coverage-attempt';child.mkdir(exist_ok=True)
            try:
                value,coverage=_notebook_answer(notebook,background,child,fake=False)
                value['coverage_only']=True;native_answers.append(value);retrieval.extend(coverage)
                coverage_only=coverage_only or generated(value)
            except Exception as exc:
                failures.append(dict(stage='source_coverage',error=type(exc).__name__,detail=str(exc)[:300]))
    selected = _rank_citations(citations, question)
    text, answer_citations = [], []
    # Engine answers remain verified by their actual receipts; excerpts are kept
    # labelled by the engine. Previous assistant messages never enter this path.
    for value in native_answers:
        for sentence in value.get("sentences", []):
            receipt = value.get("receipts", [])[sentence["receipt_index"]] if sentence.get("receipt_index") is not None else None
            receipt = receipt.get("receipt", receipt) if receipt else None
            if sentence.get("kind") != "generated_verified_unit" or not receipt or receipt.get("status") != "verified":
                continue
            sid = str(len(answer_citations) + 1)
            refs = sentence.get("citations", [])
            ref = refs[0] if refs else {}
            source = next((s for s in catalog.sources if s.doc_id == ref.get("doc_id")), None)
            answer_citations.append(dict(id=sid, text=sentence["text"], quote=ref.get("quote", ""),
                       source=source.id if source else ref.get("doc_id"), title=source.title if source else None,
                       file=source.file if source else None, url=source.url if source else None,
                       source_type=source.type if source else "uploaded document", fetched=source.accessed if source else None,
                       status="verified" if receipt and receipt.get("status") == "verified" else "source_excerpt",
                       page=ref.get("pdf_page_index", -1) + 1, path=None, span=ref, spans=refs,
                       verification=receipt, kind=sentence.get("kind")))
            text.append(sentence["text"] + " [" + sid + "]")
    # Retrieval stays internal. Never turn selected catalog entries, copied
    # source units or an excerpt recovery into a chat reply (including fixtures).
    partial=bool(text) and (coverage_only or bool(failures) or any(v.get('state')!='answered' for v in native_answers))
    response="\n\n".join(text)
    if not response:
        response=("Fixture mode: generated answers require a real local model." if fake else
                  "I could not verify a written answer to this question from the available sources.")
        if failures:response+=' Retry this question; earlier verified sources remain available.'
    return dict(operation="answer",status="partial_answer" if partial else "answered" if text else "abstained",
                text=response,question=str(request.get('question','')),retryable=bool(failures),
                answer_kind="generated_source_coverage" if coverage_only else "generated_answer" if text else "no_verified_generated_answer",fake=fake,
                citations=answer_citations,failures=failures,coverage=retrieval,
                engine_states=[v.get("state") for v in native_answers],
                message="Context only: the requested answer was not verified. These sentences describe supported background." if coverage_only else "AI review, pending owner labels; verification is not a completeness judgment.",
                unsupported_notice=not bool(text),
                metrics=dict(seconds=round(time.monotonic()-started,3),sources=len(catalog.sources),
                    units=len(text),model_calls=sum(v.get("app_calls",{}).get("generation",0) for v in native_answers),
                    native_calls=sum(v.get("app_calls",{}).get("native",0) for v in native_answers),
                    verification_blocks=sum(1 for v in native_answers for r in v.get("receipts",[]) if r.get("receipt",r).get("status")!="verified"),
                    dropped_sentences=sum(v.get("dropped_sentences",0) for v in native_answers)))


def answer(request: dict) -> dict:
    """Keep bounded question context scoped to the current source revision."""
    if not request.get("session") or not request.get("session_dir"):
        return _answer(request)
    from matn_chat.conversation import Conversation
    paths = list(request.get("catalogs", [])) + ([request["catalog"]] if request.get("catalog") else [])
    catalogs = [_load_catalog(p) for p in paths]
    scope = dict(documents=sorted({s.doc_id for c in catalogs for s in c.sources}),
                 bindings=sorted({u.binding for c in catalogs for u in c.units}))
    revision = hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()[:16]
    session = str(request["session"])[:90] + ":" + revision
    with Conversation(request["session_dir"], session, scope) as conversation:
        question = str(request.get("question", ""))
        plan = conversation.plan(question)
        if plan["reference_question"]:
            # Reasoning trace only; the rewrite never appears in the answer.
            _event(Path(request["workdir"]).resolve(), "followup_rewrite", standalone_question=plan["standalone_question"][:500])
        value = _answer(dict(request, query_plan=plan))
        # Conversation retains orientation only; subsequent retrieval and every
        # check still use the selected original source snapshots.
        remembered = dict(state="answered" if value["status"] == "answered" else "insufficient_evidence",
                          sentences=[dict(text=c["text"]) for c in value["citations"]])
        conversation.remember(question, plan["retrieval_query"], remembered)
        value["conversation"] = remembered.get("conversation")
        value["query_plan"] = plan
        value["source_scope_revision"] = revision
        return value


def run_request(request: dict) -> dict:
    operation = request.get("operation")
    if operation == "ingest":
        return ingest(request)
    if operation == "answer":
        return answer(request)
    if operation == "overview":
        paths = request.get("catalogs", []) + ([request["catalog"]] if request.get("catalog") else [])
        catalog = merge_catalogs([_load_catalog(p) for p in paths])
        return dict(operation="overview", status="complete", **_overview(catalog))
    raise ValueError("UNSUPPORTED_EVIDENCE_OPERATION")
