from __future__ import annotations

import json
from pathlib import Path

from pptx import Presentation

from matn_presentation.assets import render_figure_2
from matn_presentation.planner import build_demo_deck_plan
from matn_presentation.renderer import render_presentation, validate_rendered_pptx
from matn_presentation.validation import validate_deck_plan


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "demo" / "phase04a"


def test_renderer_creates_reopenable_bounded_presentation(tmp_path):
    claims = json.loads((RUN / "claims.json").read_text(encoding="utf-8"))["claims"]
    semantic = json.loads((RUN / "semantic-plan.json").read_text(encoding="utf-8"))
    figure = tmp_path / "figure-2.png"
    render_figure_2(ROOT / "documents" / "2601.14525v1.pdf", figure)
    plan = build_demo_deck_plan(claims, semantic, figure_asset_path=str(figure))
    validate_deck_plan(plan, claims, project_root=ROOT)
    output = tmp_path / "demo.pptx"
    render_presentation(plan, output, project_root=ROOT)
    result = validate_rendered_pptx(output, expected_slides=10)
    reopened = Presentation(output)
    assert result == {"status": "pass", "slide_count": 10, "overlaps": 0, "out_of_bounds": 0}
    assert len(reopened.slides) == 10
    assert reopened.core_properties.title == "Automated Idea Executor"
    assert output.stat().st_size > 100_000
