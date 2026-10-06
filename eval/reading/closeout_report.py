"""Publish completed close-out evidence; refuse partial runs or unadjudicated silent errors."""
import json
from collections import Counter
from pathlib import Path

from eval.reading.closeout import OUT, REPO
from eval.reading.scan_report import aggregate, _table


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _subset_label(subset):
    return 'dev_check (seen)' if subset=='dev_check' else subset


def publish():
    sets={s:load(OUT/'final'/f'{s}.json')['pages'] for s in ('dev_tune','dev_check','holdout2','real')}
    assert {s:len(p) for s,p in sets.items()} == {'dev_tune':20,'dev_check':11,'holdout2':30,'real':6}
    freeze=load(REPO/'reports/step4c-run-freeze-v3.json')
    assert all(p['fingerprint']==freeze['final_run_fingerprint'] for ps in sets.values() for p in ps), 'All final pages must use the same pre-holdout freeze'
    for subset, pages in sets.items():
        for page in pages:
            key=f"{page['doc_id']}_p{page['page_index']:04d}"
            assert all((OUT/'final'/subset/(key+suffix)).is_file() for suffix in ('.json','.png','.md','-report.md')), 'Missing final page export: '+key
    adjudication=load(REPO/'reports/step4c-closeout-adjudication.json')
    cases=adjudication['cases']
    raw={(s,p['doc_id'],p['page_index'],tuple(d['where']),d['got'])
         for s,ps in sets.items() if s!='real' for p in ps for d in p['number_problems']
         if d['status'] in ('wrong','inserted') and not d['flagged']}
    judged={(c['subset'],c['doc_id'],c['page_index'],tuple(c['where']),c['got']) for c in cases}
    assert raw==judged and all(c['judgment'] in ('reader_error','reference_artifact') and c['reason'] for c in cases)
    reader_errors=Counter(c['subset'] for c in cases if c['judgment']=='reader_error')
    passed=reader_errors['holdout2']==0
    gate='PASS' if passed else 'FAIL — BLOCKED-ON-OWNER'
    summary={s:aggregate(p) for s,p in sets.items() if s!='real'}
    table=[('A1','DONE','30 صفحة/seeds جديدة للـ OCR، disjoint؛ f4d87a1 قبل الكود؛ test_holdout2_disjoint_from_previous_synthetic_pages'),
           ('A2','DONE','dev-check = seen في القواعد والتقارير، ومش gate'),
           ('B1','DONE','rapid-layout 1.2.1 + model size/hash مطابقين؛ egress smoke 3.53s؛ 3c1f3a4'),
           ('B2','DONE','regions/captions/furniture/table-only؛ test_header_footer_and_caption_are_kept_out_of_body_or_preserved، test_repeated_margin_furniture_does_not_enter_prose'),
           ('B3','DONE','تدوير وإعادة قراءة بالقارئين؛ test_undetected_vertical_layout_region_is_rotated_and_second_read، test_nonmargin_rotated_number_requires_agreement_after_rotation'),
           ('B4','DONE','3 PNG crops أصلية + regression tests + إعادة قياس tune؛ تفاصيل معالجة التلاتة تحت'),
           ('C1','DONE','test_header_footer_and_caption_are_kept_out_of_body_or_preserved يمنع Page ii في prose'),
           ('C2','DONE','test_code_columns_do_not_trigger_text_table_alarm؛ consistency في table regions بس'),
           ('C3','DONE','0.99993 wrong؛ bar 1.0؛ all default حتى score 1.0؛ توقيت تحت؛ ADR-0005'),
           ('C4','DONE','19 tune فقط، threshold 2.0؛ step4c-denoise-selection.json؛ d5fe844'),
           ('C5','DONE','d5fe844 ثم2abd37b (margin fragments) ثمcbc5724 (duplicate detections)، tune-only؛ test_ocr_rules_frozen؛ كلهم قبل holdout'),
           ('D1','DONE','sample mode: 180 رقم بس؛ seed 20261006؛ freeze commit 477e4c7؛ crop/context، keyboard، auto-advance وحفظ GT بعد كل إجابة؛ sample_ui_test.js وtest_real_sample.py'),
           ('D2 — sampled GT complete','BLOCKED-ON-OWNER','راجعي العينة الثابتة 180 رقم؛ مفيش full-page review؛ لسه 0/180؛ GAO إضافة منفصلة 30 رقم لما الملف يوصل'),
           ('D3','BLOCKED-ON-OWNER','GAO 403 ×3؛ الملف لسه مش موجود؛ بعد verify والقراءة نضيف 15 flagged + 15 accepted بنفس seed method من p4/p37/p39، ونثبت الإضافة في commit قبل مراجعتها'),
           ('D4 — measured on sample','BLOCKED-ON-OWNER','بعد D2: real.measure → false-alarm share مع Wilson 95%، silent-error rate مع exact upper 95% و3/n عند صفر أخطاء؛ illegible منفصل، breakdown لكل صفحة؛ GAO مش بيمنع قياس العينة الأصلية'),
           ('E1','DONE','CLI + read_pdf.ps1؛ digital/scan/layout/test refusal/output paths؛ test_cli.py + test_closeout_e2e.py'),
           ('E2','DONE','generated digital + image-only + verified NBS real page؛ markers/report/overlays؛ test_closeout_e2e.py'),
           ('E3','DONE','outline من غير fill، legend موسعة؛ test_scan_overlay_preserves_character_pixels_and_keeps_legend'),
           ('F1','BLOCKED-ON-OWNER','20 tune + 11 seen + 30 holdout مقاسين ومحكّمين، وتوقيت 6 real؛ مقاييس عينة real مستنية D4'),
           ('F2','DONE' if passed else 'BLOCKED-ON-OWNER',f'{gate}؛ raw {summary["holdout2"]["silent_errors"]}، reader-attributed {reader_errors["holdout2"]}؛ لا tuning بعد القياس'),
           ('F3','DONE','docs/adr/0005-ocr-stack.md؛ الأسباب والبدائل المرفوضة'),
           ('F4','DONE','docs/ocr_setup.md + UTF-8 locks + step4c-environment.json؛ versions/full hashes/Ubuntu commands'),
           ('F5','DONE','PRE_DELIVERY_CHECKLIST.md: allowlist/signing، pymupdf-layout review، Linux parity، GPU readers'),
           ('F6','DONE','التقرير ده + JSON evidence، metrics/ablations/تحكيم/توقيت/كل الحالات'),
           ('F7','DONE','full suite result تحت؛ slow tests registered؛ HANDOFF آخر تحديث؛ الخطوة التالية المخططة Step R (Reading v1) بعد إغلاق owner blockers'),
           ('GPU readers','DEFERRED','PaddleOCR-VL + reader 3 → جهاز GPU'),
           ('Paddle parity','DEFERRED','Paddle vs RapidOCR → Linux'),
           ('Reading structure','DEFERRED','section trees/document.json/chunks → Step R'),
           ('Table structure','DEFERRED','structure/TEDS → Step 4d / R4'),
           ('Arabic OCR','DEFERRED','→ R9')]
    def close_table():
        return ['| البند | الحالة | الدليل / المطلوب |','|---|---|---|']+[f'| {a} | {b} | {c} |' for a,b,c in table]
    lines=['# Step 4c — ملخص الصبح والإغلاق','',
           '**اتعمل:** layout + rotate/re-read + adaptive denoise، اختبارات الأخطاء التلاتة، one-command reader، مراجعة GT offline بالعينة: 180 رقم (80 flagged + 100 accepted) في ترتيب مخفي وعشوائي، القياسات الصناعية والتحكيم، وتوثيق الـ stack. الـ downloads اقتصرت على الموافقات. مفيش test split اتقري ولا history اتعاد.','',
           '**مستنيكي:** Step 4c لسه مش مقفول؛ D2/D3/D4 وجزء real من F1 محتاجينك.','',
           '1. افتحي `eval/reading/real/review.html` في Chrome أو Edge. اكتبي اسمك، واضغطي `Choose existing gt folder` واختاري `eval/reading/real/gt` واسمحي بالكتابة. هتشوفي رقم واحد في كل مرة، crop كبير وسطر السياق؛ الحالة flagged/accepted مخفية.',
           '2. الكيبورد: 1 = reader-1 صح؛ 2 = reader-2 صح؛ 3 = embedded layer صح لما تكون موجودة (لو أكتر من قيمة، اختاري الصح)؛ T = اكتبي القيمة واضغطي Enter؛ X = غير مقروء وممنوع التخمين؛ Backspace = ارجعي. للكشف المكرر/الجزئي أو اللي مش رقم استخدمي `Not a number`. الحفظ في GT JSON بعد كل إجابة قبل الانتقال؛ للرجوع اختاري نفس المجلد. مفيش مراجعة للصفحة كلها ولا GT متعبّي مسبقًا.',
           '3. بعد الـ180 إجابة: `.venv\Scripts\python.exe -m eval.reading.real.measure` → `out/reading/step4c-closeout-final-v3/real-sample-metrics.json` و`reports/step4c-sample-metrics.md`. غير المقروء خارج المقام؛ لو صفر أخطاء و100 legible accepted، exact upper = 2.95%، وتقريب 3/n = 3%.',
           '4. GAO p4/p37/p39 مستني الملف اليدوي بنفس URL/hash/size المعتمدين. بعدها verify → reader → `sample extend-gao` → commit للإضافة قبل مراجعتها → regenerate review. الإضافة 15 flagged + 15 accepted منفصلة؛ الـ180 الأصلية وترتيبها مش بيتغيروا. التفاصيل في `reports/step4c-sampling.md`.', '',
           f'**نتيجة الـ gate:** {gate}. holdout-2: raw silent errors **{summary["holdout2"]["silent_errors"]}**؛ reader-attributed بعد التحكيم **{reader_errors["holdout2"]}**. flag rate **{summary["holdout2"]["flag_rate"]}**؛ false-alarm share **{summary["holdout2"]["false_alarm_rate"]}**.']
    if not passed:
        lines+=['**القرار المطلوب:** راجعي حالات holdout-2 في جدول التحكيم والصور، وقرري قبول الخطر الموثّق أو ترخيص جولة إصلاح وholdout جديد. مفيش أي tuning اتعمل على النتيجة دي.']
    lines+=['','جدول الإغلاق لحد دلوقتي:','']+close_table()+['','## قواعد القياس والأدلة','',
             'A1 اتثبت في f4d87a1 قبل أي كود close-out: 10 صفحات لكل dev document، طبقات metadata، seeds جديدة، خارج الـ31 صفحة القديمة. صفحات المستندات اتقرت digitally قبل كده في 4b؛ ده holdout للـ OCR الصناعي، مش مستندات مستقلة. dev-check seen تشخيصي بس. Freeze d5fe844 ثم2abd37b لتصليح fragmented margin stamp على dev-tune بس؛ runner fix 01d4501 وoverlap guard cbc5724 (WB p10 tune-only) قبل فتح holdout. الـ core ثابت منcbc5724.','',
             'كل تشغيل final له checkpoint ببصمة code/rules. الدليل الحالي في `out/reading/step4c-closeout-final-v3/final/`. أول checkpoint tune قبل إصلاح توصيل embedded layer محفوظ في `out/reading/step4c-closeout/final/` ومش داخل النتائج. اختيار denoise محفوظ في المجلد القديم؛ جولة dev-tune قبل overlap guard محفوظة في `out/reading/step4c-closeout-final-v2/final/` كمان. checkpointات محاولة القياس قبل margin fix كمان محفوظة في `out/reading/step4c-closeout-final/final/` ومش داخل القياس النهائي. مفيش حذف/إعادة كتابة لأي run قديم.','',
             'تعريفات المقاييس القديمة ثابتة: كل رقم مطبوع ضمن raw GT حتى figures/furniture؛ الأرقام المستبعدة دلاليًا بتتحسب flagged. false-alarm share = correct flagged / all flagged؛ ده مش معدل الخطأ على كل الأرقام الصحيحة. correct numbers المستبعدة من prose ممكن تعلي الرقم ده لأسباب سليمة. الـ real sample بيقيس false-alarm share على flagged وسرية الأخطاء على accepted؛ مفيش ادعاء population FPR أو recall للأرقام الناقصة. page quotas متناسبة مع minimum 5 حيث متاح؛ Wilson/exact binomial ملخصات للعينة تحت binomial model، مش exact design-based population intervals؛ weighted point estimates منفصلة. التفاصيل في step4c-sampling.md.','',
             '## Synthetic — full بالقواعد الحالية','']+_table([(_subset_label(s),summary[s]) for s in summary],'subset')
    lines+=['','## حسب النوع — full (الأنواع ممكن تتداخل)','']
    lines+=['accuracy والـ false-alarm share الصناعية فوق وتحت من المرجع الرقمي الخام بنفس scoring المجمّد؛ التحكيم بيحدد reader-attributed gate بس، ومش بيعيد كتابة accuracy أو matching. flag rate من flags الفعلية على الأرقام المكتشفة.','']
    for s in summary:
        kinds=sorted({k for p in sets[s] for k in p['kinds']})
        lines+=_table([(_subset_label(s)+' / '+k,aggregate([p for p in sets[s] if k in p['kinds']])) for k in kinds],'subset / kind')+['']
    lines+=['## توزيع flags الدلالية — full','', '| subset | role | tokens | flagged |','|---|---|---:|---:|']
    for s in summary:
        tokens=[t for p in sets[s] for t in p['tokens']]
        for role in sorted({t['role'] for t in tokens}):
            ts=[t for t in tokens if t['role']==role]
            lines.append(f'| {_subset_label(s)} | {role} | {len(ts)} | {sum(t["flagged"] for t in ts)} |')
    code_page=next(p for p in sets['dev_check'] if p['doc_id']=='2601-14525v1' and p['page_index']==15)
    code_alarms=Counter(f['kind'] for f in code_page['flags'])
    lines+=['',f'C2 actual seen arXiv p15: text_table_mismatch **{code_alarms["text_table_mismatch"]}**؛ table_total_mismatch **{code_alarms["table_total_mismatch"]}**. القواعد ما اتعدّلتش من نتيجة seen دي.']
    lines+=['','## كل raw silent error — التحكيم البصري','',
             'كل clean original وdegraded scan اتراجعوا. WB p10 في الجولة قبل cbc5724 كان تكرار آخر 1 من FY2020/21: غلطة قارئ فعلية اتصلحت بفحص التداخل على dev-tune، والدليل محفوظ في المجلد v2. ما اتغيّرش reader/rule بعد فتح holdout. التفاصيل وبصمات الصور في `step4c-closeout-adjudication.json`؛ الصور المحلية في `out/reading/step4c-closeout-final-v3/adjudication/`. الحالة غير الواضحة تتحسب reader error، مش نجاح مفترض.','',
             '| subset / case | page | expected → got | الحكم | سبب من الصورة | crop |','|---|---|---|---|---|---|']
    for c in cases:
        crop=Path(c['image']).as_posix()
        lines.append(f'| {_subset_label(c["subset"])} #{c["id"]} | {c["doc_id"]} p{c["page_index"]} | `{c["expected"]}` → `{c["got"]}` | {c["judgment"]} | {c["reason"]} | [crop](<{crop}>) |')
    if not cases:lines+=['| كل الـ subsets | — | — | مفيش raw silent errors | — |']
    lines+=['','## إعادة قياس الأخطاء الأصلية التلاتة — dev-tune','',
            '| الحالة الأصلية | reader-1 النهائية في مكانها | role | flagged |','|---|---|---|---|']
    regressions=[('2601-14525v1',0,'2',(25,511),'arXiv stamp'),
                 ('wb-eem-2021-12',14,'20',(420,702),'WB Dec-20 axis'),
                 ('wb-eem-2021-12',31,'8',(179,561),'WB scatter dots')]
    for doc,index,value,center,label in regressions:
        row=next(p for p in sets['dev_tune'] if p['doc_id']==doc and p['page_index']==index)
        near=[t for t in row['tokens'] if t['token']==value and
              abs((t['bbox'][0]+t['bbox'][2])/2-center[0])<15 and
              abs((t['bbox'][1]+t['bbox'][3])/2-center[1])<15]
        assert near and all(t['flagged'] for t in near), 'Original regression must never be accepted: '+label
        lines.append(f'| {label} | '+', '.join(t['token'] for t in near)+' | '+', '.join(t['role'] for t in near)+' | True |')
    lines+=['','| subset | raw | reader-attributed | reference artifacts |','|---|---:|---:|---:|']
    for s in summary:
        lines.append(f'| {_subset_label(s)} | {summary[s]["silent_errors"]} | {reader_errors[s]} | {summary[s]["silent_errors"]-reader_errors[s]} |')
    lines+=['','الـ silent drops الخام متسجلة في metrics/per-page JSON؛ نجاح silent-error gate مش ضمان إن كل رقم اتكشف. مفيش تعديل على تعريف matching عشان ننقص الرقم.','',
             '## Ablations والقرارات','',
             'الجدول التالي **قياسات 4c القديمة** على الـ31 صفحة (median3×3، قبل layout/rotation). محفوظ للمقارنة التاريخية؛ مش قياس جديد للقواعد النهائية ومش holdout-2. no_deskew/no_denoise/reader1-alone مش configs production.','']
    old=[]
    for config in ('full','no_deskew','no_denoise','reader1_alone'):
        for s in ('dev_tune','dev_check'):
            old.append((config+' / '+s+(' (seen)' if s=='dev_check' else ''),aggregate(load(REPO/'out/reading/ocr'/config/f'{s}.json')['pages'])))
    lines+=_table(old,'historical config / subset')+['',
             'Adaptive vs no-denoise اتقاسوا fresh على نفس الـ20 tune، واختيار threshold على19 فقط من غير GAO p12. أعلى exact number accuracy اختار **2.0**؛ بيحسّن الأرقام لكنه بيضر CER مقارنة بعدم الفلترة. تفاصيل كل candidate في `step4c-denoise-selection.json` و`step4c-denoise.md`. مفيش tuning من seen/holdout.','']
    denoise=load(REPO/'reports/step4c-denoise-selection.json')
    lines+=['اختيار denoise كان reader-1-only؛ الأرقام كلها flagged لغياب consensus، فـ silent errors في جدول المعايرة مش gate. معيار الاختيار exact number accuracy، مع CER كدليل على المقايضة.','']
    lines+=_table([(f'T={r["threshold"]}',r) for r in denoise['candidates']]+[('no denoise',denoise['no_denoise'])],'tune-only candidate')
    lines+=['','قرار C3: رقم غلط confidence **0.99993**؛ bar ثابت **1.0** وdefault **all**، حتى الرقم score=1 بيتقري تاني. GLM من عائلة مختلفة، بس الاتفاق ممكن يكون غلط عند الاتنين؛ layout/rotation بيحموا من 3 correlated failure modes. GPU متوقع يسرّع calls، من غير قياس أو وعد زمن. ADR-0005 فيه البدائل المرفوضة.','',
             '## التوقيت لكل صفحة والـ real reads','',
             'الثواني without/with هي preprocess + reader1 + second reads حسب سجل inference؛ cached GLM بياخد زمن inference الأصلي. wall هو الزمن الفعلي من بداية الصفحة لحد نهاية القراءة وإعادة preprocess، وبيستفيد من cache؛ فيه rendering والتدوير الإضافي، لكنه قبل scoring وكتابة PNG/Markdown. layout جزء من reader1 wall، ظاهر منفصل للتشخيص ومش بيتجمع مرتين. Ollama ps أكد GLM 100% CPU على اللابتوب؛ GPU غير مقاس. بعض صفحات tune الأولى اتقاست بالتزامن مع full suite؛ wall يوضح الكلفة الفعلية، مش مقارنة أداء معزولة.','',
             '| subset | page | GT | exact accuracy | raw silent errors | silent drops | flag rate | false-alarm share | preprocess s | layout s | without r2 s | with r2 s | actual read wall s |','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s,ps in sets.items():
        for p in ps:
            if s=='real':v=['BLOCKED']*4+[f'{p["flagged_tokens"]/max(p["reader1_tokens"],1):.4f}','BLOCKED']
            else:
                a=aggregate([p]);v=[a[k] for k in ('numbers','accuracy','silent_errors','silent_drops','flag_rate','false_alarm_rate')]
            t=p['timing'];v+= [f'{x:.2f}' for x in (t['preprocess'],p['layout_seconds'],t['without_second_reads'],t['with_second_reads'],p['wall_seconds'])]
            lines.append(f'| {_subset_label(s)} | {p["doc_id"]} p{p["page_index"]} | '+' | '.join(map(str,v))+' |')
    lines+=['','**Real sampled rates: BLOCKED-ON-OWNER**؛ sample review فيه 180 رقم بس من الست صفحات، ثابت في477e4c7. NBS وStatAb hash-verified؛ GAO مش موجود وإضافته30 رقم معلقة. GT templates لسه غير معدّلة؛ full-page status هيفضل template، وإجابات العينة تتسجل في sample_reviews بس. مفيش ادعاء full-page accuracy/CER/WER أو missed-number recall؛ table structure/TEDS مؤجل لـ4d/R4.','',
             '## التثبيت والاختبارات والحدود','',
             'rapid-layout **1.2.1** offline wheels ثم no-index؛ كل pins القديمة ثابتة. PP-DocLayoutV2 **213,963,993 bytes**، sha256 `0bd2ea0997fe0789f0300292291f8bbf897d890b44a9a3bd5be72afd6198aa90` مطابق للتقرير وdefault_models.yaml. GLM blob **2,219,298,752 bytes**، sha256 `65493e1f85b9ea4ba3ed793515fde13cbdbea7d74ad2c662b566b146eab0081e` اتراجع محليًا. hashes كاملة لكل نموذج/lock في `step4c-environment.json`؛ pip check سليم.','',
             'GAO رجع403 في3 محاولات؛ مفيش file اتكتب أو بديل اتنزّل. الأمر المعتمد من root المشروع:','',
             '```powershell',
             "Invoke-WebRequest -Uri 'https://www.gao.gov/assets/Comptroller%20General%27s%201990%20Annual%20Report.pdf' -OutFile 'eval/reading/real/incoming/gao_cg_annual_report_1990.pdf'",
             "Get-FileHash 'eval/reading/real/incoming/gao_cg_annual_report_1990.pdf' -Algorithm SHA256",
             '.venv\Scripts\python.exe -m eval.reading.real.verify',
             '.venv\Scripts\python.exe -m eval.reading.closeout --subset real',
             '.venv\Scripts\python.exe -m eval.reading.real.review','```','',
             'GAO expected SHA256 `71586b0afcd7ff14955e2f5c4dd8645e94809fca99e525761267577805b2b57a`، size 9,297,136 bytes. mismatch: الملف الجديد بس يتشال ويتسجل؛ ممنوع substitution.','',
             load(REPO/'reports/step4c-test-evidence.json')['summary'],'',
             'أداة Browser Use رفضت معاينة `file://` بسبب سياسة تسمح HTTP/HTTPS بس ومنعت workarounds. مفيش تجاوز أو server اتعمل. JavaScript syntax/DOM tests نجحوا؛ المعاينة البصرية الكاملة للأداة ضمن المطلوب منك في D2.','',
             'الإغلاق الكامل لسه مستني البنود BLOCKED. الخطوة التالية **المخططة** Step R (Reading v1)، بعد إغلاق Step4c بقرارك وGT الحقيقي. كل التأجيلات تحت من القائمة المسموحة بس.','',
             '## Close-out table — كل بند وحالته','']+close_table()
    artifact={'gate':gate,'final_core_freeze':freeze['final_core_freeze_commit'],
              'final_fingerprint':freeze['final_run_fingerprint'],
              'timing_definition':'wall_seconds stops after reading and the second preprocess, before scoring/export; with/without-second-read estimates use recorded inference time (including cached original GLM time). Extra reader1 rotation reads are included in wall_seconds.',
              'reader_attributed_errors':{s:reader_errors[s] for s in summary},'synthetic':summary,
              'evaluation_labels':{s:_subset_label(s) for s in summary},
              'page_records':{s:[{k:v for k,v in p.items() if k not in ('tokens','lines','layout','text_layer')} for p in ps] for s,ps in sets.items()},
              'closeout':[{'item':a,'state':b,'evidence':c} for a,b,c in table]}
    (REPO/'reports/step4c-closeout-metrics.json').write_text(json.dumps(artifact,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    (REPO/'reports/step4c-final.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Published reports/step4c-final.md; '+gate)


if __name__=='__main__':
    publish()
