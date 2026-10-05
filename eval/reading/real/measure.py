"""Real-scan number metrics only from signed human GT. Never derive GT from OCR predictions."""
import json
from pathlib import Path

from eval.reading.closeout import OUT
from eval.reading.degrade import rotate_bbox
from eval.reading.metrics import Word, score_numbers
from eval.reading.scan import token_correct
from .review import HERE, validated_truth
from .verify import require_verified, verify_sources


def measure():
    rows=[];blocked=[];unavailable=[]
    sources=json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    states=verify_sources()
    # Validate the entire available set before publishing any rates.
    for doc in sources["documents"]:
        key=doc["doc_key"]
        if states[key]["status"]!="ok":
            unavailable.append(f"{key}: source {states[key]['status']}")
            continue
        require_verified(key)
        for spec in doc["gt_pages"]:
            pagekey=f"{key}_p{spec['page_index']:04d}"
            try:
                gt=validated_truth(HERE / "gt" / (pagekey+'.json'))
                if gt.get("doc_key") != key or gt.get("page_index") != spec["page_index"]:
                    raise ValueError(f"BLOCKED-ON-OWNER: {pagekey}.json must contain doc_key={key} and page_index={spec['page_index']}; check the matching reviewed template")
            except ValueError as e:
                blocked.append(str(e));continue
            record=json.loads((OUT / "final/real" / (pagekey+'.json')).read_text(encoding="utf-8"))
            rows.append((pagekey,gt,record))
    if blocked:
        raise SystemExit("BLOCKED-ON-OWNER:\n"+'\n'.join(blocked))
    results=[]
    for key,gt,r in rows:
        scale=300/72;ox,oy=r["cropbox"][:2]
        size=r["preprocess"]["size"];angle=r["preprocess"]["rotation_deg"]
        def moved(box):
            px=((box[0]-ox)*scale,(box[1]-oy)*scale,(box[2]-ox)*scale,(box[3]-oy)*scale)
            b=rotate_bbox(px,angle,size)
            return (b[0]/scale+ox,b[1]/scale+oy,b[2]/scale+ox,b[3]/scale+oy)
        illegible=[n for n in gt["numbers"] if n["value_as_printed"]=="[illegible]"]
        words=[Word(n["value_as_printed"],moved(n["bbox"])) for n in gt["numbers"] if n not in illegible]
        tokens=r["tokens"]
        hyp=[Word(t["token"],tuple(t["bbox"]),t["flagged"]) for t in tokens]
        flags=[tuple(f["bbox"]) for f in r["flags"] if f["kind"] in ("possible_drop","ocr_no_text")]
        report=score_numbers(words,hyp,flagged_regions=flags)
        flagged=[t for t in tokens if t["flagged"]]
        correct=sum(token_correct(t,words) for t in tokens)
        false=sum(token_correct(t,words) for t in flagged)
        results.append({"page":key,"gt_numbers":len(words),"illegible_gt":len(illegible),
                        "accuracy":report.correct/max(report.total,1),"silent_errors_raw":report.silent_errors,
                        "silent_drops":report.silent_drops,"flag_rate":len(flagged)/max(len(tokens),1),
                        "false_alarms":false,"flagged_tokens":len(flagged),
                        "false_alarm_share_of_flags":false/max(len(flagged),1),
                        "false_positive_rate_on_correct_reads":false/max(correct,1),
                        "wall_seconds":r["wall_seconds"],"problems":report.details})
    target=OUT / "real-human-metrics.json"
    target.write_text(json.dumps({"status":"raw; every silent error still needs visual adjudication",
                                  "unavailable_sources":unavailable,"pages":results},ensure_ascii=False,indent=2),encoding="utf-8")
    print(target)


if __name__=="__main__":
    measure()
