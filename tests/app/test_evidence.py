"""App evidence uses real copy/provenance gates with fake native adapters only."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from matn_app import evidence


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def ingest_json(tmp_path, value, name="source.json"):
    source = write_json(tmp_path / name, value)
    result = evidence.run_request(dict(operation="ingest", inputs=[str(source)],
                                       workdir=str(tmp_path / (name + "-job")), fake=True))
    return source, result


def test_json_ingest_keeps_escaped_pointer_and_exact_numeric_provenance(tmp_path):
    _, result = ingest_json(tmp_path, {"a/b": {"~key": "Alpha may expand only if demand grows."}, "count": 12})
    assert result["status"] == "complete"
    assert result["metrics"]["model_calls"] == 0
    text = next(c for c in result["citations"] if c["unit_id"])
    number = next(c for c in result["citations"] if c["unit_id"] is None)
    assert text["path"] == "/a~1b/~0key"
    assert text["quote"] == "Alpha may expand only if demand grows."
    assert number["path"] == "/count" and number["quote"] == "12"
    assert number["status"] == "exact_json_copy"
    answer = evidence.answer(dict(question="What count?", catalogs=[result["catalog"]],
                                    workdir=str(tmp_path / "answer"), fake=True))
    assert answer["status"] == "abstained" and not answer["citations"]
    assert "12" not in answer["text"]  # catalog-copy fallback cannot become a chat answer


def test_uploaded_json_cannot_instruct_adapter_to_open_local_files(tmp_path):
    secret = tmp_path / "private.json"
    secret.write_text('{"secret": "NEVER_READ"}')
    _, result = ingest_json(tmp_path, {"matn_json_sources": 1, "sources": [{"file": str(secret)}],
                                       "units": [{"status": "verified", "text": "A user-supplied statement."}]})
    catalog = evidence._load_catalog(result["catalog"])
    assert "NEVER_READ" not in catalog.to_json()
    assert len(catalog.sources) == 1
    assert all(c["path"] is not None for c in result["citations"])


def test_json_hash_in_filename_and_key_do_not_corrupt_pointer(tmp_path):
    _, result = ingest_json(tmp_path, {"a#": {"b/c": "Alpha may expand."}}, "source#one.json")
    assert result["citations"][0]["path"] == "/a#/b~1c"


def test_add_file_merges_without_rewriting_prior_units_and_shows_side_by_side_difference(tmp_path):
    first, one = ingest_json(tmp_path, {"finding": "Alpha may expand."}, "one.json")
    second = write_json(tmp_path / "two.json", {"finding": "Alpha must wait."})
    two = evidence.ingest(dict(inputs=[str(second)], catalogs=[one["catalog"]],
                               workdir=str(tmp_path / "second-job"), fake=True))
    assert len(two["sources"]) == 2
    assert {c["text"] for c in two["citations"]} == {"Alpha may expand.", "Alpha must wait."}
    assert two["disagreements"][0]["path"] == "/finding"
    assert "comparability is not established" in two["disagreements"][0]["label"]
    output = tmp_path / "merged.json"
    assert evidence.merge_catalogs([one["catalog"], two["catalog"]], output) == output
    merged = evidence._load_catalog(output)
    assert len(merged.sources) == 2 and len(merged.units) == 2
    assert first.read_text() == '{"finding": "Alpha may expand."}'
    identical = evidence.merge_catalogs([merged, merged])
    assert len(identical.plan.axes) == len(merged.plan.axes)


def test_changed_json_is_rejected_and_failed_sources_do_not_hide_good_source(tmp_path):
    source, result = ingest_json(tmp_path, {"finding": "The rate was 12 percent."})
    source.write_text('{"finding":"The rate was 90 percent."}')
    with pytest.raises(ValueError, match="SOURCE_OR_RECEIPT_CHANGED"):
        evidence._load_catalog(result["catalog"])
    other = write_json(tmp_path / "other.json", {"finding": "Beta may expand."})
    broken = tmp_path / "broken.json"
    broken.write_text("{broken")
    value = evidence.ingest(dict(inputs=[str(broken), str(other)], workdir=str(tmp_path / "partial"), fake=True))
    assert value["status"] == "partial" and len(value["failures"]) == 1
    assert value["citations"][0]["text"] == "Beta may expand."
    assert (tmp_path / "partial" / "partial-catalog.json").exists()


def test_pdf_catalog_reuses_native_scope_veto_and_preserves_page_span(tmp_path):
    from tests.verification.test_rules import doc
    file = tmp_path / "source.pdf"
    file.write_bytes(b"%PDF-test")
    folder = tmp_path / "verify"
    folder.mkdir()
    document = doc("Alpha may expand only if demand grows.", "However, Alpha must pause when demand falls.")
    catalog, metrics = evidence._pdf_catalog(document, file, folder, fake=True)
    saved = json.loads((folder / "verification.json").read_bytes())
    # The first exact sentence is still blocked when the adjacent qualifier is
    # omitted; a fake perfect native adapter cannot override preserved scope.
    assert saved["blocked"]
    assert any("scope_unknown" in b["reasons"] for b in saved["blocked"])
    assert all(u.text != "Alpha may expand only if demand grows." for u in catalog.units)
    assert all(c["page"] == 1 and c["span"]["quote"] for c in evidence.catalog_citations(catalog))
    assert metrics["attempted"] == len(saved["receipts"])


def test_pdf_catalog_never_promotes_failed_native_verification(tmp_path, monkeypatch):
    from tests.verification.test_rules import doc
    from matn_verification.contracts import Check
    import matn_chat.engine
    class Reject:
        def check(self, text, evidence, target):
            return Check(target=target, layer="L4", verdict="reject", reasons=("entailment_failed",))
        def close(self):
            pass
    monkeypatch.setattr(matn_chat.engine, "MiniCheck", Reject)
    file = tmp_path / "source.pdf"
    file.write_bytes(b"%PDF-test")
    catalog, metrics = evidence._pdf_catalog(doc("Alpha may expand."), file, tmp_path, fake=False)
    assert not catalog.units and metrics["blocked"] == 1


def test_source_search_queries_every_selected_source_and_keeps_each_leg():
    class Search:
        repo = object()
        def __init__(self): self.selected = []
        def query(self, notebook, sources, question, **kwargs):
            self.selected.append(sources)
            return dict(hits=[dict(chunk_id=sources[0], text="original " + sources[0])])
    underlying = Search()
    search = evidence._PerSourceSearch(underlying)
    result = search.query("n", ["a", "b"], "question", depth=100)
    assert underlying.selected == [["a"], ["b"]]
    assert {h["chunk_id"] for h in result["hits"]} == {"a", "b"}
    assert search.coverage[0]["sources"] == [dict(source="a", candidates=1), dict(source="b", candidates=1)]


def test_native_failure_retains_prior_verified_pdf_units(tmp_path, monkeypatch):
    from tests.verification.test_rules import doc
    from matn_verification.contracts import Check
    import matn_chat.engine
    class FailsLater:
        def __init__(self): self.calls = 0
        def check(self, text, evidence, target):
            self.calls += 1
            if self.calls > 3:
                raise RuntimeError("local verifier stopped")
            return Check(target=target, layer="L4", verdict="pass")
        def close(self): pass
    monkeypatch.setattr(matn_chat.engine, "MiniCheck", FailsLater)
    file = tmp_path / "source.pdf"
    file.write_bytes(b"%PDF-test")
    catalog, metrics = evidence._pdf_catalog(doc("Alpha may expand.", "Beta may wait."), file, tmp_path, fake=False)
    assert len(catalog.units) == 1
    assert metrics["native_error"]["error"] == "NativeVerificationUnavailable"
    assert (tmp_path / "verification-partial.json").exists()


def test_answer_respects_explicit_dates_and_includes_relevant_sources(tmp_path):
    _, one = ingest_json(tmp_path, {"finding": "Revenue was 12 percent in 2021."}, "one.json")
    _, two = ingest_json(tmp_path, {"finding": "Revenue was 8 percent in 2021."}, "two.json")
    answer = evidence.answer(dict(catalogs=[one["catalog"], two["catalog"]], question="What revenue in 2021?",
                                   workdir=str(tmp_path / "answer"), fake=True))
    assert answer["status"] == "abstained" and not answer["citations"]
    unknown = evidence.answer(dict(catalogs=[one["catalog"], two["catalog"]], question="What revenue in 2025?",
                                    workdir=str(tmp_path / "unknown"), fake=True))
    assert unknown["status"] == "abstained" and not unknown["citations"]


def test_followup_context_persists_questions_and_resets_for_added_source(tmp_path,monkeypatch):
    _, one = ingest_json(tmp_path, {"finding": "Revenue was 12 percent in 2021."}, "one.json")
    catalog=evidence._load_catalog(one['catalog'])
    def generated(*args,**kwargs):
        return dict(state='answered',receipts=[dict(status='verified')],sentences=[dict(
            text='Revenue was reported at 12 percent in 2021.',kind='generated_verified_unit',receipt_index=0,
            citations=[dict(doc_id=catalog.sources[0].doc_id,quote='Revenue was 12 percent in 2021.',pdf_page_index=0)])]),[]
    monkeypatch.setattr(evidence,'_notebook_answer',generated)
    base = dict(catalogs=[one["catalog"]],notebooks=["fixture.db"], session="conversation-one", session_dir=str(tmp_path / "sessions"), fake=True)
    first = evidence.answer(dict(base, question="What revenue in 2021?", workdir=str(tmp_path / "answer-one")))
    second = evidence.answer(dict(base, question="What about those revenues?", workdir=str(tmp_path / "answer-two")))
    assert second["status"] == "answered"
    assert second["query_plan"]["reference_question"] == "What revenue in 2021?"
    assert second["conversation"]["context_is_evidence"] is False
    _, two = ingest_json(tmp_path, {"finding": "Costs were 8 percent in 2021."}, "two.json")
    updated = evidence.answer(dict(base, catalogs=[one["catalog"], two["catalog"]], question="What costs in 2021?",
                                    workdir=str(tmp_path / "answer-three")))
    assert updated["source_scope_revision"] != first["source_scope_revision"]
    assert updated["conversation"]["prior_turns"] == 0


def test_merge_remaps_synthesis_figures_numbers_and_preserves_exact_sources(tmp_path):
    from matn_deck.catalog import Figure, SynthesisSentence
    _, result = ingest_json(tmp_path, {"finding": "Revenue was 12 percent in 2021."})
    catalog = evidence._load_catalog(result["catalog"])
    unit = catalog.units[0]
    figure = Figure("F1", unit.span.doc_id, unit.source, 0, (0., 0., 100., 100.), "Original caption", "caption", unit.axis, (unit.id,))
    catalog = replace(catalog, figures=(figure,), synthesis=(SynthesisSentence(unit.axis, unit.text, (unit.id,)),))
    merged = evidence.merge_catalogs([catalog])
    assert merged.figures[0].axis == merged.units[0].axis
    assert merged.figures[0].unit_ids == (merged.units[0].id,)
    assert merged.synthesis[0].unit_ids == (merged.units[0].id,)
    assert merged.numbers[0].unit_id == merged.units[0].id
    assert merged.units[0].span == unit.span


def test_worker_failure_writes_designated_result_and_preserves_partial_pointer(tmp_path):
    from matn_app.evidence_worker import main
    workdir = tmp_path / "job"
    workdir.mkdir()
    write_json(workdir / "partial-result.json", dict(catalog="partial-catalog.json"))
    output = workdir / "result.json"
    request = write_json(tmp_path / "request.json", dict(operation="unknown", workdir=str(workdir), output=str(output)))
    assert main([str(request)]) == 1
    value = json.loads(output.read_bytes())
    assert value["status"] == "failed" and value["partial"]["catalog"] == "partial-catalog.json"


def test_worker_sigterm_publishes_interruption_before_cleanup(tmp_path, monkeypatch):
    import os
    import signal
    from matn_app import evidence_worker
    output = tmp_path / "result.json"
    request = write_json(tmp_path / "request.json", dict(operation="answer", workdir=str(tmp_path), output=str(output),
                                                         catalogs=["existing-verified-catalog.json"]))
    def terminate(request):
        os.kill(os.getpid(), signal.SIGTERM)
    monkeypatch.setattr(evidence_worker, "run_request", terminate)
    assert evidence_worker.main([str(request)]) == 1
    result = json.loads(output.read_bytes())
    assert result["status"] == "interrupted"
    # The outer failure record and the initial signal record both retain
    # existing source evidence; no new model text becomes a result.
    assert result["citations"] == []


def test_worker_json_roundtrip_needs_no_model_or_network(tmp_path):
    source = write_json(tmp_path / "source.json", {"finding": "Alpha may expand only if demand grows."})
    output = tmp_path / "job" / "result.json"
    request = write_json(tmp_path / "request.json", dict(operation="ingest", inputs=[str(source)],
                                                         workdir=str(output.parent), output=str(output), fake=True))
    run = subprocess.run([sys.executable, "-B", "-m", "matn_app.evidence_worker", str(request)],
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert json.loads(output.read_bytes())["citations"][0]["path"] == "/finding"


def test_fake_file_journey_reads_digital_pdf_indexes_and_answers_without_model(tmp_path):
    from tests.reading.pdf_fixtures import write_pdf
    pdf = write_pdf(tmp_path / "public-fixture.pdf",
                    b"BT /F1 12 Tf 72 600 Td (Alpha may expand only if demand grows.) Tj ET\n"
                    b"BT /F1 12 Tf 72 560 Td (Revenue was 12 percent in 2021.) Tj ET\n")
    result = evidence.ingest(dict(inputs=[str(pdf)], workdir=str(tmp_path / "ingest"), fake=True))
    assert result["status"] == "complete", result["failures"]
    assert result["notebook"] and result["documents"]
    assert result["coverage"][0]["complete"]
    assert result["citations"] and all(c["page"] == 1 for c in result["citations"])
    answer = evidence.answer(dict(question="What revenue in 2021?", catalogs=[result["catalog"]],
                                   notebooks=[result["notebook"]], workdir=str(tmp_path / "answer"), fake=True))
    assert answer["status"] == "abstained" and "12 percent" not in answer["text"]
    assert answer["metrics"]["model_calls"] == 0


def test_notebook_union_deduplicates_sources_before_one_answer(tmp_path):
    from tests.reading.pdf_fixtures import write_pdf
    from matn_storyboard.__main__ import load
    first = write_pdf(tmp_path / "one.pdf", b"BT /F1 12 Tf 72 600 Td (Alpha may expand.) Tj ET\n")
    second = write_pdf(tmp_path / "two.pdf", b"BT /F1 12 Tf 72 600 Td (Beta may wait.) Tj ET\n")
    one = evidence.ingest(dict(inputs=[str(first)], workdir=str(tmp_path / "one"), fake=True))
    two = evidence.ingest(dict(inputs=[str(second)], documents=one["documents"],
                               catalogs=[one["catalog"]], workdir=str(tmp_path / "two"), fake=True))
    target = tmp_path / "combined"
    target.mkdir()
    notebooks = evidence._combine_notebooks([one["notebook"], two["notebook"]], target)
    assert len(notebooks) == 1
    repo, _, selected, docs, _ = load(notebooks[0])
    try:
        assert len(selected) == len(docs) == 2
    finally:
        repo.db.close()


def test_nonfinite_json_numbers_are_explicit_failure(tmp_path):
    source = tmp_path / "invalid.json"
    source.write_text('{"count": NaN}')
    result = evidence.ingest(dict(inputs=[str(source)], workdir=str(tmp_path / "job"), fake=True))
    assert result["status"] == "partial"
    assert "NONFINITE_JSON_NUMBER" in result["failures"][0]["detail"]


def test_fake_app_research_executes_real_v2_pipeline_and_catalog_adapter(tmp_path):
    from matn_app.demo import research
    from matn_deck.catalog_adapters import from_research
    folder = tmp_path / "research"
    outcome = research(folder, "Offline product demonstration")
    assert outcome["fake"] and outcome["live_search"] == 0
    assert outcome["fake_search_attempts"] == 4
    assert outcome["verified_units"] > 0
    catalog = from_research(folder)
    assert len(catalog.units) > 0 and len(catalog.plan.axes) == 4
    assert all("synthetic source" in u.text for u in catalog.units)


def test_empty_overview_has_no_presentation_proposal():
    from matn_deck.catalog import EvidenceCatalog, Plan
    catalog = EvidenceCatalog(plan=Plan("Empty", "Audience", "Brief", "English", ()), units=(), sources=())
    result = evidence._overview(catalog)
    assert result["proposal"] is None and result["comparison_status"] is None


def test_catalog_fallback_respects_named_source_and_ignores_question_stopwords():
    citations = [dict(id="U1", doc_id="a", text="A bank recommends digital skills training.", title="Cedar Bank Report", file="cedar.json", path=None),
                 dict(id="U2", doc_id="b", text="Workers would need training by 2030.", title="Workforce Survey", file="workforce.json", path=None)]
    found = evidence._rank_citations(citations, "What does Cedar Bank recommend for digital skills?")
    assert [c["id"] for c in found] == ["U1"]
    assert evidence._rank_citations(citations, "What is the and does?") == []


def test_shared_quote_stays_attached_to_each_distinct_research_axis(tmp_path):
    from dataclasses import replace
    from matn_deck.catalog import Axis
    _, result = ingest_json(tmp_path, {"finding": "Alpha may expand."})
    first = evidence._load_catalog(result["catalog"])
    second = replace(first, plan=replace(first.plan, axes=(Axis("new", "A different research question"),)),
                     units=tuple(replace(u, axis="new") for u in first.units))
    merged = evidence.merge_catalogs([first, second])
    assert len(merged.units) == 2
    assert {u.axis for u in merged.units} == {a.id for a in merged.plan.axes}
    again = evidence.merge_catalogs([merged, merged])
    assert len(again.units) == 2


def test_verified_source_copy_is_never_returned_as_an_answer(tmp_path, monkeypatch):
    _, result = ingest_json(tmp_path, {"finding": "Alpha may expand."})
    catalog = evidence._load_catalog(result["catalog"])
    def copied(*args, **kwargs):
        return dict(state="partial_answer", app_calls=dict(generation=1, native=1),
                    receipts=[dict(status="verified")], sentences=[dict(text="Alpha may expand.", kind="source_copy",
                    receipt_index=0, citations=[dict(doc_id=catalog.sources[0].doc_id, quote="Alpha may expand.", pdf_page_index=0)])]), []
    monkeypatch.setattr(evidence, "_notebook_answer", copied)
    answer = evidence.answer(dict(question="What may Alpha do?", catalogs=[result["catalog"]],
                                  notebooks=["stub.db"], workdir=str(tmp_path / "answer")))
    assert answer["answer_kind"] == "no_verified_generated_answer"
    assert "Alpha may expand" not in answer["text"] and answer["citations"] == []
    assert answer["engine_states"] and set(answer["engine_states"]) == {"partial_answer"}
