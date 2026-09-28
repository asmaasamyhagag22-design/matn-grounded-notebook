"""Phase 02 document store, structural indexing, and scoped selection.

The implementation is deliberately deterministic and local.  Structured
Markdown supplies candidate blocks and headings, while the raw extraction and
the original PDF remain independent evidence.  No LLM or OCR is used here.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

import pymupdf

from inspect_pdf import InspectionError, PageSelection, StagedOutput, sha256_file


STORE_SCHEMA_VERSION = 1
BUILDER_VERSION = "phase02-1"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[*_`]+", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.casefold()


def display_heading(value: str) -> str:
    value = re.sub(r"^#{1,6}\s+", "", value.strip())
    value = re.sub(r"^\*\*(.*?)\*\*\s*$", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()


def stable_id(prefix: str, *parts: object, length: int = 16) -> str:
    encoded = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:length]}"


def _semantic_heading(title: str, markdown_level: int) -> tuple[int, str | None]:
    clean = display_heading(title)
    numbered = re.match(r"^(\d+(?:\.\d+)*)\.?(?:\s+|$)", clean)
    if numbered:
        number = numbered.group(1)
        return number.count(".") + 1, "sec-" + number.replace(".", "-")
    appendix_child = re.match(r"^([A-Z])\.(\d+(?:\.\d+)*)\.?(?:\s+|$)", clean)
    if appendix_child:
        suffix = f"{appendix_child.group(1)}-{appendix_child.group(2)}"
        return appendix_child.group(2).count(".") + 2, "sec-" + suffix.casefold().replace(".", "-")
    appendix = re.match(r"^([A-Z])\.(?:\s+|$)", clean)
    if appendix:
        return 1, f"sec-appendix-{appendix.group(1).casefold()}"
    named = {
        "abstract": "sec-abstract",
        "references": "sec-references",
        "acknowledgment": "sec-acknowledgment",
        "acknowledgements": "sec-acknowledgements",
        "appendix": "sec-appendix",
    }
    normalized = normalize_text(clean)
    if normalized in named:
        return 1, named[normalized]
    return markdown_level, None


def _markdown_blocks(text: str) -> list[tuple[int, int, str]]:
    """Split without deleting bytes; whitespace gaps remain recoverable by offsets."""
    boundaries = list(re.finditer(r"\r?\n[ \t]*\r?\n", text))
    regions: list[tuple[int, int]] = []
    cursor = 0
    for boundary in boundaries:
        regions.append((cursor, boundary.start()))
        cursor = boundary.end()
    regions.append((cursor, len(text)))
    blocks: list[tuple[int, int, str]] = []
    for region_start, region_end in regions:
        region = text[region_start:region_end]
        leading = len(region) - len(region.lstrip())
        trailing_end = len(region.rstrip())
        if leading == trailing_end:
            continue
        start = region_start + leading
        end = region_start + trailing_end
        blocks.append((start, end, text[start:end]))
    return blocks


def _first_heading(block_text: str) -> tuple[int, str, int, int] | None:
    match = re.match(r"\s*(#{1,6})\s+([^\r\n]+)", block_text)
    if match is None:
        return None
    return len(match.group(1)), display_heading(match.group(2)), match.start(2), match.end(2)


def _content_flags(
    text: str,
    *,
    image_count: int | None,
    drawing_count: int | None,
    disagreement: bool,
) -> list[str]:
    flags: list[str] = []
    if isinstance(image_count, int) and image_count > 0:
        flags.append("contains_picture_region")
    if re.search(r"(?m)^\s*\|.*\|\s*$", text):
        flags.append("contains_table")
        if text.count("|") > 40:
            flags.extend(["complex_table_suspected", "needs_human_review"])
    if re.search(r"\$[^$]+\$|\\(?:frac|sum|mathbb|mathbf)|[∑∫√≈≤≥]", text):
        flags.append("equation_or_symbol_risk")
    if disagreement:
        flags.extend(["structured_raw_disagreement", "needs_human_review"])
    if isinstance(drawing_count, int) and drawing_count > 40:
        flags.append("extraction_order_risk")
    return sorted(set(flags))


def _candidate_lines(page_texts: dict[int, str]) -> list[dict[str, Any]]:
    occurrences: dict[tuple[str, str], set[int]] = defaultdict(set)
    examples: dict[tuple[str, str], str] = {}
    for pdf_page, text in page_texts.items():
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for position, subset in (("header", lines[:3]), ("footer", lines[-3:])):
            for line in subset:
                normalized = normalize_text(display_heading(line))
                if not normalized or len(normalized) > 160:
                    continue
                key = (position, normalized)
                occurrences[key].add(pdf_page)
                examples.setdefault(key, display_heading(line))
    threshold = max(3, (len(page_texts) + 1) // 2)
    result = []
    for (position, normalized), pages in sorted(occurrences.items()):
        if len(pages) < threshold:
            continue
        result.append(
            {
                "candidate_id": stable_id("hf", position, normalized),
                "text": examples[(position, normalized)],
                "normalized_text": normalized,
                "position": position,
                "pdf_pages": sorted(pages),
                "evidence": {
                    "method": "repeated_edge_line",
                    "page_occurrences": len(pages),
                    "page_population": len(page_texts),
                    "edge_line_window": 3,
                },
                "status": "proposed",
                "warnings": [
                    "Repetition at a page edge is only a candidate; semantic repetition can be legitimate."
                ],
            }
        )
    return result


def _load_manual(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"schema_version": 1, "headings": [], "header_footer": [], "printed_pages": []}
    data = read_json(path)
    if data.get("schema_version") != 1:
        raise ValueError("manual corrections must use schema_version 1")
    for key in ("headings", "header_footer", "printed_pages"):
        data.setdefault(key, [])
    return data


def _apply_manual_headings(headings: list[dict[str, Any]], manual: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for rule in manual["headings"]:
        matches = [
            item
            for item in headings
            if item["normalized_text"] == normalize_text(rule["normalized_title"])
            and (rule.get("pdf_page") is None or item["pdf_page"] == rule["pdf_page"])
        ]
        if len(matches) != 1:
            warnings.append(
                f"Manual heading rule matched {len(matches)} candidates: {rule['normalized_title']!r}."
            )
            continue
        item = matches[0]
        action = rule["action"]
        if action not in {"confirm", "reject"}:
            raise ValueError("manual heading action must be confirm or reject")
        item["status"] = "confirmed" if action == "confirm" else "rejected"
        item["evidence_status"] = "manual_confirmed" if action == "confirm" else "manual_rejected"
        item["source_method"].append("manual_correction")
        if "level" in rule:
            item["level"] = int(rule["level"])
        if rule.get("section_id"):
            item["requested_section_id"] = rule["section_id"]
    return warnings


def _apply_manual_hf(candidates: list[dict[str, Any]], manual: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for rule in manual["header_footer"]:
        matches = [
            item
            for item in candidates
            if item["normalized_text"] == normalize_text(rule["normalized_text"])
            and item["position"] == rule["position"]
        ]
        if len(matches) != 1:
            warnings.append(
                f"Manual header/footer rule matched {len(matches)} candidates: {rule['normalized_text']!r}."
            )
            continue
        action = rule["action"]
        if action not in {"confirm", "reject"}:
            raise ValueError("manual header/footer action must be confirm or reject")
        matches[0]["status"] = "confirmed" if action == "confirm" else "rejected"
    return warnings


def _manifest_pages(manifest: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(item["pdf_page"]): item for item in manifest["pages"]}


def _validate_inputs(
    pdf_path: Path, raw_dir: Path, structured_dir: Path
) -> tuple[dict[str, Any], dict[str, Any], list[int]]:
    raw = read_json(raw_dir / "manifest.json")
    structured = read_json(structured_dir / "manifest.json")
    if raw["extractor"]["name"] != "PyMuPDF Page.get_text":
        raise ValueError("--raw-run is not a raw PyMuPDF extraction")
    if structured["extractor"]["name"] != "PyMuPDF4LLM to_markdown":
        raise ValueError("--structured-run is not a structured extraction")
    if raw["source"] != structured["source"]:
        raise ValueError("raw and structured manifests do not describe the same source")
    if sha256_file(pdf_path) != raw["source"]["sha256"]:
        raise ValueError("PDF SHA-256 does not match the extraction manifests")
    raw_pages = list(raw["requested_pdf_pages"]["pdf_pages"])
    structured_pages = list(structured["requested_pdf_pages"]["pdf_pages"])
    if raw_pages != structured_pages:
        raise ValueError("raw and structured runs must contain the same pages in the same order")
    return raw, structured, raw_pages


def validate_document_store(store: dict[str, Any], page_texts: dict[int, str]) -> None:
    """Reject internally inconsistent stores before atomic publication."""
    if store.get("schema_version") != STORE_SCHEMA_VERSION or store.get("store_status") != "completed":
        raise ValueError("document store is not a completed supported schema version")
    page_numbers = {item["pdf_page"] for item in store["pages"]}
    chunk_ids: set[str] = set()
    for chunk in store["chunks"]:
        if chunk["chunk_id"] in chunk_ids:
            raise ValueError("duplicate chunk ID")
        chunk_ids.add(chunk["chunk_id"])
        if chunk["pdf_page"] not in page_numbers:
            raise ValueError("chunk references a page outside store coverage")
        source = page_texts[chunk["pdf_page"]]
        if source[chunk["start_offset"] : chunk["end_offset"]] != chunk["text"]:
            raise ValueError("chunk offsets do not reproduce exact structured source text")
        if Path(chunk["source_text_path"]).is_absolute():
            raise ValueError("shareable store contains an absolute text path")
    for page in store["pages"]:
        if Path(page["raw_text_path"]).is_absolute() or Path(page["structured_text_path"]).is_absolute():
            raise ValueError("shareable store contains an absolute page path")
        if any(chunk_id not in chunk_ids for chunk_id in page["chunk_ids"]):
            raise ValueError("page references an unknown chunk")
    for section in store["sections"]:
        if not section["included_chunk_ids"]:
            raise ValueError("section contains no selectable chunk")
        if any(chunk_id not in chunk_ids for chunk_id in section["included_chunk_ids"]):
            raise ValueError("section references an unknown chunk")


def build_document_store(
    pdf_path: Path,
    raw_dir: Path,
    structured_dir: Path,
    output_dir: Path,
    *,
    manual_corrections: Path | None = None,
) -> dict[str, Any]:
    """Build and atomically publish a versioned document store."""
    raw, structured, pdf_pages = _validate_inputs(pdf_path, raw_dir, structured_dir)
    manual = _load_manual(manual_corrections)
    raw_records = _manifest_pages(raw)
    structured_records = _manifest_pages(structured)
    document_id = f"sha256-{raw['source']['sha256']}"
    run_identity = {
        "builder_version": BUILDER_VERSION,
        "raw_extraction_run_id": raw["extraction_run_id"],
        "structured_extraction_run_id": structured["extraction_run_id"],
        "raw_extractor": raw["extractor"],
        "structured_extractor": structured["extractor"],
        "settings": {
            "chunking": "structured_markdown_blank_line_blocks",
            "heading_detection": "outline_then_markdown_then_manual",
            "ocr": False,
            "automatic_raw_structured_fallback": False,
        },
    }
    index_run_id = stable_id("index", document_id, json.dumps(run_identity, sort_keys=True))

    page_texts: dict[int, str] = {}
    raw_texts: dict[int, str] = {}
    pages: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    headings: list[dict[str, Any]] = []
    order = 0

    with pymupdf.open(pdf_path) as document:
        outline = document.get_toc(simple=False)
        outline_entries = [
            {
                "level": int(entry[0]),
                "title": str(entry[1]),
                "normalized_title": normalize_text(str(entry[1])),
                "pdf_page": int(entry[2]),
            }
            for entry in outline
            if len(entry) >= 3 and int(entry[2]) > 0
        ]

        printed_overrides = {
            int(item["pdf_page"]): item["printed_page"] for item in manual["printed_pages"]
        }
        for pdf_page in pdf_pages:
            raw_record = raw_records[pdf_page]
            structured_record = structured_records[pdf_page]
            raw_text = (raw_dir / raw_record["text_path"]).read_text(encoding="utf-8")
            structured_text = (structured_dir / structured_record["text_path"]).read_text(encoding="utf-8")
            raw_texts[pdf_page] = raw_text
            page_texts[pdf_page] = structured_text
            raw_norm = normalize_text(raw_text)
            structured_norm = normalize_text(structured_text)
            disagreement = bool(raw_norm and structured_norm and SequenceMatcher(None, raw_norm, structured_norm).ratio() < 0.65)
            signals = raw_record.get("signals", {})
            page_flags = _content_flags(
                structured_text,
                image_count=signals.get("image_count"),
                drawing_count=signals.get("drawing_count"),
                disagreement=disagreement,
            )
            page_chunk_ids: list[str] = []
            for start, end, text in _markdown_blocks(structured_text):
                chunk_id = stable_id(
                    "chk",
                    document_id,
                    BUILDER_VERSION,
                    "structured",
                    pdf_page,
                    start,
                    end,
                    hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
                heading = _first_heading(text)
                chunk_flags = _content_flags(
                    text,
                    image_count=signals.get("image_count"),
                    drawing_count=signals.get("drawing_count"),
                    disagreement=disagreement,
                )
                chunk = {
                    "chunk_id": chunk_id,
                    "order": order,
                    "pdf_page": pdf_page,
                    "source_type": "structured",
                    "source_text_path": f"text/structured/page_{pdf_page:04d}.md",
                    "start_offset": start,
                    "end_offset": end,
                    "block_kind": "heading_block" if heading else "layout_block",
                    "text": text,
                    "content_risk_flags": chunk_flags,
                    "warnings": [
                        "A layout block is not asserted to be a linguistically complete paragraph."
                    ],
                }
                chunks.append(chunk)
                page_chunk_ids.append(chunk_id)
                order += 1
                if heading:
                    markdown_level, title, relative_start, relative_end = heading
                    level, requested_id = _semantic_heading(title, markdown_level)
                    normalized = normalize_text(title)
                    outline_on_page = [
                        item for item in outline_entries if item["pdf_page"] == pdf_page
                    ]
                    outline_matches = [
                        item
                        for item in outline_on_page
                        if item["normalized_title"] == normalized and item["pdf_page"] == pdf_page
                    ]
                    if len(outline_matches) == 1:
                        evidence_status = "outline_and_heading_agree"
                        status = "confirmed"
                        methods = ["pdf_outline", "structured_markdown_heading"]
                        level = outline_matches[0]["level"]
                    elif outline_matches or outline_on_page:
                        evidence_status = "conflicting_evidence"
                        status = "proposed"
                        methods = ["pdf_outline", "structured_markdown_heading"]
                    else:
                        evidence_status = "heading_only"
                        status = "proposed"
                        methods = ["structured_markdown_heading"]
                    headings.append(
                        {
                            "heading_id": stable_id("hdg", chunk_id, normalized),
                            "text": title,
                            "normalized_text": normalized,
                            "level": level,
                            "pdf_page": pdf_page,
                            "chunk_id": chunk_id,
                            "start_offset": start + relative_start,
                            "end_offset": start + relative_end,
                            "source_method": methods,
                            "evidence": {
                                "markdown_level": markdown_level,
                                "outline_matches": outline_matches,
                                "outline_entries_on_page": outline_on_page,
                            },
                            "evidence_status": evidence_status,
                            "status": status,
                            "warnings": (
                                []
                                if len(outline_matches) == 1
                                else ["Outline and structured-heading evidence conflict; review is required."]
                                if outline_on_page
                                else ["Heading-only evidence requires explicit allowance or manual confirmation."]
                            ),
                            "requested_section_id": requested_id,
                        }
                    )

            pages.append(
                {
                    "pdf_page": pdf_page,
                    "page_label": structured_record.get("page_label"),
                    "printed_page": printed_overrides.get(pdf_page),
                    "raw_text_path": f"text/raw/page_{pdf_page:04d}.txt",
                    "structured_text_path": f"text/structured/page_{pdf_page:04d}.md",
                    "chunk_ids": page_chunk_ids,
                    "content_risk_flags": page_flags,
                    "warnings": sorted(set(raw_record.get("warnings", []) + structured_record.get("warnings", []))),
                }
            )

    # Preserve outline-only evidence even when Markdown did not style the title
    # as a heading.  Exact text in a page block supplies a usable anchor; an
    # unanchored bookmark remains proposed/conflicting rather than pretending
    # that the whole page is a precise section boundary.
    outline_warnings: list[str] = []
    for outline_entry in outline_entries:
        if any(
            item["pdf_page"] == outline_entry["pdf_page"]
            and item["normalized_text"] == outline_entry["normalized_title"]
            for item in headings
        ):
            continue
        page_chunks = [item for item in chunks if item["pdf_page"] == outline_entry["pdf_page"]]
        exact_chunks = [
            item
            for item in page_chunks
            if outline_entry["normalized_title"] in normalize_text(item["text"])
        ]
        anchor = exact_chunks[0] if exact_chunks else (page_chunks[0] if page_chunks else None)
        if anchor is None:
            outline_warnings.append(
                f"Outline entry {outline_entry['title']!r} is outside extracted coverage; no section anchor was created."
            )
            continue
        level, requested_id = _semantic_heading(outline_entry["title"], outline_entry["level"])
        exact = bool(exact_chunks)
        headings.append(
            {
                "heading_id": stable_id("hdg", anchor["chunk_id"], outline_entry["normalized_title"], "outline"),
                "text": outline_entry["title"],
                "normalized_text": outline_entry["normalized_title"],
                "level": level,
                "pdf_page": outline_entry["pdf_page"],
                "chunk_id": anchor["chunk_id"],
                "start_offset": anchor["start_offset"],
                "end_offset": anchor["start_offset"] + len(outline_entry["title"]),
                "source_method": ["pdf_outline", "structured_block_exact_title"] if exact else ["pdf_outline"],
                "evidence": {"outline_entry": outline_entry, "exact_title_in_block": exact},
                "evidence_status": "exact_outline_match" if exact else "conflicting_evidence",
                "status": "confirmed" if exact else "proposed",
                "warnings": [] if exact else ["Outline title was not found exactly in a structured page block."],
                "requested_section_id": requested_id,
                "index_eligible": exact,
            }
        )

    build_warnings = outline_warnings + _apply_manual_headings(headings, manual)
    hf_candidates = _candidate_lines(page_texts)
    build_warnings.extend(_apply_manual_hf(hf_candidates, manual))
    confirmed_hf = {item["normalized_text"] for item in hf_candidates if item["status"] == "confirmed"}
    for chunk in chunks:
        normalized_lines = [
            normalize_text(display_heading(line))
            for line in chunk["text"].splitlines()
            if line.strip()
        ]
        if any(line in confirmed_hf for line in normalized_lines):
            chunk["content_risk_flags"] = sorted(set(chunk["content_risk_flags"] + ["repeated_header_footer_candidate"]))
        chunk["selection_excluded_reason"] = (
            "confirmed_repetitive_header_footer"
            if normalized_lines and all(line in confirmed_hf for line in normalized_lines)
            else None
        )

    chunk_index = {item["chunk_id"]: item for item in chunks}
    active_headings = [
        item
        for item in headings
        if item["status"] != "rejected" and item.get("index_eligible", True)
    ]
    active_headings.sort(key=lambda item: chunk_index[item["chunk_id"]]["order"])
    id_counts: Counter[str] = Counter()
    sections: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for position, heading in enumerate(active_headings):
        while stack and stack[-1]["level"] >= heading["level"]:
            stack.pop()
        parent_id = stack[-1]["section_id"] if stack else None
        base_id = heading.get("requested_section_id") or stable_id("sec", heading["normalized_text"], length=12)
        id_counts[base_id] += 1
        section_id = base_id if id_counts[base_id] == 1 else f"{base_id}-{id_counts[base_id]}"
        start_order = chunk_index[heading["chunk_id"]]["order"]
        next_heading = next(
            (candidate for candidate in active_headings[position + 1 :] if candidate["level"] <= heading["level"]),
            None,
        )
        end_order = chunk_index[next_heading["chunk_id"]]["order"] if next_heading else len(chunks)
        included = [
            item
            for item in chunks
            if start_order <= item["order"] < end_order
            and item["selection_excluded_reason"] is None
        ]
        section = {
            "section_id": section_id,
            "heading_id": heading["heading_id"],
            "title": heading["text"],
            "normalized_title": heading["normalized_text"],
            "level": heading["level"],
            "parent_section_id": parent_id,
            "start_anchor": {
                "pdf_page": heading["pdf_page"],
                "chunk_id": heading["chunk_id"],
                "offset": heading["start_offset"],
            },
            "end_anchor_exclusive": (
                {
                    "pdf_page": next_heading["pdf_page"],
                    "chunk_id": next_heading["chunk_id"],
                    "offset": next_heading["start_offset"],
                }
                if next_heading
                else None
            ),
            "first_pdf_page": included[0]["pdf_page"],
            "last_pdf_page": included[-1]["pdf_page"],
            "included_chunk_ids": [item["chunk_id"] for item in included],
            "source_evidence": {
                "heading_evidence_status": heading["evidence_status"],
                "source_method": heading["source_method"],
            },
            "confirmation_status": heading["status"],
            "content_risk_flags": sorted({flag for item in included for flag in item["content_risk_flags"]}),
            "warnings": list(heading["warnings"]),
        }
        sections.append(section)
        stack.append(section)

    store = {
        "schema_version": STORE_SCHEMA_VERSION,
        "store_status": "completed",
        "document": {
            "document_id": document_id,
            "sha256": raw["source"]["sha256"],
            "size_bytes": raw["source"]["size_bytes"],
            "safe_file_name": Path(raw["source"]["file_name"]).name,
            "pdf_page_count": raw["source"]["page_count"],
        },
        "index_run": run_identity | {"index_run_id": index_run_id},
        "coverage": {
            "pdf_pages": pdf_pages,
            "is_complete_document": pdf_pages == list(range(1, raw["source"]["page_count"] + 1)),
        },
        "outline": {
            "present": bool(outline_entries),
            "entries": outline_entries,
        },
        "pages": pages,
        "chunks": chunks,
        "heading_candidates": headings,
        "sections": sections,
        "header_footer_candidates": hf_candidates,
        "warnings": build_warnings + ([] if outline_entries else ["PDF outline/bookmarks are absent."]),
    }

    validate_document_store(store, page_texts)

    with StagedOutput(output_dir, index_run_id) as staged:
        (staged.staging_path / "text" / "raw").mkdir(parents=True)
        (staged.staging_path / "text" / "structured").mkdir(parents=True)
        for pdf_page in pdf_pages:
            (staged.staging_path / f"text/raw/page_{pdf_page:04d}.txt").write_text(raw_texts[pdf_page], encoding="utf-8")
            (staged.staging_path / f"text/structured/page_{pdf_page:04d}.md").write_text(page_texts[pdf_page], encoding="utf-8")
        (staged.staging_path / "document-store.json").write_text(
            json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        staged.publish()
    return store


def _strip_confirmed_edges(text: str, confirmed: set[str]) -> tuple[str, list[dict[str, str]]]:
    kept: list[str] = []
    excluded: list[dict[str, str]] = []
    for line in text.splitlines(keepends=True):
        normalized = normalize_text(display_heading(line))
        if normalized in confirmed:
            excluded.append({"text": line.rstrip("\r\n"), "reason": "confirmed_repetitive_header_footer"})
        else:
            kept.append(line)
    return "".join(kept), excluded


def select_source(
    store: dict[str, Any],
    *,
    pages: str | None = None,
    section_ids: Iterable[str] | None = None,
    allow_unconfirmed: bool = False,
) -> dict[str, Any]:
    if (pages is None) == (section_ids is None):
        raise ValueError("choose exactly one of pages or section_ids")
    chunks_by_id = {item["chunk_id"]: item for item in store["chunks"]}
    available_pages = {item["pdf_page"] for item in store["pages"]}
    selected_sections: list[dict[str, Any]] = []
    requested: dict[str, Any]
    selection_scope: str
    if pages is not None:
        parsed = PageSelection.parse(pages)
        missing = sorted(set(parsed.pdf_pages) - available_pages)
        if missing:
            raise ValueError(f"pages are outside this store's extracted coverage: {missing}")
        selected_chunks = [item for item in store["chunks"] if item["pdf_page"] in parsed.pdf_pages]
        requested = {"type": "pages", "value": pages}
        resolved_pages = list(parsed.pdf_pages)
        selection_scope = "page-scoped"
        warnings = ["Page-scoped selection includes every extracted block on each requested PDF page."]
    else:
        ids = list(section_ids or [])
        if not ids or any(not item.strip() for item in ids):
            raise ValueError("section selection cannot be empty")
        section_map = {item["section_id"]: item for item in store["sections"]}
        missing_ids = [item for item in ids if item not in section_map]
        if missing_ids:
            raise ValueError(f"section not found: {', '.join(missing_ids)}")
        selected_sections = [section_map[item] for item in ids]
        blocked = [item["section_id"] for item in selected_sections if item["confirmation_status"] != "confirmed"]
        if blocked and not allow_unconfirmed:
            raise ValueError(
                "unconfirmed sections require --allow-unconfirmed or manual confirmation: " + ", ".join(blocked)
            )
        chunk_ids = {chunk_id for section in selected_sections for chunk_id in section["included_chunk_ids"]}
        selected_chunks = [item for item in store["chunks"] if item["chunk_id"] in chunk_ids]
        requested = {"type": "sections", "value": ids, "allow_unconfirmed": allow_unconfirmed}
        resolved_pages = sorted({item["pdf_page"] for item in selected_chunks})
        selection_scope = "section-scoped"
        warnings = []
        if blocked:
            warnings.append("Selection explicitly includes unconfirmed structural evidence.")

    confirmed_hf = {
        item["normalized_text"]
        for item in store["header_footer_candidates"]
        if item["status"] == "confirmed"
    }
    selected_payload: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    for chunk in selected_chunks:
        selection_text, removed = _strip_confirmed_edges(chunk["text"], confirmed_hf)
        selected_payload.append(
            {
                "chunk_id": chunk["chunk_id"],
                "pdf_page": chunk["pdf_page"],
                "source_type": chunk["source_type"],
                "start_offset": chunk["start_offset"],
                "end_offset": chunk["end_offset"],
                "original_text": chunk["text"],
                "selection_text": selection_text,
                "transformations": removed,
                "content_risk_flags": chunk["content_risk_flags"],
            }
        )
        for item in removed:
            exclusions.append({"chunk_id": chunk["chunk_id"], "pdf_page": chunk["pdf_page"], **item})

    if selected_sections:
        for section in selected_sections:
            start_order = chunks_by_id[section["start_anchor"]["chunk_id"]]["order"]
            end_order = (
                chunks_by_id[section["end_anchor_exclusive"]["chunk_id"]]["order"]
                if section["end_anchor_exclusive"]
                else len(store["chunks"])
            )
            for chunk in store["chunks"]:
                if (
                    start_order <= chunk["order"] < end_order
                    and chunk.get("selection_excluded_reason") == "confirmed_repetitive_header_footer"
                ):
                    exclusions.append(
                        {
                            "chunk_id": chunk["chunk_id"],
                            "pdf_page": chunk["pdf_page"],
                            "text": chunk["text"],
                            "reason": "confirmed_repetitive_header_footer",
                        }
                    )

    selected_ids = {item["chunk_id"] for item in selected_chunks}
    boundary_exclusions: list[dict[str, Any]] = []
    if selected_sections:
        boundary_pages = {page for section in selected_sections for page in (section["first_pdf_page"], section["last_pdf_page"])}
        for chunk in store["chunks"]:
            if chunk["pdf_page"] in boundary_pages and chunk["chunk_id"] not in selected_ids:
                boundary_exclusions.append(
                    {"chunk_id": chunk["chunk_id"], "pdf_page": chunk["pdf_page"], "reason": "outside_end_exclusive_section_boundary"}
                )

    risk_flags = sorted({flag for item in selected_chunks for flag in item["content_risk_flags"]})
    selection_key = json.dumps(requested, sort_keys=True) + "|" + "|".join(item["chunk_id"] for item in selected_chunks)
    result = {
        "schema_version": 1,
        "selection_id": stable_id("sel", store["document"]["document_id"], selection_key),
        "document_id": store["document"]["document_id"],
        "selection_scope": selection_scope,
        "requested_selector": requested,
        "resolved_sections": [item["section_id"] for item in selected_sections],
        "resolved_pdf_pages": resolved_pages,
        "included_chunk_ids": [item["chunk_id"] for item in selected_chunks],
        "chunks": selected_payload,
        "citations": [
            {"chunk_id": item["chunk_id"], "pdf_page": item["pdf_page"]} for item in selected_chunks
        ],
        "excluded_boundary_fragments": boundary_exclusions,
        "excluded_repetitive_header_footer": exclusions,
        "content_risk_flags": risk_flags,
        "warnings": warnings,
        "confirmation_status": (
            "confirmed"
            if not selected_sections or all(item["confirmation_status"] == "confirmed" for item in selected_sections)
            else "explicitly_allowed_unconfirmed"
        ),
    }
    citation_ids = {item["chunk_id"] for item in result["citations"]}
    if citation_ids != set(result["included_chunk_ids"]):
        raise ValueError("selection citations do not match selected chunks")
    if any(item["pdf_page"] not in available_pages for item in result["citations"]):
        raise ValueError("selection contains an invalid page citation")
    return result
