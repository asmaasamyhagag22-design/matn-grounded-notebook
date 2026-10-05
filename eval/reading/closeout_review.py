"""Visual evidence for every raw silent error of a completed final close-out run. Does not adjudicate automatically."""
import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from eval.reading.closeout import OUT
from eval.reading.degrade import degrade, rotate_bbox
from eval.reading.digital import dev_documents
from eval.reading.scan import synthetic_image
from matn_reading.ocr.preprocess import render_page_image, preprocess


def build(subset):
    data=json.loads((OUT / "final" / (subset+'.json')).read_text(encoding="utf-8"))
    docs=dict(dev_documents());panels=[];cases=[]
    folder=OUT / "adjudication" / subset;folder.mkdir(parents=True,exist_ok=True)
    font=ImageFont.truetype("arial.ttf",19)
    for row in data["pages"]:
        problems=[d for d in row["number_problems"] if d["status"] in ("wrong","inserted") and not d["flagged"]]
        if not problems:continue
        doc,index=row["doc_id"],row["page_index"]
        clean=render_page_image(docs[doc],index)
        if subset=="holdout2":
            image,_=degrade(clean,row["degrade"]["seed"])
        else:image,_=synthetic_image(doc,docs[doc],index)
        processed,_=preprocess(image)
        scale=300/72;ox,oy=row["cropbox"][:2]
        angle=row["degrade"]["rotation_deg"]+row["preprocess"]["rotation_deg"]
        for problem in problems:
            number=len(cases);box=problem["where"]
            px=((box[0]-ox)*scale,(box[1]-oy)*scale,(box[2]-ox)*scale,(box[3]-oy)*scale)
            original=rotate_bbox(px,-angle,clean.size)
            def crop(im,b):
                pad=100
                b=(max(0,int(b[0])-pad),max(0,int(b[1])-pad),min(im.width,int(b[2])+pad),min(im.height,int(b[3])+pad))
                return im.crop(b).convert("RGB")
            left,right=crop(clean,original),crop(processed,px)
            panel=Image.new("RGB",(1400,500),"white");draw=ImageDraw.Draw(panel)
            title=f"{subset} #{number} {doc} p{index}: truth {problem['expected']!r}, read {problem['got']!r}"
            draw.text((15,10),title,fill="black",font=font)
            for x,im,label in [(15,left,'Clean original'),(710,right,'Both readers saw this scan')]:
                draw.text((x,45),label,fill="black",font=font)
                im.thumbnail((675,420));panel.paste(im,(x,75))
            panel.save(folder / f"case-{number:03d}.png")
            panels.append(panel)
            cases.append({"id":number,"subset":subset,"doc_id":doc,"page_index":index,**problem,
                          "image":str(folder / f"case-{number:03d}.png"),"judgment":None,"reason":None})
    for start in range(0,len(panels),4):
        selected=panels[start:start+4];sheet=Image.new("RGB",(1400,500*len(selected)),"white")
        for i,p in enumerate(selected):sheet.paste(p,(0,i*500))
        sheet.save(folder / f"sheet-{start//4:02d}.png")
    (folder / "cases.json").write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"{subset}: {len(cases)} raw silent errors; visual evidence {folder}")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("subset",choices=['dev_tune','dev_check','holdout2'])
    build(p.parse_args().subset)
