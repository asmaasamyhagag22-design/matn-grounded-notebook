"""SHA-bound smoke diagnostics; cached reader input, no retrieval or tuning."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import resource
import time

from matn_contracts.structure import DocumentStructure
from matn_reading.structure.cache import load_snapshot
from matn_reading.structure.document import prepare_snapshot, write_structure
from checks.egress_guard import block_egress
from eval.rag.r_lite_3_part1 import short_distribution, SPACED
from eval.rag.r_lite_3_part2c_m4 import decisions
from eval.rag.r_lite_3_part2c_m4_data import coverage


def save(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True,allow_nan=False)+"\n")


def run(source, root, pdf, labels, expected_sha):
    started=time.perf_counter()
    if hashlib.sha256(pdf.read_bytes()).hexdigest()!=expected_sha:raise ValueError("SOURCE_SHA")
    snapshots=sorted((root/"runs").glob("*/00_reading.json"))
    if snapshots:
        snapshot=load_snapshot(snapshots[0]);acquisition_complete=True
    else:
        snapshot=load_snapshot(root/"digital_read.json");acquisition_complete=False
        with block_egress():snapshot=prepare_snapshot(snapshot,pdf)
    sidecar=json.loads(labels.read_text())
    if len(sidecar["pages"])!=len(snapshot["pages"]):raise ValueError("LAYOUT_COVERAGE")
    with block_egress():
        before=write_structure(snapshot,root/"baseline")
        after=write_structure(snapshot,root/"labeled",layout_sidecar=sidecar)
    objects={}
    import pdfplumber
    with block_egress(),pdfplumber.open(pdf) as opened:
        for page in snapshot["pages"]:
            i=page["page_index"];native=opened.pages[i]
            objects[f"{source}/{i}"]={"chars":[{"object_id":j,"text":c["text"],"bbox":[c["x0"],c["top"],c["x1"],c["bottom"]],"fontname":c["fontname"],"size":c["size"]} for j,c in enumerate(native.chars)]}
            native.close()
    save(root/"native-objects.json",objects)
    src={"snapshot":snapshot,"document":after}
    cov=coverage({source:src},objects)
    m4=decisions(src,objects,source,json.loads(Path("eval/rag/r_lite_3_part2c_m4_rule.json").read_text()))
    save(root/"m4-coverage.json",cov);save(root/"m4-projection.json",m4)
    old={e.block.block_id:e for e in before.elements}
    retyped=[e for e in after.elements if old[e.block.block_id].role=="table" and e.role=="figure"]
    tables=[e for e in after.elements if e.role=="table"]
    available={b for t in after.tables if t.structure=="available" and t.cells for b in t.block_ids}
    mixed={p["page_index"] for p in snapshot["pages"] if p["route"]=="mixed"}
    ocr=[p["page_index"] for p in snapshot["pages"] if p.get("ocr")]
    assert len(ocr)<=10,"OCR_CAP"
    routes=[{"page_index":p["page_index"],"route":p["route"],"ocr_used":bool(p.get("ocr"))} for p in snapshot["pages"]]
    raw_spacing=[{"block_id":e.block.block_id,"runs":SPACED.findall(e.block.text)} for e in after.elements if SPACED.search(e.block.text)]
    body=[c.word_count for c in after.chunks if c.kind=="body"]
    protected_evidence=[e for e in after.elements if e.citable and not (e.role=="table" and e.block.block_id not in available) and not (e.block.page_index in mixed and e.block.route.value!="text_layer")]
    sampling=json.loads(Path("eval/smoke/sampling.json").read_text());rng=random.Random(sampling["seed"])
    crops=[]
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(str(pdf)) as opened:
        for cohort,pool in [("retyped",retyped),("table-kind",tables)]:
            pool=sorted(pool,key=lambda e:e.block.block_id)
            selected=rng.sample(pool,min(sampling["sample_per_cohort"],len(pool)))
            for j,e in enumerate(selected,1):
                page=opened[e.block.page_index];bmp=page.render(scale=1.5);image=bmp.to_pil().copy()
                b=e.block.bbox;box=(max(0,int((b[0]-72)*1.5)),max(0,int((b[1]-72)*1.5)),min(image.width,int((b[2]+72)*1.5+1)),min(image.height,int((b[3]+72)*1.5+1)))
                path=root/"crops"/f"{cohort}-{j:02d}.png";path.parent.mkdir(exist_ok=True);image.crop(box).save(path)
                crops.append({"cohort":cohort,"index":j,"block_id":e.block.block_id,"pdf_page_index":e.block.page_index,"bbox":list(b),"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"visual_judgment":None,"provenance":"Codex visual judgment, not human ground truth"})
                image.close();bmp.close();page.close()
    save(root/"crops-manifest.json",crops)
    result={"source":source,"source_sha256":expected_sha,"reader_acquisition_complete":acquisition_complete,"routes":routes,"route_counts":dict(Counter(p["route"] for p in snapshot["pages"])),"ocr_pages_used":ocr,"mixed_route_pages":sorted(mixed),"unprocessed_ocr_route_pages":[p["page_index"] for p in snapshot["pages"] if p["route"] in ("mixed","scanned","digital_broken","scanned_with_ocr_layer") and not p.get("ocr")],"blocks_by_kind":dict(Counter(e.role for e in after.elements)),"reader_block_types":dict(Counter(e.block.block_type.value for e in after.elements)),"citable_words":sum(len(e.block.text.split()) for e in after.elements if e.citable),"verification_eligible_words_L3_03_12_15_17":sum(len(e.block.text.split()) for e in protected_evidence),"table_kind_available":sum(e.block.block_id in available for e in tables),"table_kind_unavailable":sum(e.block.block_id not in available for e in tables),"docling_retyped_blocks":len(retyped),"tracked_spacing_raw_runs":sum(len(r["runs"]) for r in raw_spacing),"tracked_spacing_raw_blocks":len(raw_spacing),"tracked_spacing_guarded_blocks":len(m4["texts"]),"tracked_spacing_native_coverage":{k:v for k,v in cov["sources"][source].items() if k!="rows"},"headings":sum(e.role=="heading" for e in after.elements),"sections":len(after.sections),"body_chunk_words":short_distribution(body),"body_chunks_under_10":sum(w<10 for w in body),"all_chunks_under_10":sum(c.word_count<10 for c in after.chunks),"crop_counts":dict(Counter(c["cohort"] for c in crops)),"raw_spacing":raw_spacing,"priority_evidence":{"M4":len(m4["texts"]),"L3_02_mixed_blocks":sum(e.block.page_index in mixed for e in after.elements),"chart_typing":len(retyped),"M2_heading_blocks":sum(e.role=="heading" for e in after.elements),"tiny_chunk_blocks":len({s.block_id for c in after.chunks if c.word_count<10 for s in c.primary})},"limits":"Priority counts are affected candidates, not calibrated accuracy; mixed-route pages retained by reader are not evidence until L3-02; no smoke tuning."}
    save(root/"diagnosis.json",result)
    save(root/"cost-diagnosis.json",{"wall_seconds":time.perf_counter()-started,"peak_RSS_KiB":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    print(json.dumps({k:v for k,v in result.items() if k not in ("routes","raw_spacing")},ensure_ascii=False,sort_keys=True))


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--source",required=True);p.add_argument("--root",type=Path,required=True);p.add_argument("--pdf",type=Path,required=True);p.add_argument("--labels",type=Path,required=True);p.add_argument("--sha256",required=True);a=p.parse_args()
    run(a.source,a.root,a.pdf,a.labels,a.sha256)
