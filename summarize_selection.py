"""CLI for Matn Phase 03 local grounded summarization."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from matn_summarization.io import Phase03Error
from matn_summarization.pipeline import run_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--document-store", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--language", choices=("en", "ar"), required=True)
    parser.add_argument("--audience", required=True)
    parser.add_argument("--length", choices=("short", "medium", "long"), default="medium")
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--strategy", choices=("direct", "hierarchical"), default="hierarchical")
    parser.add_argument("--num-predict", type=int, default=1536)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--bypass-cache", action="store_true", help="Compatibility alias for --bypass-map-cache")
    parser.add_argument("--bypass-result-cache", action="store_true", help="Bypass any whole-result cache (recorded even though no result cache is currently implemented)")
    parser.add_argument("--bypass-map-cache", action="store_true", help="Bypass the claim-map cache")
    parser.add_argument("--semantic-plan", type=Path, help="Frozen canonical English semantic-plan.json; required for Arabic")
    parser.add_argument("--rejected-render", type=Path, help="Rejected Arabic render artifact to revalidate against the same frozen plan before one constrained repair")
    parser.add_argument("--translation-memory", type=Path, help="Accepted Arabic summary.json whose exact matching claims may be reused and revalidated")
    parser.add_argument("--disable-translation-memory", action="store_true")
    parser.add_argument("--disable-rejected-render-reuse", action="store_true")
    parser.add_argument("--require-model-rendering", action="store_true", help="Fail unless Arabic rendering makes at least one actual model call")
    parser.add_argument("--require-model-stage", action="append", choices=("map", "render", "synthesis", "repair"), default=[], help="Fail if the requested model stage makes zero model calls")
    parser.add_argument("--require-cold", action="store_true", help="Require uncached, unreplayed model generation and fail on fallback")
    parser.add_argument("--visually-verified-chunk", action="append", default=[], help="Selected chunk visually checked against the PDF")
    parser.add_argument("--model-map-enrichment", action="store_true", help="Optional local-model enrichment after lossless deterministic extraction")
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_summary(
            project_root=Path(__file__).resolve().parent,
            selection_path=args.selection, store_path=args.document_store, pdf_path=args.pdf,
            out_path=args.out, language=args.language, audience=args.audience, length=args.length,
            glossary_path=args.glossary, model=args.model, base_url=args.base_url,
            strategy=args.strategy, num_predict=args.num_predict, cache_path=args.cache,
            bypass_cache=args.bypass_cache,
            bypass_result_cache=args.bypass_result_cache,
            bypass_map_cache=args.bypass_map_cache or args.bypass_cache,
            semantic_plan_path=args.semantic_plan,
            rejected_render_path=args.rejected_render,
            translation_memory_path=args.translation_memory,
            disable_translation_memory=args.disable_translation_memory,
            disable_rejected_render_reuse=args.disable_rejected_render_reuse,
            require_model_rendering=args.require_model_rendering,
            required_model_stages=set(args.require_model_stage),
            require_cold=args.require_cold,
            visually_verified_chunk_ids=set(args.visually_verified_chunk),
            model_map_enrichment=args.model_map_enrichment,
        )
        metadata = result["metadata"]
        print(json.dumps({
            "status": "completed", "run_id": metadata["run_id"], "strategy": metadata["strategy"],
            "map_batches": metadata["map_batches"], "claims": metadata["claims_after_validation"],
            "cache_hits": metadata["cache"]["hits"], "cache_misses": metadata["cache"]["misses"],
            "generation_mode": metadata["generation_mode"], "provenance": metadata["provenance_classification"],
            "model_calls_total": metadata["model_calls_total"],
            "output": str(args.out),
        }, ensure_ascii=False))
        return 0
    except Phase03Error as exc:
        print(f"Phase 03 failed safely: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Phase 03 failed safely: UNEXPECTED:{type(exc).__name__}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
