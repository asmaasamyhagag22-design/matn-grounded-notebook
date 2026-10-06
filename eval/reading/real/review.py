"""Generate an offline human number-review tool. Suggestions are never ground truth.

Generate after `eval.reading.closeout --subset real`; save only after the owner explicitly reviews every value,
checks the full page for missing numbers, and signs the page. Templates are untouched by the generator.
"""
from __future__ import annotations
import json
from pathlib import Path

from eval.reading.degrade import rotate_bbox
from matn_reading.ocr.numbers import number_spans, number_tokens
from matn_reading.ocr.preprocess import render_page_image
from .verify import require_verified, verify_sources

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def make_proposals(tokens, layer, angle, size, cropbox, reader2_only=()):
    scale=300/72
    def original(box):
        px=tuple((v-cropbox[i%2])*scale for i,v in enumerate(box))
        moved=rotate_bbox(px,-angle,size) if angle else px
        return [moved[i]/scale+cropbox[i%2] for i in range(4)]
    proposals=[]
    for token in tokens:
        box=original(token["bbox"])
        nearby=[text for text,lb in layer if _overlap(box,lb)>.3]
        proposals.append({"reader1":token["token"],"reader2":token.get("reader2"),"layer":" | ".join(dict.fromkeys(t for text in nearby for t in number_tokens(text))),
                          "context":token.get("word",""),"bbox":box,"chosen":None,"flagged":token["flagged"]})
    for text,box in layer:
        if any(_overlap(box,p["bbox"])>.3 for p in proposals): continue
        for token,_,_ in number_spans(text):
            proposals.append({"reader1":None,"reader2":None,"layer":token,"context":text,"bbox":list(box),
                              "chosen":None,"flagged":True})
    for flag in reader2_only:
        if flag.get("kind") != "possible_drop" or not isinstance(flag.get("reader2"), list): continue
        for token in flag["reader2"]:
            box=original(flag["bbox"])
            if any(p["reader2"]==token and _overlap(box,p["bbox"])>.3 for p in proposals): continue
            proposals.append({"reader1":None,"reader2":token,"layer":"","context":flag.get("reader2_line", ""),
                              "bbox":box,"chosen":None,"flagged":True})
    return proposals


def _overlap(a,b):
    area=min((a[2]-a[0])*(a[3]-a[1]),(b[2]-b[0])*(b[3]-b[1]))
    return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))/max(area,1e-9)


def validated_truth(path):
    gt=json.loads(Path(path).read_text(encoding="utf-8"))
    if gt.get("status")!="verified" or not gt.get("verified_by") or not gt.get("full_page_reviewed"):
        raise ValueError(f"BLOCKED-ON-OWNER: the owner must complete and sign {path}")
    for n in gt["numbers"]:
        if not n.get("verified") or len(n.get("bbox",[]))!=4 or not n.get("value_as_printed"):
            raise ValueError(f"BLOCKED-ON-OWNER: unchecked number in {path}")
    return gt


def render_html(pages):
    data=json.dumps(pages,ensure_ascii=False).replace("<","\\u003c")
    source=Path(__file__).with_name("review_ui.html").read_text(encoding="utf-8")
    return source.replace("__REVIEW_DATA__",data)


def generate():
    from eval.reading.closeout import OUT
    pages=[]
    assets=HERE / "review_assets"
    assets.mkdir(exist_ok=True)
    sources=json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    verified=verify_sources()
    for d in sources["documents"]:
        doc=d["doc_key"]
        if verified[doc]["status"]!="ok": continue
        pdf=require_verified(doc)
        for spec in d["gt_pages"]:
            index=spec["page_index"];key=f"{doc}_p{index:04d}"
            record=json.loads((OUT / "final/real" / (key+'.json')).read_text(encoding="utf-8"))
            image=render_page_image(pdf,index)
            image.save(assets / (key+'.png'))
            proposals=make_proposals(record["tokens"],record["text_layer"],record["preprocess"]["rotation_deg"],image.size,
                                    record["cropbox"],record["flags"])
            for i,p in enumerate(proposals):
                x0,y0,x1,y1=p["bbox"];ox,oy=record["cropbox"][:2];scale=300/72
                box=(max(0,int((x0-ox)*scale)-30),max(0,int((y0-oy)*scale)-30),
                     min(image.width,int((x1-ox)*scale)+30),min(image.height,int((y1-oy)*scale)+30))
                name=f"{key}_n{i:04d}.png"
                image.crop(box).save(assets / name)
                p["crop"]="review_assets/"+name
            template=json.loads((HERE / "gt" / (key+'.json')).read_text(encoding="utf-8"))
            pages.append({"key":key,"image":"review_assets/"+key+'.png',"template":template,"proposals":proposals,
                          "cropbox":record["cropbox"]})
    (HERE / "review.html").write_text(render_html(pages),encoding="utf-8")
    print(f"Offline review: {HERE / 'review.html'}; {len(pages)} pages; GT templates untouched")


if __name__=="__main__":
    import sys
    from .sample import INITIAL
    if INITIAL.exists() and '--full' not in sys.argv:
        from .sample_review import generate as generate_sample
        generate_sample()
    else:
        generate()
