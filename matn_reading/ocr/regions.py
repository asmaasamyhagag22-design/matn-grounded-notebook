"""Frozen semantic regions and orientation; no model imports in the pipeline venv."""
import json
import math
import re
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

RULES = json.loads(Path(__file__).with_name("closeout_rules.json").read_text(encoding="utf-8"))
ROLES = {"chart": "figure_text", "image": "figure_text", "header_image": "header", "footer_image": "footer",
         "header": "header", "footer": "footer", "number": "footer", "vertical_text": "vertical_text",
         "table": "table", "figure_title": "caption", "table_title": "caption", "caption": "caption", "footnote": "footnote", "doc_title": "heading", "paragraph_title": "heading"}


def coverage(box, outer):
    area = max(0, box[2]-box[0]) * max(0, box[3]-box[1])
    return (max(0, min(box[2],outer[2])-max(box[0],outer[0])) *
            max(0, min(box[3],outer[3])-max(box[1],outer[1]))) / max(area, 1e-9)


def role(box, regions):
    matches = [r for r in regions if coverage(box, r["bbox"]) >= RULES["region_word_coverage"]]
    # A caption overlapping a enclosing image must remain a caption. Otherwise prefer the smaller region.
    matches.sort(key=lambda r: (ROLES.get(r["class"]) != "caption",
                               (r["bbox"][2]-r["bbox"][0])*(r["bbox"][3]-r["bbox"][1])))
    return ROLES.get(matches[0]["class"], "text") if matches else "text"


def orientation(quad, box, semantic_role):
    edges = [(quad[(i+1)%4][0]-quad[i][0], quad[(i+1)%4][1]-quad[i][1]) for i in range(2)]
    dx, dy = max(edges, key=lambda e:e[0]**2+e[1]**2)
    angle = math.degrees(math.atan2(dy, dx))
    angle = (angle+90) % 180-90
    tall = (box[3]-box[1]) > RULES["vertical_aspect_ratio"] * max(box[2]-box[0],1)
    if tall or semantic_role == "vertical_text":
        return -90.0 if abs(angle) < RULES["rotation_min_degrees"] else angle
    return angle if abs(angle) >= RULES["rotation_min_degrees"] else 0.0


def repeat_furniture(pages):
    """Confirm model furniture and find repeated text only within frozen top/bottom margins."""
    candidates = defaultdict(list)
    for page in pages:
        if page.ocr is None:
            continue
        for block in page.blocks:
            box = block.contract.bbox
            zone = "header" if box[3] <= page.cropbox[1] + page.height * RULES["margin_fraction"] else (
                "footer" if box[1] >= page.cropbox[3] - page.height * RULES["margin_fraction"] else None)
            if zone:
                key = re.sub(r"\d+", "#", block.contract.text.lower()).strip()
                candidates[(zone, key)].append((page, block))
    for (zone, key), items in candidates.items():
        count = len({p.page_index for p,b in items})
        if not key or count < RULES["furniture_min_pages"] or count / max(len(pages),1) < RULES["furniture_page_share"]:
            continue
        for page, block in items:
            block.block_type = zone
            # Keep deterministic provenance IDs coherent with the classification.
            from matn_contracts.domain import Block
            data = block.contract.model_dump(exclude={"block_id"})
            data["block_type"] = zone
            block.contract = Block.create(**data)
            page.flags.append({"kind": "repeated_furniture", "bbox": block.contract.bbox, "pages": count})
