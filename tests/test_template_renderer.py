"""Renderer v1: layouts chosen by name, placeholders filled by name, measured fallback and split."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER

from matn_contracts.domain import ChartSpec, DeckPlan, Slide
from matn_contracts.enums import ChartType, FactStatus, SlideType
from matn_deck.specimen_v2 import specimen_inputs
from matn_deck.specimen import SPECIMEN_DOC_ID, item, sample_fact, sample_table
from matn_deck.template_renderer import (
    DeckRenderError,
    TemplateInvalidError,
    build_presentation,
    render,
)
from matn_deck.templates import GALLERY_DIR, LAYOUTS, default_template_id, gallery

DEFAULT = GALLERY_DIR / default_template_id() / "template.pptx"


@pytest.fixture(scope="module")
def specimen():
    plan, facts, tables = specimen_inputs()
    prs, report = build_presentation(plan, facts, tables, DEFAULT, strict=True)
    return plan, facts, tables, prs, report


def by_name(slide, name):
    return next(shape for shape in slide.shapes if shape.name == name)


def test_specimen_exercises_every_2b_variant_and_slide_type(specimen, tmp_path):
    plan, facts, tables, prs, report = specimen
    assert {slide.slide_type for slide in plan.slides} == set(SlideType)
    assert set(LAYOUTS) <= set(report.layouts)
    assert report.overflows == () and report.warnings == ()
    assert len(prs.slides) == len(report.layouts)
    out = tmp_path / "deck.pptx"
    assert render(plan, facts, tables, DEFAULT, out, strict=True) == report


def test_placeholders_are_filled_by_name_and_nothing_is_left_empty(specimen):
    plan, facts, _, prs, report = specimen
    by_id = {fact.fact_id: fact for fact in facts}
    kpi = next(i for i, layout in enumerate(report.layouts) if layout == "matn:kpi:cards")
    slide = prs.slides[kpi]
    assert slide.slide_layout.name == "matn:kpi:cards"
    assert by_name(slide, "title").text_frame.text == plan.slides[kpi].title
    for n, fact_id in enumerate(plan.slides[kpi].kpi_fact_ids, start=1):
        value = by_id[fact_id].number_value
        runs = by_name(slide, f"kpi_value_{n}").text_frame.paragraphs[0].runs
        assert runs[0].text == value.value_as_written
        assert "".join(r.text for r in runs[1:]).strip() == (value.unit or "")
        assert by_name(slide, f"kpi_label_{n}").text_frame.text == value.label
    assert by_name(slide, "source").text_frame.text == "p. 3, 5, 6, 7"
    for slide in prs.slides:
        for shape in slide.placeholders:
            assert shape.has_chart if shape.name == "chart" else shape.text_frame.text.strip(), shape.name
            assert not re.fullmatch(r".* \d+", shape.name), shape.name  # renamed to the contract name


def test_the_chart_goes_into_the_chart_placeholder_with_table_data(specimen):
    plan, _, tables, prs, report = specimen
    index = report.layouts.index("matn:chart:hero")
    frame = by_name(prs.slides[index], "chart")
    assert frame.is_placeholder and frame.placeholder_format.type == PP_PLACEHOLDER.CHART
    plot = frame.chart.plots[0]
    assert list(plot.categories) == ["Region A", "Region B", "Region C", "Region D"]
    assert [(s.name, list(s.values)) for s in plot.series] == [("2024", [12.5, 9.0, 6.5, 4.0]),
                                                              ("2025", [18.0, 14.5, 8.0, 7.5])]
    assert by_name(prs.slides[index], "source").text_frame.text == "p. 8, 10 (table)"
    assert frame.chart.value_axis.has_major_gridlines is False and plot.has_data_labels


def test_all_text_stays_editable_and_there_are_no_pictures(specimen):
    _, _, _, prs, _ = specimen
    for slide in prs.slides:
        for shape in slide.shapes:
            assert shape.is_placeholder, shape.name  # every shape comes from the template's layout
            assert shape.shape_type in {MSO_SHAPE_TYPE.PLACEHOLDER, MSO_SHAPE_TYPE.CHART}, shape.name


def test_overflow_tries_the_next_variant_then_splits():
    fact = sample_fact("Sample: a.", "Sample text: a.", 1)
    lead = "Sample lead that is forty characters lon"  # 40 characters: wraps in the two-col title slot
    plan = DeckPlan(doc_id=SPECIMEN_DOC_ID, slides=(
        Slide(slide_type=SlideType.FINDING, title="Sample fallback",
              items=(item(f"{lead}: sample rest.", fact), item("Short: sample.", fact)), notes=None),))
    narrow = GALLERY_DIR / "ion-boardroom" / "template.pptx"
    _, report = build_presentation(plan, (fact,), (), narrow, strict=True)
    assert report.layouts == ("matn:finding:split-60-40",)  # two-col was preferred for 2 items, then overflowed

    numbers = tuple(sample_fact(f"Sample: n{i}.", f"Sample text: {i},000 sample units were counted.", i % 20,
                                number=(f"Sample count {i}", f"{i},000", "units")) for i in range(1, 31))
    plan = DeckPlan(doc_id=SPECIMEN_DOC_ID, slides=(
        Slide(slide_type=SlideType.KPI, title="Sample numbers", kpi_fact_ids=(numbers[0].fact_id, numbers[1].fact_id),
              notes=None),
        Slide(slide_type=SlideType.EVIDENCE_APPENDIX, title="Sample receipts", notes=None)))
    prs, report = build_presentation(plan, numbers[:2], (), DEFAULT, strict=True)
    assert report.layouts == ("matn:kpi:big-number", "matn:evidence_appendix:default")
    plan = plan.model_copy(update={"slides": tuple(
        Slide(slide_type=SlideType.LIMITATIONS, title="Sample caveat", items=(item("Sample.", n),), notes=None)
        for n in numbers) + plan.slides[1:]})
    prs, report = build_presentation(plan, numbers, (), DEFAULT, strict=True)
    parts = [i for i, layout in enumerate(report.layouts) if layout == "matn:evidence_appendix:default"]
    assert len(parts) >= 2
    titles = [by_name(prs.slides[i], "title").text_frame.text for i in parts]
    assert titles == [f"Sample receipts ({k}/{len(parts)})" for k in range(1, len(parts) + 1)]
    lines = [p.text for i in parts for p in by_name(prs.slides[i], "body").text_frame.paragraphs]
    assert len(lines) == len(numbers)  # every number once, none cut
    assert all(f"“{n.evidence[0].quote}”" in line for n, line in zip(numbers, lines))


def test_the_same_plan_keeps_identical_facts_values_and_sources_in_every_template():
    plan, facts, tables = specimen_inputs()

    def content(template: Path):
        prs, _ = build_presentation(plan, facts, tables, template, strict=True)
        notes, values, pages, appendix = set(), [], set(), []
        for slide in prs.slides:
            notes |= {line for line in slide.notes_slide.notes_text_frame.text.splitlines() if "“" in line}
            for shape in slide.placeholders:
                if shape.name.startswith(("kpi_value_", "kpi_label_")):
                    values.append(shape.text_frame.text)
                elif shape.name == "source":
                    pages |= set(re.findall(r"\d+(?: \(table\))?", shape.text_frame.text))
                elif shape.name == "chart":
                    values.append(str([list(s.values) for s in shape.chart.plots[0].series]))
            if slide.slide_layout.name == "matn:evidence_appendix:default":
                appendix += [p.text for p in by_name(slide, "body").text_frame.paragraphs]
        return notes, values, pages, appendix

    expected = content(DEFAULT)
    assert all(expected)
    for template in gallery():
        assert content(template.path) == expected, template.id


def test_rejected_facts_unknown_tables_and_invalid_templates_stop_the_render(tmp_path):
    rejected = sample_fact("Sample: rejected.", "Sample text: rejected.", 1, status=FactStatus.REJECTED)
    plan = DeckPlan(doc_id=SPECIMEN_DOC_ID, slides=(
        Slide(slide_type=SlideType.LIMITATIONS, title="Sample", items=(item("Sample.", rejected),), notes=None),))
    with pytest.raises(DeckRenderError, match="REJECTED_FACT_CITED"):
        build_presentation(plan, (rejected,), (), DEFAULT)
    broken = sample_table([["Region", "Value"], ["Region A", "about 12"]], 9)
    fact = sample_fact("Sample: a.", "Sample text: a.", 1)
    chart = Slide(slide_type=SlideType.CHART, title="Sample", items=(item("Sample.", fact),), notes=None,
                  chart=ChartSpec(table_id=broken.table_id, x_column=0, y_columns=(1,), chart_type=ChartType.BAR))
    with pytest.raises(DeckRenderError, match="UNKNOWN_TABLE_ID"):
        build_presentation(DeckPlan(doc_id=SPECIMEN_DOC_ID, slides=(chart,)), (fact,), (), DEFAULT)
    with pytest.raises(DeckRenderError, match="CHART_CELL_NOT_NUMERIC"):
        build_presentation(DeckPlan(doc_id=SPECIMEN_DOC_ID, slides=(chart,)), (fact,), (broken,), DEFAULT)
    with pytest.raises(TemplateInvalidError, match="TEMPLATE_INVALID"):
        build_presentation(plan, (fact,), (), tmp_path / "missing.pptx")
