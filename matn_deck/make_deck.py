"""catalog -> deck.pptx -> deck.pdf -> thumbnails + contact sheet -> deck_qa.json/.html, with one re-layout.

Slides that fail a layout gate (measured overflow, PDF overflow, minimum font, density) are re-laid out once with
their chosen layout excluded (the next-best candidate); whatever still fails is flagged in deck_qa.json. Content is
never dropped.
"""
from __future__ import annotations

import json
from pathlib import Path

from .catalog import EvidenceCatalog
from .deck_qa import run_qa, write_report
from .deck_v2 import DECK_SAFETY, build_deck
from .export_v2 import contact_sheet, export_pdf, thumbnails
from .storyboard_v2 import Controls, Storyboard

LAYOUT_GATES = {"overflow_measured", "overflow_pdf", "min_font", "density"}


def make_deck(catalog: EvidenceCatalog, template: Path, out_dir: Path, *, controls: Controls = Controls(),
              fonts: str = "office", safety: float = DECK_SAFETY, pdf: bool = True, label: str = "",
              storyboard: Storyboard | None = None) -> dict:
    out_dir = Path(out_dir)
    exclude: dict[int, set[str]] = {}
    history = []

    def attempt(number: int) -> tuple:
        build = build_deck(catalog, template, out_dir, controls=controls, fonts=fonts, safety=safety,
                           exclude=exclude, storyboard=storyboard)
        pdf_path = export_pdf(build.pptx, out_dir / "deck.pdf") if pdf else None
        qa = run_qa(out_dir, pdf=pdf_path)
        failing = {int(k): v for k, v in qa["failing_slides"].items() if set(v) & LAYOUT_GATES}
        history.append({"attempt": number, "status": qa["status"], "layout_failures": sorted(failing),
                        "excluded": {str(k): sorted(v) for k, v in exclude.items()}})
        return build, qa, failing

    build, qa, failing = attempt(1)
    if failing:
        first = dict(exclude)
        for record in build.records:
            if record.slide in failing:
                exclude.setdefault(record.spec, set()).add(record.layout)
        build, qa, second = attempt(2)
        if len(second) > len(failing) or (second and len(second) == len(failing)):
            exclude.clear()
            exclude.update(first)
            build, qa, _ = attempt(3)  # the re-layout did not help: keep the first layout and flag it
            history[-1]["kept"] = "first layout (re-layout was not better)"
    qa["relayout"] = history
    qa["flagged_slides"] = sorted(int(k) for k, v in qa["failing_slides"].items())
    thumbs = thumbnails(out_dir / "deck.pdf", out_dir / "thumbs") if pdf else []
    if thumbs:
        kinds = [r.kind for r in build.records]
        contact_sheet(thumbs, out_dir / "contact-sheet.png",
                      title=f"{label or catalog.plan.topic} · {qa['status']} · fonts {fonts}",
                      labels=[f"{i} · {k}" for i, k in enumerate(kinds, start=1)])
    (out_dir / "deck_qa.json").write_text(json.dumps(qa, indent=1, ensure_ascii=False, sort_keys=True),
                                         encoding="utf-8")
    write_report(out_dir, qa, thumbs)
    return qa
