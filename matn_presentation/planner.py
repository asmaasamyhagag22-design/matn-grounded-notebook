from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


DEMO_VERIFIED_RISK_CLAIMS = {"src-src-010"}


def _bullet(text: str, *claim_ids: str) -> dict[str, Any]:
    return {"text": text, "claim_ids": list(claim_ids)}


def _citations(bullets: list[dict[str, Any]], claim_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_page_set: dict[tuple[int, ...], list[str]] = {}
    ordered_ids: list[str] = []
    for bullet in bullets:
        for claim_id in bullet["claim_ids"]:
            if claim_id not in ordered_ids:
                ordered_ids.append(claim_id)
    for claim_id in ordered_ids:
        pages = tuple(sorted({int(item["pdf_page"]) for item in claim_map[claim_id]["evidence"]}))
        by_page_set.setdefault(pages, []).append(claim_id)
    return [{"claim_ids": ids, "pdf_pages": list(pages)} for pages, ids in by_page_set.items()]


def _slide(
    number: int,
    title: str,
    purpose: str,
    layout: str,
    bullets: list[dict[str, Any]],
    claim_map: dict[str, dict[str, Any]],
    *,
    visual_asset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "slide_id": f"s{number:02d}",
        "slide_number": number,
        "title": title,
        "purpose": purpose,
        "layout": layout,
        "bullets": bullets,
        "citations": _citations(bullets, claim_map),
        "visual_asset": visual_asset,
        "speaker_notes": None,
        "validation_status": "validated",
    }


def build_demo_deck_plan(
    claims: list[dict[str, Any]],
    semantic_plan: dict[str, Any],
    *,
    figure_asset_path: str,
) -> dict[str, Any]:
    claim_map = {claim["claim_id"]: claim for claim in claims}
    specs = [
        (2, "Purpose and research environments", "Define the executor and its two research settings.", "title_and_bullets", [
            _bullet("The executor turns natural-language ideas into benchmark results.", "src-src-001"),
            _bullet("Each environment fixes a problem, codebase, benchmark, data, and metrics.", "src-src-005"),
            _bullet("Problems remain open-ended while retaining established baselines and measurements.", "src-src-006"),
            _bullet("The study provides both pre-training and post-training environments.", "src-src-007"),
        ]),
        (3, "Pre-training environment", "Explain the nanoGPT objective, proxy reward, budget, and validation control.", "title_and_bullets", [
            _bullet("The nanoGPT task trains a 124M GPT-2 model on FineWeb.", "src-src-008"),
            _bullet("Success reaches 3.28 validation loss on eight H100 GPUs.", "src-src-008"),
            _bullet("Search uses a proxy reward equal to 1 / loss.", "src-src-010"),
            _bullet("A fixed 25-minute wall-clock budget keeps runs comparable.", "src-src-011"),
            _bullet("Final validation predicts one token at a time with frozen hyperparameters.", "src-src-013", "src-src-014"),
        ]),
        (4, "Post-training environment", "Explain the GRPO baseline, metric, controls, and search scope.", "title_and_bullets", [
            _bullet("The GRPO baseline fine-tunes Qwen2.5-Math-1.5B on MATH.", "src-src-015"),
            _bullet("The ideator searches for post-training algorithms beyond the baseline.", "src-src-016"),
            _bullet("The metric is maximum MATH validation accuracy during training.", "src-src-017"),
            _bullet("Validation code stays separate and inaccessible to the executor.", "src-src-018"),
            _bullet("The ideation scope includes tuning, architectures, and training algorithms.", "src-src-019"),
        ]),
        (5, "Executor architecture", "Show the supported responsibilities of the three executor components.", "three_columns", [
            _bullet("The API maps idea batches to benchmark performance.", "src-src-020"),
            _bullet("Implementer generates and applies code diffs.", "src-src-021"),
            _bullet("Scheduler allocates resources and prepares jobs.", "src-src-021"),
            _bullet("Worker runs GPU experiments and uploads results.", "src-src-021"),
        ]),
        (6, "Implementer workflow", "Trace candidate generation, bounded repair, and publication.", "process", [
            _bullet("The Implementer runs on a high-IO CPU machine.", "src-src-022"),
            _bullet("Users submit ideas as a batch.", "src-src-023"),
            _bullet("Parallel LLM calls produce ten candidate diffs for each baseline.", "src-src-024", "src-src-025"),
            _bullet("Failed patches return logs for at most two revisions.", "src-src-026", "src-src-027"),
            _bullet("The first patchable diff is packaged and uploaded.", "src-src-028", "src-src-029"),
        ]),
        (7, "Scheduler and Worker", "Explain resource assignment, execution, success, and failure behavior.", "two_columns", [
            _bullet("Scheduler checks new codebases at a set clock frequency.", "src-src-030"),
            _bullet("Unexecuted codebases receive resource-aware job configurations.", "src-src-031"),
            _bullet("Available GPUs start Worker experiments.", "src-src-032"),
            _bullet("Successful runs upload metrics and complete metadata to wandb.", "src-src-033"),
            _bullet("Failed runs halt, while the ideator can retrieve full logs.", "src-src-034", "src-src-035"),
        ]),
        (8, "Evaluation and failure controls", "Collect the controls that prevent misleading or incomplete execution results.", "title_and_bullets", [
            _bullet("Plots report loss or proxy reward; training time covers the top solution.", "src-src-012"),
            _bullet("Frozen settings and one-token prediction reduce reward-hacking opportunities.", "src-src-013"),
            _bullet("GRPO validation code remains outside executor access.", "src-src-018"),
            _bullet("Patch failures trigger bounded revision before the first valid diff continues.", "src-src-026", "src-src-027", "src-src-028"),
            _bullet("Execution failures stop the Worker instead of reporting success.", "src-src-034"),
        ]),
        (9, "Figure 2 findings", "Present only the verified figure caption and the source crop.", "image_and_caption", [
            _bullet("Figure 2 compares self-execution with GPT-5 execution.", "src-src-037"),
            _bullet("GRPO baseline accuracy is 0.480.", "src-src-038"),
            _bullet("nanoGPT baseline loss is 3.255.", "src-src-038"),
            _bullet("Most models show high completion, especially under self-execution.", "src-src-039"),
        ]),
        (10, "Key takeaways and source disclosure", "Close with the grounded workflow and disclose the exact source scope.", "sources", [
            _bullet("Execution grounds idea generation in observed benchmark performance.", "src-src-001", "src-src-020"),
            _bullet("Broad ideation remains bounded by fixed evaluation controls.", "src-src-019", "src-src-013", "src-src-018"),
            _bullet("Figure 2 reports high completion for most evaluated models.", "src-src-039"),
        ]),
    ]

    title_slide = _slide(
        1,
        "Automated Idea Executor",
        "Introduce the paper section, source scope, and provenance standard.",
        "title",
        [],
        claim_map,
    )
    slides = [title_slide]
    for number, title, purpose, layout, bullets in specs:
        asset = None
        if number == 9:
            asset = {
                "asset_id": "figure-2-page-3",
                "path": figure_asset_path.replace("\\", "/"),
                "source_pdf_page": 3,
                "crop_pdf_points": [305.0, 315.0, 551.0, 592.0],
                "description": "Verified crop of Figure 2 with caption, axes, labels, and legends",
                "provenance_mode": "source_pdf_crop_no_ocr",
            }
        slides.append(_slide(number, title, purpose, layout, bullets, claim_map, visual_asset=asset))

    used = {claim_id for slide in slides for bullet in slide["bullets"] for claim_id in bullet["claim_ids"]}
    reasons = {
        "src-src-002": "Table title omitted because the deck does not present Table 1 results.",
        "src-src-003": "Duplicate task description from table-adjacent extraction; safer narrative claim retained.",
        "src-src-004": "Duplicate task description from table-adjacent extraction; source-text claim retained.",
        "src-src-009": "Vague transition sentence adds no independent presentation fact.",
        "src-src-036": "Raw picture-region transcription is forbidden presentation content.",
    }
    omitted = [
        {"claim_id": claim["claim_id"], "reason": reasons.get(claim["claim_id"], "Not needed for the ten-slide narrative.")}
        for claim in claims
        if claim["claim_id"] not in used
    ]
    stable_material = semantic_plan["document_id"] + semantic_plan["source_selection_id"] + "phase04a-en-v1"
    deck_id = "deck-" + hashlib.sha256(stable_material.encode("utf-8")).hexdigest()[:16]
    return {
        "schema_version": 1,
        "deck_id": deck_id,
        "deck_title": "Automated Idea Executor",
        "source_document_id": semantic_plan["document_id"],
        "source_filename": "2601.14525v1.pdf",
        "language": "en",
        "generation_mode": "validated_demo",
        "source_scope": {"section": "2", "pdf_pages": [2, 3], "page_numbering": "physical_1_based"},
        "validation_profile": {
            "accepted_risk_claim_ids": sorted(DEMO_VERIFIED_RISK_CLAIMS),
            "blocked_claim_ids": ["src-src-036"],
            "human_verification_note": "The printed reciprocal 1/loss and Figure 2 caption were visually checked on PDF pages 2 and 3.",
        },
        "provenance": {
            "claims_artifact": "demo/phase04a/claims.json",
            "semantic_plan_artifact": "demo/phase04a/semantic-plan.json",
            "cache_status": "validated_cached_demo",
            "provenance_mode": "validated_claims_with_explicit_phase04a_corrections",
            "model_generation_calls": 0,
            "inference_endpoint": None,
            "cloud_fallback_enabled": False,
        },
        "slides": slides,
        "omitted_claims": omitted,
    }
