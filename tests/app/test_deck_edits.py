"""Fake-mapper and immutable-source tests; no network or model calls."""
from dataclasses import replace
import json
from pathlib import Path
import hashlib

import pytest

from matn_deck.catalog import Axis, Context, EvidenceCatalog, Plan, Source, Span, Unit
from matn_deck.deck_qa import storyboard_fidelity
from matn_deck.edits import (
    DeckEdit, UnsupportedEdit, apply_edit, edit_payload, fake_edit, layout_overrides,
    load_storyboard, validate_storyboard,
)
from matn_deck.storyboard_v2 import Controls, build_storyboard


def catalog_fixture():
    def unit(uid, axis, text, source, context=()):
        span = Span("sha256-" + source * 32, uid, 0, len(text), text, page_index=0)
        return Unit(uid, axis, text, span, source, "uploaded document", "verified", "binding-" + uid,
                    context=context)
    context = Context("The review covers regional public offices.", "required", "source-backed context")
    return EvidenceCatalog(
        Plan("Public service access", "Ministry reviewers", "Review evidence", "English",
             (Axis("a1", "Access"), Axis("a2", "Staffing"))),
        (unit("U1", "a1", "Appointment booking is available online.", "S1", (context,)),
         unit("U2", "a1", "Offices publish their opening times.", "S1"),
         unit("U3", "a2", "Staff rotate between service desks.", "S2")),
        (Source("S1", "sha256-" + "a" * 64, "uploaded document", "Example Department", "Access review",
                file="access.json", pages=(1,)),
         Source("S2", "sha256-" + "b" * 64, "uploaded document", "Example Agency", "Staff review",
                file="staff.json", pages=(1,))),
    ).validate()


@pytest.fixture
def evidence():
    catalog = catalog_fixture()
    # Axis titles ensure every verified unit is a bullet in this test fixture.
    story = build_storyboard(catalog, lambda text: False, Controls(date="2026-10-30"),
                             template="ministry_light|fonts=template|safety=0.91")
    return catalog, story


def test_shorten_drops_whole_units_and_preserves_required_context_and_parent(evidence):
    catalog, parent = evidence
    before = parent.to_json()
    child = apply_edit(parent, catalog, {"op": "shorten", "slide": 3, "keep_units": ["U1"]})
    assert parent.to_json() == before
    assert [b.unit_id for b in child.slides[2].bullets] == ["U1"]
    assert child.slides[2].bullets[0].context == parent.slides[2].bullets[0].context
    assert child.slides[2].bullets[0].text.text == catalog.unit("U1").text
    assert child.version == parent.version + 1
    assert storyboard_fidelity(child, catalog) == []


def test_delete_renumbers_citations_and_regenerates_sources_and_notes(evidence):
    catalog, parent = evidence
    child = apply_edit(parent, catalog, {"op": "delete", "slide": 3})
    assert child.citations == ("S2",)
    evidence_slide = next(s for s in child.slides if s.kind == "assertion")
    assert evidence_slide.bullets[0].text.marker == "[1]"
    assert any("U3 [1]" in row for row in evidence_slide.notes)
    sources = next(s for s in child.slides if s.kind == "sources")
    assert [(line.ref, line.marker) for line in sources.lines] == [("S2", "[1]")]
    assert "Access review" not in sources.lines[0].text
    validate_storyboard(child, catalog)


def test_reorder_retains_layout_on_the_same_evidence(evidence):
    catalog, parent = evidence
    layout = apply_edit(parent, catalog, {"op": "change_layout", "slide": 3, "layout": "two_column"})
    child = apply_edit(layout, catalog, {"op": "reorder", "slide": 3, "position": 4})
    assert child.slides[3].axis == "a1"
    assert layout_overrides(child) == {3: "matn:finding:two-col"}
    assert child.slides[2].axis == "a2"
    assert parent.slides[2].axis == "a1"
    assert child.citations == ("S2", "S1")


def test_shorten_reflows_a_layout_that_no_longer_fits_its_unit_count(evidence):
    catalog, parent = evidence
    layout = apply_edit(parent, catalog, {"op": "change_layout", "slide": 3, "layout": "two_column"})
    child = apply_edit(layout, catalog, {"op": "shorten", "slide": 3, "keep_units": ["U1"]})
    assert len(child.slides[2].bullets) == 1
    assert layout_overrides(child) == {}


def test_add_slide_selects_only_verified_evidence_and_preserves_context(evidence):
    catalog, parent = evidence
    child = apply_edit(parent, catalog, {"op": "add_slide", "source": "S1", "unit_ids": ["U1"], "position": 2})
    assert child.slides[1].bullets[0].unit_id == "U1"
    assert child.slides[1].bullets[0].context[0].text == catalog.unit("U1").context[0].quote
    assert child.slides[1].title.text == "Access review"
    assert storyboard_fidelity(child, catalog) == []
    with pytest.raises(UnsupportedEdit, match="do not belong"):
        apply_edit(parent, catalog, {"op": "add_slide", "source": "S1", "unit_ids": ["U3"]})


@pytest.mark.parametrize("edit", [
    {"op": "retitle", "slide": 3, "title": "The policy will save billions."},
    {"op": "shorten", "slide": 3, "keep_units": ["U3"]},
    {"op": "shorten", "slide": 3, "keep_units": []},
    {"op": "delete", "slide": 1},
    {"op": "delete", "slide": 6},
    {"op": "reorder", "slide": 3, "position": 1},
    {"op": "change_layout", "slide": 4, "layout": "two_column"},
    {"op": "change_layout", "slide": 3, "layout": "cards"},
    {"op": "change_template", "template": "../../private"},
    {"op": "retitle", "slide": True, "title": "Access"},
    {"op": "delete", "slide": 3, "text": "New claim"},
    {"op": "unsupported"},
])
def test_unsupported_request_cannot_mutate_the_saved_version(evidence, edit):
    catalog, parent = evidence
    before = parent.to_json()
    with pytest.raises(UnsupportedEdit):
        apply_edit(parent, catalog, edit)
    assert before == parent.to_json()


def test_safe_titles_are_exact_or_neutral_and_context_cannot_disappear(evidence):
    catalog, parent = evidence
    for title in ("Access", catalog.unit("U2").text, catalog.plan.topic, "Further evidence"):
        child = apply_edit(parent, catalog, {"op": "retitle", "slide": 3, "title": title})
        assert child.slides[2].title.text == title
        assert storyboard_fidelity(child, catalog) == []
    with pytest.raises(UnsupportedEdit, match="needs its source context"):
        apply_edit(parent, catalog, {"op": "retitle", "slide": 4, "title": catalog.unit("U1").text})
    bullet = replace(parent.slides[2].bullets[0], context=())
    broken = replace(parent, slides=parent.slides[:2] + (replace(parent.slides[2], bullets=(bullet,)),) + parent.slides[3:])
    with pytest.raises(UnsupportedEdit, match="context was changed"):
        apply_edit(broken, catalog, {"op": "change_template", "template": "midnight"})


def test_changed_catalog_or_citation_refuses_receipt_reuse(evidence):
    catalog, parent = evidence
    changed = replace(catalog, units=(replace(catalog.units[0], text="A different statement."),) + catalog.units[1:])
    with pytest.raises(UnsupportedEdit, match="different evidence"):
        apply_edit(parent, changed, {"op": "change_template", "template": "midnight"})
    wrong = replace(parent, citations=tuple(reversed(parent.citations)))
    with pytest.raises(UnsupportedEdit, match="citation points"):
        apply_edit(wrong, catalog, {"op": "delete", "slide": 4})


def test_mapper_schema_has_only_finite_titles_ids_and_operations(evidence):
    catalog, story = evidence
    body = edit_payload("Make slide 3 punchier", catalog, story)
    schema = body["format"]
    assert schema["additionalProperties"] is False
    assert "unsupported" in schema["properties"]["op"]["enum"]
    assert "The policy will save billions." not in schema["properties"]["title"]["enum"]
    assert schema["properties"]["unit_ids"]["items"]["enum"] == ["U1", "U2", "U3"]
    assert body["model"] == "qwen3.5:9b" and body["think"] is False and body["truncate"] is False


def test_mapper_schema_pairs_each_operation_with_its_arguments(evidence):
    from jsonschema import Draft202012Validator, ValidationError
    catalog, story = evidence
    validator = Draft202012Validator(edit_payload("Shorten slide 3", catalog, story)["format"])
    validator.validate({"op": "shorten", "slide": 3, "keep_units": ["U1"]})
    with pytest.raises(ValidationError):
        validator.validate({"op": "shorten", "slide": 3, "unit_ids": ["U1"], "title": "Access"})
    assert fake_edit("use the dark template", catalog, story).template == "midnight"
    assert fake_edit("shorten slide 3", catalog, story).slide == 3
    assert fake_edit("invent a better statistic", catalog, story).op.value == "unsupported"


def test_model_output_is_an_operation_not_factual_prose(evidence, tmp_path):
    from matn_app.deck_worker import map_edit
    catalog, story = evidence
    class FakeGenerator:
        def generate(self, body):
            assert body["format"]["additionalProperties"] is False
            return {"done": True, "done_reason": "stop", "response": '{"op":"delete","slide":4}'}
    edit = map_edit("Delete slide 4", catalog, story, generator=FakeGenerator(), trace=tmp_path / "mapping.json")
    assert edit.to_dict() == {"op": "delete", "slide": 4}
    assert json.loads((tmp_path / "mapping.json").read_text())["kind"].startswith("local typed")


def test_worker_outputs_new_version_and_fake_mapping_is_labelled(evidence, tmp_path):
    from matn_app.deck_worker import run_request
    catalog, parent = evidence
    cat_path, parent_path = tmp_path / "input.json", tmp_path / "parent.json"
    cat_path.write_text(catalog.to_json())
    parent_path.write_text(parent.to_json())
    seen = []
    def renderer(catalog, template, output, **kwargs):
        story = kwargs["storyboard"]
        seen.append(story)
        assert kwargs["fonts"] == "template" and kwargs["pdf"] is True
        (output / "storyboard.json").write_text(story.to_json())
        (output / "catalog.json").write_text(catalog.to_json())
        return {"status": "QA_PASS", "delivery": {"status": "DELIVERY_READY"}}
    request = {"operation": "edit", "catalog": str(cat_path), "parent_storyboard": str(parent_path),
               "template": "ministry-light", "output": str(tmp_path / "v2"),
               "instruction": "shorten slide 3", "fake": True}
    result = run_request(request, renderer=renderer)
    assert result["ok"] and result["mapping"] == "fake mapper (test mode)"
    assert result["metrics"]["generation_calls"] == 0
    assert result["edit"]["op"] == "shorten"
    assert parent_path.read_text() == parent.to_json()
    assert load_storyboard(Path(result["storyboard"]).read_bytes()) == seen[0]
    assert json.loads((tmp_path / "v2" / "result.json").read_text()) == result
    with pytest.raises(ValueError, match="ALREADY_EXISTS"):
        run_request(request, renderer=renderer)


def test_worker_unsupported_edit_has_reason_and_no_renderer_call(evidence, tmp_path):
    from matn_app.deck_worker import run_request
    catalog, parent = evidence
    cat_path, parent_path = tmp_path / "input.json", tmp_path / "parent.json"
    cat_path.write_text(catalog.to_json())
    parent_path.write_text(parent.to_json())
    def forbidden(*args, **kwargs):
        raise AssertionError("An unsupported operation must not render a deck")
    result = run_request({"operation": "edit", "catalog": str(cat_path), "parent_storyboard": str(parent_path),
                          "output": str(tmp_path / "unsupported"), "edit": {"op": "retitle", "slide": 3,
                          "title": "A new unsupported claim."}}, renderer=forbidden)
    assert result["status"] == "UNSUPPORTED_EDIT" and result["reason"] and result["alternatives"]
    assert result["metrics"]["generation_calls"] == 0


def test_worker_rejects_changed_source_or_receipt_before_rendering(evidence, tmp_path):
    from matn_app.deck_worker import run_request
    catalog, _ = evidence
    source = tmp_path / "source.json"
    source.write_text('{"statement":"Original evidence."}')
    catalog = replace(catalog, origin={"files": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()}})
    cat_path = tmp_path / "catalog.json"
    cat_path.write_text(catalog.to_json())
    source.write_text('{"statement":"Changed evidence."}')
    def forbidden(*args, **kwargs):
        raise AssertionError("Changed evidence must not render")
    result = run_request({"operation": "build", "catalog": str(cat_path), "output": str(tmp_path / "blocked")},
                         renderer=forbidden)
    assert result["status"] == "UNSUPPORTED_EDIT" and "artifact changed" in result["reason"]


def test_explicit_edit_intent_prevents_unrequested_slide_deletion(evidence):
    from matn_deck.edits import explicit_edit,validate_edit_intent,DeckEdit
    assert explicit_edit('Use the Midnight template').to_dict()==dict(op='change_template',template='midnight')
    assert explicit_edit('Move slide 5 to position 4').to_dict()==dict(op='reorder',slide=5,position=4)
    assert explicit_edit('Do not delete slide 3') is None
    with pytest.raises(UnsupportedEdit,match='does not match'):
        validate_edit_intent('Use the Midnight template',DeckEdit.from_dict(dict(op='delete',slide=3)))
    with pytest.raises(UnsupportedEdit,match='requires an explicit'):
        validate_edit_intent('Make it darker',DeckEdit.from_dict(dict(op='delete',slide=3)))


def test_real_model_cannot_return_schema_valid_but_unrequested_delete(evidence):
    from matn_app.deck_worker import map_edit
    catalog,story=evidence
    class WrongMapper:
        def generate(self,body):return dict(done=True,done_reason='stop',response='{"op":"delete","slide":3}')
    with pytest.raises(UnsupportedEdit):
        map_edit('Use the Midnight template',catalog,story,generator=WrongMapper())
