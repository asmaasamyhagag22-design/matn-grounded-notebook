"""Build Matn's self-contained, offline static demo page."""
from __future__ import annotations

import json
from pathlib import Path

from matn_deck.demo_data import deck_fact_ids, receipts_for

from .build_assets import OUTPUT, build_assets, fit_16_9


def _receipt_assets(inventory: dict, output: Path) -> None:
    for deck in inventory["decks"]:
        fact_ids = deck_fact_ids(output / deck["pptx"])
        receipts = [receipt for receipt in receipts_for(deck["doc_key"], fact_ids) if receipt["value"]]
        built = []
        for receipt in receipts:
            source = receipt["crop_png"] or receipt["page_png"]
            if source is None or not Path(source).is_file():
                continue
            filename = receipt["fact_id"].replace(":", "-") + ".jpg"
            target = output / "assets" / "receipts" / deck["doc_key"] / filename
            fit_16_9(Path(source), target, 1280, quality=86)
            built.append({
                key: value for key, value in receipt.items()
                if key not in {"crop_png", "page_png"}
            } | {"image": target.relative_to(output).as_posix()})
        deck["receipts"] = built


def _site_data(inventory: dict) -> dict:
    documents = []
    by_doc: dict[str, dict] = {}
    for deck in inventory["decks"]:
        document = by_doc.setdefault(deck["doc_key"], {
            "key": deck["doc_key"], "title": deck["title"], "publisher": deck["publisher"], "deck_ids": []})
        document["deck_ids"].append(deck["id"])
    documents.extend(by_doc.values())
    return {
        "brand": "متن",
        "templates": inventory["templates"],
        "decks": inventory["decks"],
        "documents": documents,
        "timeline": inventory["timeline"],
    }


def build_site(output: Path = OUTPUT) -> Path:
    output = Path(output)
    inventory = build_assets(output)
    _receipt_assets(inventory, output)
    data = json.dumps(_site_data(inventory), ensure_ascii=False, separators=(",", ":"))
    data = data.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = HTML.replace("__SITE_DATA__", data)
    target = output / "index.html"
    target.write_text(html, encoding="utf-8")
    return target


HTML = r'''<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>متن — من المستند للعرض</title>
<style>
:root{--teal:#0b5d5b;--teal2:#083f3e;--amber:#d99a32;--ink:#172322;--muted:#63706e;--bg:#f7f6f2;--card:#fff;--line:#dfe6e3;--shadow:0 12px 34px rgba(18,48,46,.09);--r:15px}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font-family:"Segoe UI",Tahoma,sans-serif;line-height:1.55}button,a{font:inherit}button{color:inherit}.shell{width:min(1180px,calc(100% - 36px));margin:auto}
.topbar{position:sticky;top:0;z-index:20;background:rgba(247,246,242,.94);backdrop-filter:blur(12px);border-bottom:1px solid rgba(11,93,91,.1)}.navrow{min-height:72px;display:flex;align-items:center;gap:24px}.brand{display:flex;align-items:center;gap:10px;font-size:22px;font-weight:800;color:var(--teal2);margin-inline-end:auto}.brandmark{width:30px;height:30px;border-radius:9px;background:var(--teal);display:grid;place-items:center;color:#fff;box-shadow:inset 0 -7px 0 rgba(0,0,0,.08)}
.nav{display:flex;gap:7px}.nav button,.chip,.filter,.template-chip{border:1px solid transparent;background:transparent;border-radius:999px;padding:9px 15px;cursor:pointer}.nav button:hover,.nav button:focus-visible,.nav button.active{background:#e5efec;color:var(--teal2);outline:none}.nav button.active{font-weight:700}
main{padding:46px 0 80px}.page{display:none}.page.active{display:block}.eyebrow{font-size:13px;color:var(--teal);font-weight:800;letter-spacing:.04em}.hero{padding:48px 44px;border-radius:24px;background:linear-gradient(125deg,#e5f0ed 0%,#fffaf0 100%);box-shadow:var(--shadow);overflow:hidden;position:relative}.hero:after{content:"";position:absolute;inset:auto -80px -120px auto;width:300px;height:300px;border:45px solid rgba(217,154,50,.13);border-radius:50%}.hero h1{font-size:clamp(34px,5vw,58px);line-height:1.12;max-width:850px;margin:10px 0 18px;color:var(--teal2)}.hero p{font-size:19px;color:var(--muted);max-width:720px;margin:0}.pillars{display:flex;gap:10px;flex-wrap:wrap;margin-top:28px;position:relative;z-index:1}.pillar{padding:9px 14px;border-radius:999px;background:#fff;border:1px solid #d5e4df;font-size:14px;font-weight:700}.pillar:before{content:"✓";color:var(--teal);margin-left:7px}
.section-head{display:flex;align-items:end;justify-content:space-between;gap:20px;margin:48px 0 20px}.section-head h2{font-size:30px;line-height:1.2;margin:0}.section-head p{margin:5px 0 0;color:var(--muted)}
.timeline{position:relative;padding-right:35px}.timeline:before{content:"";position:absolute;right:9px;top:10px;bottom:10px;width:2px;background:#c7d7d2}.step{position:relative;margin-bottom:32px}.step:before{content:"";position:absolute;right:-33px;top:8px;width:15px;height:15px;border:4px solid var(--bg);background:var(--teal);border-radius:50%;box-shadow:0 0 0 2px var(--teal)}.step.current:before{background:var(--amber);box-shadow:0 0 0 2px var(--amber)}.step-title{display:flex;align-items:center;gap:10px;margin-bottom:12px}.version{font-weight:800;color:var(--teal)}.current .version{color:#9a6307}.step h3{font-size:20px;margin:0}.step p{margin:0 0 14px;color:var(--muted)}.slide-row{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.slide-row img,.ratio-img{display:block;width:100%;aspect-ratio:16/9;object-fit:contain;background:#ecefeb;border-radius:12px;border:1px solid var(--line)}
.next-grid,.gallery,.doc-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.next-card,.gallery-card,.doc-card,.panel,.receipt-card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);box-shadow:var(--shadow)}.next-card{padding:22px}.next-card .num{color:var(--amber);font-weight:800;font-size:13px}.next-card h3{font-size:19px;margin:8px 0}.next-card p{font-size:14px;color:var(--muted);margin:0}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 20px}.filter{background:#fff;border-color:var(--line)}.filter.active,.template-chip.active{background:var(--teal);color:#fff}.gallery{grid-template-columns:repeat(3,1fr)}.gallery-card{padding:0;overflow:hidden;text-align:right;cursor:pointer;transition:transform .16s,box-shadow .16s}.gallery-card:hover,.gallery-card:focus-visible{transform:translateY(-3px);box-shadow:0 18px 42px rgba(18,48,46,.15);outline:3px solid rgba(11,93,91,.2)}.gallery-card .body{padding:17px}.gallery-card h3{font-size:19px;margin:0}.en{display:block;direction:ltr;text-align:right;font-size:13px;color:var(--muted)}.meta-row{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin-top:11px}.tag{font-size:12px;background:#edf2f0;padding:4px 8px;border-radius:999px}.star{color:#b4740a;font-size:17px}.preview-note{color:#8a5a08}
.doc-grid{grid-template-columns:repeat(3,1fr)}.doc-card{padding:20px;text-align:right;cursor:pointer}.doc-card.active{border:2px solid var(--teal);background:#f1f8f6}.doc-card h3{font-size:17px;margin:0 0 8px}.doc-card p{font-size:13px;color:var(--muted);margin:0}.template-chips{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.template-chip{background:#fff;border-color:var(--line)}.viewer-panel{padding:18px}.viewer-main{position:relative}.viewer-main img{box-shadow:0 10px 30px rgba(0,0,0,.12)}.round-btn{position:absolute;top:50%;transform:translateY(-50%);width:45px;height:45px;border:0;border-radius:50%;background:rgba(8,63,62,.92);color:#fff;font-size:25px;cursor:pointer;box-shadow:0 5px 18px rgba(0,0,0,.2)}.prev{right:14px}.next{left:14px}.viewer-tools{display:flex;justify-content:space-between;align-items:center;gap:14px;margin:14px 0}.counter{font-size:14px;color:var(--muted)}.downloads{display:flex;gap:8px;flex-wrap:wrap}.download{display:inline-flex;text-decoration:none;padding:9px 14px;border-radius:10px;background:var(--teal);color:#fff;font-size:14px}.download.secondary{background:#fff;color:var(--teal);border:1px solid var(--teal)}.filmstrip{display:flex;gap:9px;overflow:auto;padding:4px 2px 10px}.filmstrip button{flex:0 0 132px;padding:0;border:2px solid transparent;border-radius:9px;overflow:hidden;cursor:pointer;background:#fff}.filmstrip button.active{border-color:var(--amber)}.filmstrip img{width:100%;display:block;aspect-ratio:16/9;object-fit:contain}
.receipts-layout{display:grid;grid-template-columns:1fr 1.55fr;gap:18px}.receipt-list{display:grid;gap:11px;align-content:start}.receipt-card{padding:16px;text-align:right;cursor:pointer}.receipt-card.active{border:2px solid var(--amber);background:#fffaf0}.big-value{font-size:31px;font-weight:800;color:var(--teal2);line-height:1}.receipt-card p{font-size:13px;color:var(--muted);margin:8px 0 0}.receipt-detail{padding:23px;position:sticky;top:94px}.quote{font-size:20px;line-height:1.75;margin:10px 0 14px}mark{background:#ffe09b;color:inherit;border-radius:4px;padding:0 3px}.page-label{color:var(--muted);font-size:13px}.empty{padding:38px;text-align:center;color:var(--muted);background:#fff;border:1px dashed #bac9c5;border-radius:var(--r)}
.modal{position:fixed;inset:0;background:rgba(4,20,19,.92);z-index:50;display:none;padding:22px}.modal.open{display:grid;grid-template-rows:auto 1fr auto}.modal-head{display:flex;align-items:center;justify-content:space-between;color:#fff}.modal-head h2{font-size:21px;margin:0}.close{border:1px solid rgba(255,255,255,.35);background:transparent;color:#fff;border-radius:50%;width:42px;height:42px;font-size:24px;cursor:pointer}.modal-stage{min-height:0;display:grid;place-items:center;position:relative}.modal-stage img{max-width:min(1180px,90vw);max-height:68vh;width:100%;aspect-ratio:16/9;object-fit:contain}.modal .filmstrip{direction:ltr}.modal .filmstrip button{flex-basis:112px}.modal .counter{color:#d3dfdc}.modal .viewer-tools{color:#fff;max-width:1180px;width:100%;margin:10px auto}.modal .download.secondary{background:transparent;color:#fff;border-color:#fff}
@media(max-width:850px){.navrow{align-items:flex-start;padding:12px 0;flex-wrap:wrap}.brand{width:100%}.nav{width:100%;overflow:auto}.nav button{white-space:nowrap}.hero{padding:34px 24px}.gallery,.next-grid{grid-template-columns:repeat(2,1fr)}.doc-grid,.receipts-layout{grid-template-columns:1fr}.receipt-detail{position:static}.slide-row{grid-template-columns:1fr 1fr}.slide-row img:last-child{display:none}}
@media(max-width:560px){.shell{width:min(100% - 24px,1180px)}main{padding-top:24px}.gallery,.next-grid{grid-template-columns:1fr}.hero h1{font-size:34px}.viewer-tools{align-items:flex-start;flex-direction:column}.round-btn{width:39px;height:39px}.filmstrip button{flex-basis:98px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
</style>
</head>
<body>
<header class="topbar"><div class="shell navrow"><div class="brand"><span class="brandmark">م</span><span>متن</span></div><nav class="nav" aria-label="أقسام الموقع"><button class="active" data-page="story">القصة</button><button data-page="gallery-page">المعرض</button><button data-page="presentation">العرض</button><button data-page="receipts">الإيصالات</button></nav></div></header>
<main class="shell">
<section id="story" class="page active"><div class="hero"><div class="eyebrow">PDF → VERIFIED DECK</div><h1>متن: من المستند للعرض، وكل رقم بمصدره</h1><p>ديمو محلي بالكامل يحوّل المحتوى الموثّق لعرض PowerPoint حقيقي، ويخلي الدليل قريب من كل رقم.</p><div class="pillars"><span class="pillar">أوفلاين</span><span class="pillar">أرقام متحقق منها</span><span class="pillar">PowerPoint بيتعدل</span><span class="pillar">معرض قوالب</span></div></div><div class="section-head"><div><div class="eyebrow">رحلة التصميم</div><h2>من أول نسخة لحد الليلة</h2></div><p>صور شرائح حقيقية، من غير crop.</p></div><div id="timeline" class="timeline"></div><div class="section-head"><div><div class="eyebrow">ROADMAP</div><h2>اللي جاي</h2></div></div><div class="next-grid" id="next-grid"></div></section>
<section id="gallery-page" class="page"><div class="section-head"><div><div class="eyebrow">16 TEMPLATE</div><h2>معرض القوالب</h2><p>الداكن الأول. مودولو هو الاختيار الافتراضي.</p></div></div><div class="filters" id="filters"></div><div class="gallery" id="gallery"></div></section>
<section id="presentation" class="page"><div class="section-head"><div><div class="eyebrow">3 DEV DOCUMENTS</div><h2>اختاري المستند والقالب</h2><p>كل تركيبة هنا متصدّرة فعلًا كـ PPTX وPDF.</p></div></div><div class="doc-grid" id="documents"></div><div class="template-chips" id="presentation-templates"></div><div class="panel viewer-panel" id="presentation-viewer"></div></section>
<section id="receipts" class="page"><div class="section-head"><div><div class="eyebrow">SOURCE RECEIPTS</div><h2>كل رقم ومعاه الإيصال</h2><p id="receipt-deck-name"></p></div></div><div class="receipts-layout"><div class="receipt-list" id="receipt-list"></div><div class="panel receipt-detail" id="receipt-detail"></div></div></section>
</main>
<div class="modal" id="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-head"><h2 id="modal-title"></h2><button class="close" aria-label="اقفل المعاينة">×</button></div><div class="modal-stage"><button class="round-btn prev" aria-label="الشريحة السابقة">›</button><img id="modal-image" alt=""><button class="round-btn next" aria-label="الشريحة التالية">‹</button></div><div><div class="viewer-tools"><span class="counter" id="modal-counter"></span><div class="downloads" id="modal-downloads"></div></div><div class="filmstrip" id="modal-filmstrip"></div></div></div>
<script id="site-data" type="application/json">__SITE_DATA__</script>
<script>
const DATA=JSON.parse(document.getElementById('site-data').textContent);const byDeck=Object.fromEntries(DATA.decks.map(d=>[d.id,d]));const byTemplate=Object.fromEntries(DATA.templates.map(t=>[t.id,t]));
const nextItems=[['01','الملخص من أي PDF','استخراج واختيار وتنظيم المحتوى قبل العرض.'],['02','التحقق من المعنى (3 طبقات)','حذف فقط، اتفاق الاتجاه والـ modality، وحقيقة واحدة لكل KPI.'],['03','الأيقونات','نظام أيقونات محلي يخدم المعنى من غير زخرفة.'],['04','العربي','RTL كامل وصياغة عربية مهنية من أول الـ pipeline.'],['05','التشغيل على جهاز الشغل','حزمة أوفلاين واضحة التثبيت والتحديث.']];
let selectedDeck=(DATA.templates.find(t=>t.default)||DATA.templates[0]).primary_deck_id||DATA.decks[0].id;let presentationDoc=byDeck[selectedDeck].doc_key;let presentationSlide=0;let modalDeck=null;let modalSlide=0;
const el=id=>document.getElementById(id);function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n}function img(src,alt,cls=''){const n=node('img',cls);n.src=src;n.alt=alt;return n}
document.querySelectorAll('.nav button').forEach(b=>b.addEventListener('click',()=>{document.querySelectorAll('.nav button').forEach(x=>x.classList.toggle('active',x===b));document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===b.dataset.page));if(b.dataset.page==='receipts')renderReceipts();window.scrollTo({top:0})}));
function renderStory(){DATA.timeline.forEach(s=>{const box=node('article','step'+(s.current?' current':''));const head=node('div','step-title');head.append(node('span','version',s.version),node('h3','',s.title));box.append(head,node('p','',s.sentence));const row=node('div','slide-row');s.images.forEach((x,i)=>row.append(img(x,`${s.version} — شريحة ${i+1}`)));box.append(row);el('timeline').append(box)});nextItems.forEach(x=>{const c=node('article','next-card');c.append(node('div','num',x[0]),node('h3','',x[1]),node('p','',x[2]));el('next-grid').append(c)})}
const filters=[['all','الكل'],['classic','كلاسيك'],['creative','إبداعي'],['dark','غامق'],['light','فاتح']];let filter='all';function renderFilters(){el('filters').replaceChildren(...filters.map(([id,label])=>{const b=node('button','filter'+(filter===id?' active':''),label);b.onclick=()=>{filter=id;renderFilters();renderGallery()};return b}))}
function matches(t){return filter==='all'||t.family===filter||t.mode===filter}function templateCard(t){const b=node('button','gallery-card');b.type='button';b.append(img(t.cover,`${t.name_ar} — ${t.name_en}`,'ratio-img'));const body=node('div','body');const title=node('h3','',t.name_ar+(t.default?' ':''));if(t.default)title.append(node('span','star','★'));body.append(title,node('span','en',t.name_en));const meta=node('div','meta-row');meta.append(node('span','tag',t.mood),node('span','tag',t.mode==='dark'?'غامق':'فاتح'));if(!t.primary_deck_id)meta.append(node('span','tag preview-note','معاينة فقط'));body.append(meta);b.append(body);b.onclick=()=>openTemplate(t);return b}function renderGallery(){el('gallery').replaceChildren(...DATA.templates.filter(matches).map(templateCard))}
function currentModalSlides(){return modalDeck?modalDeck.viewer:[byTemplate[modalDeck===null?'':modalDeck]?.cover].filter(Boolean)}function openTemplate(t){selectedDeck=t.primary_deck_id||selectedDeck;modalDeck=t.primary_deck_id?byDeck[t.primary_deck_id]:{id:null,template_id:t.id,viewer:[t.cover],grid:[t.cover],pptx:null,pdf:null};modalSlide=0;renderModal();el('modal').classList.add('open');el('modal').querySelector('.close').focus()}
function downloadLinks(deck,dark=false){const wrap=node('div','downloads');if(!deck||!deck.pptx)return wrap;[['pptx','Download PPTX',''],['pdf','Download PDF','secondary']].forEach(([key,label,cls])=>{const a=node('a','download '+cls,label);a.href=deck[key];a.download='';wrap.append(a)});return wrap}
function renderModal(){const t=byTemplate[modalDeck.template_id];el('modal-title').textContent=t?`${t.name_ar} · ${t.name_en}`:'معاينة';el('modal-image').src=modalDeck.viewer[modalSlide];el('modal-image').alt=`${t?.name_ar||'القالب'} — شريحة ${modalSlide+1}`;el('modal-counter').textContent=`${modalSlide+1} / ${modalDeck.viewer.length}`;el('modal-downloads').replaceChildren(...downloadLinks(modalDeck).childNodes);const fs=el('modal-filmstrip');fs.replaceChildren(...modalDeck.grid.map((x,i)=>{const b=node('button',i===modalSlide?'active':'');b.append(img(x,`شريحة ${i+1}`));b.onclick=()=>{modalSlide=i;renderModal()};return b}))}
function stepModal(delta){if(!modalDeck)return;modalSlide=(modalSlide+delta+modalDeck.viewer.length)%modalDeck.viewer.length;renderModal()}function closeModal(){el('modal').classList.remove('open');modalDeck=null}el('modal').querySelector('.close').onclick=closeModal;el('modal').querySelector('.prev').onclick=()=>stepModal(-1);el('modal').querySelector('.next').onclick=()=>stepModal(1);el('modal').addEventListener('click',e=>{if(e.target===el('modal'))closeModal()});document.addEventListener('keydown',e=>{if(!el('modal').classList.contains('open'))return;if(e.key==='Escape')closeModal();if(e.key==='ArrowLeft')stepModal(1);if(e.key==='ArrowRight')stepModal(-1)});
function renderDocuments(){el('documents').replaceChildren(...DATA.documents.map(d=>{const b=node('button','doc-card'+(d.key===presentationDoc?' active':''));b.append(node('h3','',d.title),node('p','',d.publisher));b.onclick=()=>{presentationDoc=d.key;const ids=d.deck_ids;const modulo=ids.find(x=>byDeck[x].template_id==='modulo');selectedDeck=modulo||ids[0];presentationSlide=0;renderDocuments();renderPresentation()};return b}))}
function renderPresentation(){const options=DATA.decks.filter(d=>d.doc_key===presentationDoc);el('presentation-templates').replaceChildren(...options.map(d=>{const t=byTemplate[d.template_id];const b=node('button','template-chip'+(d.id===selectedDeck?' active':''),t.name_ar+(t.default?' ★':''));b.onclick=()=>{selectedDeck=d.id;presentationSlide=0;renderPresentation()};return b}));const deck=byDeck[selectedDeck];const wrap=el('presentation-viewer');wrap.replaceChildren();const stage=node('div','viewer-main');stage.append(img(deck.viewer[presentationSlide],`شريحة ${presentationSlide+1}`,'ratio-img'));const prev=node('button','round-btn prev','›');prev.ariaLabel='الشريحة السابقة';prev.onclick=()=>{presentationSlide=(presentationSlide-1+deck.viewer.length)%deck.viewer.length;renderPresentation()};const next=node('button','round-btn next','‹');next.ariaLabel='الشريحة التالية';next.onclick=()=>{presentationSlide=(presentationSlide+1)%deck.viewer.length;renderPresentation()};stage.append(prev,next);wrap.append(stage);const tools=node('div','viewer-tools');tools.append(node('span','counter',`${presentationSlide+1} / ${deck.viewer.length}`),downloadLinks(deck));wrap.append(tools);const fs=node('div','filmstrip');deck.grid.forEach((x,i)=>{const b=node('button',i===presentationSlide?'active':'');b.append(img(x,`شريحة ${i+1}`));b.onclick=()=>{presentationSlide=i;renderPresentation()};fs.append(b)});wrap.append(fs)}
function appendQuote(container,text,value){const index=text.indexOf(value);if(index<0){container.textContent=text;return}container.append(document.createTextNode(text.slice(0,index)));const mark=node('mark','',value);container.append(mark,document.createTextNode(text.slice(index+value.length)))}
function renderReceiptDetail(receipt){const box=el('receipt-detail');box.replaceChildren();if(!receipt){box.append(node('div','empty','العرض ده مفيهوش أرقام مستخدمة.'));return}box.append(node('div','eyebrow','الاقتباس الدقيق'));const q=node('blockquote','quote');appendQuote(q,receipt.quote,receipt.value);box.append(q,node('div','page-label',`الصفحة ${receipt.page_label} · ${receipt.section||'المستند'}`),img(receipt.image,`صورة مصدر الرقم ${receipt.value}`,'ratio-img'))}
function renderReceipts(){const deck=byDeck[selectedDeck];const t=byTemplate[deck.template_id];el('receipt-deck-name').textContent=`${deck.title} · ${t.name_ar}`;const receipts=deck.receipts||[];const list=el('receipt-list');list.replaceChildren();receipts.forEach((r,i)=>{const b=node('button','receipt-card'+(i===0?' active':''));b.append(node('div','big-value',r.value+(r.unit==='%'?'%':r.unit?' '+r.unit:'')),node('p','',r.label||r.claim));b.onclick=()=>{list.querySelectorAll('.receipt-card').forEach(x=>x.classList.remove('active'));b.classList.add('active');renderReceiptDetail(r)};list.append(b)});if(!receipts.length)list.append(node('div','empty','مفيش number facts مستخدمة في العرض ده.'));renderReceiptDetail(receipts[0])}
renderStory();renderFilters();renderGallery();renderDocuments();renderPresentation();
</script>
</body></html>'''


if __name__ == "__main__":
    print(build_site())
