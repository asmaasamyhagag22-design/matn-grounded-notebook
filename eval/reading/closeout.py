"""Resumable Step 4c runs. One immutable checkpoint per page; holdout2 is only a final frozen measurement.

Calibration compares adaptive vs no-denoise on dev-tune only. Final runs do not rewrite original 4c results.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import time
from pathlib import Path

from PIL import Image
from checks.egress_guard import block_egress
from eval.reading.degrade import degrade
from eval.reading.digital import dev_documents
from eval.reading.scan import synthetic_pages, synthetic_image, ground_truth, score_page, _timing
from matn_reading.cli import write_reading, write_report
from matn_reading.ocr.glm import GlmReader
from matn_reading.ocr.preprocess import PreprocessConfig, preprocess, render_page_image
from matn_reading.ocr.reader1 import RapidOcrWorker
from matn_reading.ocr.route import OcrConfig, read_scan_page
from matn_reading.overlay import draw_scan_overlay
from matn_reading.read import read_document
from matn_reading.pdf_page import OpenPdf
from matn_reading.triage import Route, decide_route

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "out/reading/step4c-closeout-final-v3"


def fingerprint(mode):
    files = sorted((REPO / "matn_reading").rglob("*.py")) + sorted((REPO / "matn_reading/ocr").glob("*.json"))
    files += [REPO / "eval/reading/synthetic/holdout2.json", Path(__file__)]
    return hashlib.sha256(mode.encode() + b"".join(p.read_bytes().replace(b"\r\n", b"\n") for p in files)).hexdigest()


def specs(subset):
    if subset == "holdout2":
        return json.loads((REPO / "eval/reading/synthetic/holdout2.json").read_text(encoding="utf-8"))["pages"]
    if subset == "real":
        from eval.reading.real.verify import verify_sources
        sources = json.loads((REPO / "eval/reading/real/sources.json").read_text(encoding="utf-8"))
        verified = verify_sources()
        return [{"doc_id": d["doc_key"], "page_index": p["page_index"], "kinds": [p["kind"]]}
                for d in sources["documents"] if verified[d["doc_key"]]["status"] == "ok" for p in d["gt_pages"]]
    return synthetic_pages(subset)


def run(subset, mode="final", max_seconds=6900):
    if mode != "final" and subset != "dev_tune":
        raise ValueError("Denoise selection is dev-tune ONLY")
    config = OcrConfig(preprocess=PreprocessConfig(denoise=mode != "no_denoise"), second_read=mode == "final")
    folder = OUT / mode / subset
    folder.mkdir(parents=True, exist_ok=True)
    docs = dict(dev_documents())
    identity = fingerprint(mode)
    rows = []
    started_run = time.perf_counter()
    with block_egress(), RapidOcrWorker() as worker:
        glm = GlmReader() if config.second_read else None
        for spec in specs(subset):
            doc, index = spec["doc_id"], spec["page_index"]
            target = folder / f"{doc}_p{index:04d}.json"
            if target.is_file():
                old = json.loads(target.read_text(encoding="utf-8"))
                if old["fingerprint"] != identity:
                    raise ValueError(f"Checkpoint belongs to different code/rules: {target}; preserve it and use a new mode/output.")
                rows.append(old)
                continue
            if time.perf_counter()-started_run > max_seconds:
                print("REMAINDER_PENDING: restart the same command; completed pages are retained", flush=True)
                return 2
            started = time.perf_counter()
            layer = []
            if subset == "real":
                from eval.reading.real.verify import require_verified
                pdf = require_verified(doc)
                with OpenPdf(pdf) as opened:
                    data = opened.page(index)
                    cropbox, label = data.cropbox, data.page_label
                    route, reasons = decide_route(data.signals)
                    if route is Route.SCANNED_WITH_OCR_LAYER:
                        layer = [(w.text,(w.x0,w.top,w.x1,w.bottom)) for w in data.words]
                image = render_page_image(pdf,index)
                params = {"rotation_deg": 0.0}
            else:
                pdf = docs[doc]
                digital = read_document(pdf,pages=[index]).pages[0]
                cropbox, label = digital.cropbox, digital.page_label
                route, reasons = Route.SCANNED, ["synthetic scan", "dev-check seen" if subset == "dev_check" else subset]
                if "seed" in spec:
                    image, params = degrade(render_page_image(pdf,index), spec["seed"])
                else:
                    image, params = synthetic_image(doc,pdf,index)
            page = read_scan_page(image,page_index=index,page_label=label,cropbox=cropbox,route=route,reasons=reasons,
                                  doc_id="sha256-"+"0"*64,worker=worker,glm=glm,config=config,crop_dir=folder,text_layer=layer)
            processed, _ = preprocess(image, config.preprocess)
            record = {"fingerprint": identity, "doc_id":doc,"page_index":index,"subset":subset,"mode":mode,
                      "kinds":spec["kinds"],"degrade":params,"cropbox":cropbox,
                      "wall_seconds":round(time.perf_counter()-started,2),
                      "timing":_timing(page.ocr,page.ocr["preprocess_seconds"]),
                      "reader1_tokens":len(page.ocr["tokens"]),"flagged_tokens":sum(t["flagged"] for t in page.ocr["tokens"]),
                      "tokens":page.ocr["tokens"],"lines":page.ocr["lines"],"flags":page.flags,"layout":page.ocr["layout"],
                      "layout_seconds":page.ocr["layout_seconds"],"preprocess":page.ocr["preprocess"],"text_layer":layer}
            if subset != "real":
                gt_words, gt_lines = ground_truth(digital,params["rotation_deg"]+page.ocr["preprocess"]["rotation_deg"],image.size)
                record.update(score_page(page,gt_words,gt_lines))
            # Checkpoint before expensive PNG/export work: the inference is never lost on restart.
            target.write_text(json.dumps(record,ensure_ascii=False,indent=1),encoding="utf-8")
            if mode == "final":
                draw_scan_overlay(page,processed,config.dpi).save(folder / f"{doc}_p{index:04d}.png")
                write_reading([page],doc,folder / f"{doc}_p{index:04d}.md")
                write_report([page],doc,record["wall_seconds"],record["wall_seconds"],folder / f"{doc}_p{index:04d}-report.md")
            rows.append(record)
            print(f"{mode} {subset} {doc} p{index}: checkpoint saved ({record['wall_seconds']}s)",flush=True)
    (OUT / mode / f"{subset}.json").write_text(json.dumps({"subset":subset,"mode":mode,"fingerprint":identity,"pages":rows},
                                                         ensure_ascii=False,indent=1),encoding="utf-8")
    return 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subset",choices=["dev_tune","dev_check","holdout2","real"],required=True)
    parser.add_argument("--mode",choices=["final","adaptive_candidate","no_denoise"],default="final")
    return run(**vars(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
