from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

from .domain import (
    Block,
    BlockStyle,
    ChartSpec,
    DeckPlan,
    EvidenceRef,
    ExtractorInfo,
    Fact,
    KeyNumber,
    NumberFactValue,
    PageRange,
    PromptVersion,
    RunManifest,
    SamplingParameters,
    Section,
    SectionCoverage,
    SectionSummary,
    Slide,
    SlideItem,
    Summary,
    SummarySentence,
    Table,
    TableCell,
)
from .drafts import (
    ChartSpecDraft,
    DeckPlanDraft,
    EvidenceRefDraft,
    FactDraft,
    NumberFactValueDraft,
    SectionSummaryDraft,
    SlideDraft,
    SlideItemDraft,
    SummarySentenceDraft,
)


_MODELS = (
    BlockStyle,
    ExtractorInfo,
    Block,
    TableCell,
    Table,
    PageRange,
    Section,
    SectionCoverage,
    EvidenceRef,
    NumberFactValue,
    Fact,
    SummarySentence,
    SectionSummary,
    KeyNumber,
    Summary,
    SlideItem,
    ChartSpec,
    Slide,
    DeckPlan,
    PromptVersion,
    SamplingParameters,
    RunManifest,
    EvidenceRefDraft,
    NumberFactValueDraft,
    FactDraft,
    SummarySentenceDraft,
    SectionSummaryDraft,
    SlideItemDraft,
    ChartSpecDraft,
    SlideDraft,
    DeckPlanDraft,
)


def _filename(model: type[BaseModel]) -> str:
    stem = re.sub(r"(?<!^)(?=[A-Z])", "-", model.__name__).lower()
    return f"{stem}.schema.json"


CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    _filename(model): model for model in _MODELS
}


def render_schema_files() -> dict[str, str]:
    return {
        filename: json.dumps(
            model.model_json_schema(mode="validation"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
        for filename, model in CONTRACT_MODELS.items()
    }


def export_schema_files(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in render_schema_files().items():
        (output_dir / filename).write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    repository_root = Path(__file__).resolve().parents[1]
    export_schema_files(repository_root / "schemas" / "contracts")
