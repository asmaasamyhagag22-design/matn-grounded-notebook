# R-lite — من القراية لنص ينفع يتراجع ويتستشهد بيه

R-lite بياخد Blocks القارئ المجمّد ويطلع elements، شجرة sections، tables، chunks و`document.json`. الشغل ده deterministic: مفيش LLM، embeddings، شبكة، تنزيلات أو dependencies جديدة. السبب إن الاستشهاد لازم يرجع لنص موجود ومكان معروف، والأرقام لازم تتنقل بالكود بدل ما model يعيد كتابتها.

بناء structure ما بيصلّحش نص snapshot ولا بيغيّر رقم. تغييرات القارئ الرقمية المحدودة في R-lite.1 وR-lite.2 اتوافقت بالاسم وليها fingerprint جديد؛OCR/rules ثابتين. acquisition المعتمد قرا الـ3 dev documents مرة واحدة، وسجّل routes قبل OCR، واستخدم 8 صفحات من الحد العالمي10 تحت egress guard. باقي البناء بيستخدم cache. الـ6 real-scan pages اتعمل لها replay؛ مفيش OCR جديد ليها. Test split مقفول.

## تشغيل وإعادة بناء

```bash
.venv/bin/python -m matn_reading read source.pdf --out out/source
.venv/bin/python -m matn_reading read source.pdf --out out/source --structure-only
.venv/bin/python -m eval.reading.r_lite
```

`--structure-only` ما بيفتحش PDF وما بيشغّلش القارئ أو OCR. بيقرأ snapshot الموثّق بالـSHA256 ويعيد البناء. الـentry point في `matn_reading/__main__.py` و`structure/cli.py`؛ `matn_reading/cli.py` المجمّد فضل زي ما هو بقرار المالكة. الـacquisition cache مرتبط بـPDF hash + frozen core fingerprint + OCR configuration؛ ده يمنع خلط قراءات من نسخ مختلفة.

## العقود

`DocumentStructure` بقى `schema_version: 2` في R-lite.2؛باقي العقود `schema_version: 1` في `matn_contracts/structure.py`، والـJSON Schema snapshots في `schemas/contracts/structure/`. الـBlock الأصلي بيفضل بعقده القديم من غير تغيير enums أو fields.

| عقد | أهم fields | ليه والـinvariants |
|---|---|---|
| Element | block، role، citable، exclusion_reasons، flags، source_spans، number_tokens، bbox، reader_frame | يحتفظ بالنص الأصلي وقرار استبعاده. كل span جوه النص، وكل bbox موصوف الدقة. |
| Section | section_id، parent_id، child_ids، level، path، source، heading_block_id، block_ids، page_range | internal node ما يملكش blocks؛ كل citable block له leaf واحدة، عشان chunk ما يعبرش section. |
| Table | table_id، pdf_page_index، bbox، block_ids، structure، unavailable_reason، rows، cols، header_rows، cells | available لازم grid صالح؛ unavailable لازم reason وخلايا فاضية. مفيش خلية متخمنة. |
| TableCell | row، col، row_span، col_span، text، bbox، source_spans، numeric_tokens، is_header | bbox جوه region، مفيش grid assignment مكرر، والنص مرتبط بمصدره. merged bounds المبهمة بتخلي البنية unavailable. |
| Chunk | chunk_id، section_id، kind، text، context_prefix، offset_map، primary، repeated_context، sentence_spans، numeric_tokens، prev/next_chunk_id، word_count، flags، table_id، row_range | retrieval unit مستقلة عن citation. map يعيد نفس النص حرفيًا، وneighbors في نفس section. |
| DocumentStructure | doc_id، title، producer_versions، reader_fingerprint، coordinate_convention، pages، elements، sections، tables، chunks، excluded_blocks، issues، coverage، coverage_summary | يجمع provenance graph؛ ids وعلاقات الشجرة وسبب كل استبعاد بيتراجعوا. |

`BlockSpan` و`PrimarySpan`: block_id، start، end، boxes. الـoffsets Unicode code points، والـend مش داخل المدى. `RepeatedContextSpan` بيزود primary_chunk_id. `OffsetSpan` نوعه primary/repeated_context/separator. `SentenceSpan` له start/end/flags جوه الـchunk.

`BBoxRef`: coordinates، bbox_precision (`char | word | line | region`)، frame، interpolated. النقاط PDF points، origin أعلى شمال MediaBox، x لليمين وy لتحت. كل صفحة لها size، cropbox، rotation، pdf_page_index وpage_label لو الـPDF محدده. `reader_points` للـbbox الأصلي في ledger؛ boxes الاستشهاد في `pdf_points` بعد التحويل.

## مين ينفع يتستشهد بيه؟

Visible body prose، headings، list items، captions، footnotes وtable text ينفعوا. Hidden/uncertain visibility، figure_text، running headers/footers، marginalia وأرقام الصفحات ما ينفعوش. كل excluded block متسجل في `excluded_blocks` مع الأسباب؛ مفيش حذف صامت. Role القارئ محفوظ حتى لو فيه finding على classification بتاعه.

لما layout words يركبوا النص حرفيًا، كل span بياخد word boxes. لو النص مش متطابق، النص بياخد region precision وfinding واضح. ده يمنع ادعاء إن عندنا char geometry وإحنا ما عندناش. الـdigital number اللي له link دقيق له word geometry؛ لو ملوش link دقيق بيستخدم القرار الإضافي المعتمد `digital-unlinked`.

## الأرقام: status مش ختم تحقق

`NumberTokenRef` يحتفظ بـtext، block span، chunk span، page، bbox وreader_source؛ ولو linked يحتفظ بـreader_ref، reader_status، reader1، reader2، reasons وreader_bbox الأصلي. أي تغيّر في value/status/geometry ledger يفشل G2. كل primary numeric span لازم يظهر مرة واحدة؛ repeated headers ممكن تعيد نفس token كـcontext.

| status | reader_source | معناه للـverifier |
|---|---|---|
| digital | digital | نص رقمي من القارئ الرقمي وله source word/char geometry؛ مش OCR consensus، ومش ادعاء تحقق مستقل. |
| accepted | ocr | OCR reader ما علّمش الرقم؛ ده قرار القارئ، مش ضمان صحة الرقم. |
| flagged | ocr | linked والـreader شايف uncertainty؛ values/reasons محفوظين. ممنوع اعتباره verified. |
| flagged-unlinked | ocr | مفيش unique reader-token link. النص محفوظ، بس مفيش verdict أو values متخيلين. ممنوع verified. |
| digital-unlinked | digital | إضافة اعتمدتها المالكة أثناء التقييم: مفيش exact unique source-word link. coarse geometry، reason واضح، من غير reader values/ref. ممنوع verified. |

آخر حالتين بيتعدّوا ويتسجلوا كلهم بالصفحة وblock_id وspan في `out/r-lite/metrics.json`. خلايا بأرقام unlinked ما ينفعش تستخدم لـcharts/KPIs. R-lite عمره ما يحوّل flagged لaccepted أو يعيد كتابة رقم.

OCR checkpoints بتحتفظ بحجم الصورة، cropbox وdeskew. التحويل بيرجع corners للإطار الأصلي بـ72/300 ونفس مركز دوران PIL؛ مفيش rescaling تخميني. الـbbox الأصلي اللي القارئ interpolated جوه word محفوظ وعليه `interpolated: true`؛ highlight بياخد word box الحقيقي، مش char box متخيل. الـ6 صفحات اتراجعت metadata بتاعتها قبل replay، وtoken bytes فضلت متطابقة.

## Sections وtables

الأولوية PDF outline مطابق لـheading block، بعده layout heading/numbering في prose، بعده windows ثابتة3 صفحات. كل node له source. unmatched bookmarks، level jumps، fused headings والـheading اللي مفيهوش عنوان مفهوم findings، بالصفحة وblock_id لما موجود. Parent introduction يبقى leaf مستقلة عشان الملكية ما تتكررش. `$` لوحده ما يبقاش section title؛ numbered table rows ما تتحولش headings. النص نفسه ما بيتغيّرش.

Captions وfootnotes تابعين للـsection اللي ماسكاهم في reading order، وكل واحد chunk مستقل. لو outline مش موجود أو جزء منه مش مطابق، layout anchors تكمل مع تسجيل mismatches.

Digital cells بتتقرأ بـpdfplumber داخل frozen table regions باستخدام القواعد الافتراضية. OCR cells بتتعمل بس لو row bands وcolumn assignments واضحة من geometry. Bounds مدمجة/مفقودة، source ambiguous، totals mismatch أو region ownership مبهم => unavailable مع reason. مفيش text strategy أو heuristic recovery. الـtable text يفضل citable. لو regions اتداخلت ومفيش region ownership فريد، blocks تتنقل مرة واحدة كـtable chunks والبنية المبهمة متسجلة unavailable؛ ما نخمنش region.

Structured table بتتقسم row groups، وheader rows تتعاد كـrepeated_context بعد أول ظهور primary. ده يخلي السياق مقروء من غير ما يضاعف ملكية الحروف. Interstitial reader characters زي pipes والمسافات محفوظة، ومعاها synthetic cell/row separators منفصلة في الـmap.

## Chunks، الجمل، والاستشهاد

Body target250 words، hard max350، باستخدام `whitespace-v1`: عدد `text.split()`، من غير tokenizer. الأرقام ثابتة قبل قياس gold. Chunk ما يعبرش section، مفيش overlap، والـremainder أقل50 words يندمج بس لو نفس section وبحد350. Sentence أطول350 تفضل كاملة في chunk عليها `single_sentence_overflow`. مفيش intra-sentence cuts. ده يحافظ على المعنى؛ 350 كلمة مش ضمان512 tokens، وده محتاج تحقق في خطوة verifier.

Splitter rule-based بيحمي decimals، e.g./U.S./Fig./No.، percentages، ranges وlist numbering. Block boundary hard sentence boundary؛ cross-block continuation معطل في v1. السبب إن joining نصين ممكن يختلق جملة غير موجودة بالمصدر.

`text` فيه synthetic `\n\n` بين blocks في body/caption/footnote، و`\t` بين cells و`\n` بين rows في table. الـmap يسجل كل separator من غير source span. Separators ما تتستشهدش بيها ومش جزء من primary partition. `context_prefix` عنوان المستند + section path، منفصل عن text وللاستخدام اللاحق في embedding بس.

Citation يتخزن `block_id + [start,end)`، مش chunk_id. لو retrieval جاب chunk، `resolve_citation` يرجع block spans؛ separator hit بيرفض الطلب. repeated_context hit بيرجع primary_chunk_id والموقع الأصلي. بعد كده Element.source_spans توصل للصفحة والـbbox بدقته المعلنة. Sentence spans تبين مكان الجملة جوه chunk، فالـchain يبقى chunk → sentence → block span → page → bbox.

## IDs وملفات الـrun

Section/table/chunk ids: `{doc_id}:s:<16hex>` / `:t:` / `:c:`. Hash على canonical sorted JSON وproducer version. نفس PDF ونفس versions والـsnapshot => نفس bytes وids. Re-chunking ممكن يغيّر chunk ids؛ block citation يفضل صالح طول ما frozen reader input ثابت. Run timestamps في manifest بس.

تحت `runs/<doc_id>/`:

1. `00_reading.json` + `.sha256`: frozen reader snapshot + additive metadata/cell observations.
2. `01_elements.jsonl`: النص والـprovenance/الاستبعادات.
3. `02_sections.json`: الشجرة والملكية.
4. `03_tables.json`: cells أو unavailable/reason.
5. `04_chunks.jsonl`: retrieval text والخرائط والجمل والأرقام.
6. `05_document.json` و`document.json`: التجميع النهائي بنفس bytes.
7. `06_run_manifest.json`: وقت التشغيل، cache key وhashes؛ خارج determinism comparison.

## التحقق وحدوده

G1a بيجمع primary intervals لكل block، يرتبها من غير dedup، ويبدأ cursor=0: كل start لازم يساوي cursor؛ أقل = overlap، أكبر = gap؛ وآخر end لازم يساوي len(Block.text)، بما فيها source whitespace. repeated_context وsynthetic separators ما يدخلش في الـpartition. G1b يراجع leaf ownership لوحده.

G2 يعيد text من typed map بما فيها separators، ويفحص sentence bounds وكل numeric ledger/disposition. G3 يراجع مصدر كل حرف: صفر forbidden blocks، وseparators هي الحروف الوحيدة غير المسندة. G5 يقارن كل ملفات structure في عمليتين Python؛ manifest مستثنى. G6 يراجع sizes والـoverflows: count/max/cause/chunk ids/pages. G7 يراجع cells/grid/bounds/source numbers والـtable-total check المجمّد؛ unavailable لازم reason.

G4 يستخدم `eval.normalize` المجمّد على dev gold بس. الموجود يتحسب single chunk أو two adjacent أو other split؛ المفقود يتصنف reader_text/wrongly_excluded_block/normalization. مفيش tuning على القياس. التقرير الفعلي في `reports/r-lite.md`؛ النقص في gold أو كثرة unavailable مش بيتخبوا. شجرة كل dev في `out/r-lite/<doc>/tree.txt`، وcontact sheet واحدة في `out/r-lite/table-contact-sheet.png`.

## R-lite.1: ليه الشجرة والنص اتغيّروا؟

A1 بيقبل section anchor من outline مطابق، أو حجم >=1.15 من body، أو reader heading على سطر مستقل. Fragment بنفس baseline جنب body ما يعملش section جديدة؛ TOC dot leaders والعناوين البريدية ما تعملش anchors. المرفوض يبقى Element.role=text ومعاه heading_demoted/page/block_id؛ Block الأصلي محفوظ. الهدف إن bold وسط الجملة ما يقطعش evidence أو chunk.

A2 الـopening leaf بياخد عنوان ومسار الأب؛ synthetic_opening متسجل في Section.issues، باستخدام العقد الحالي. مفيش عنوان Introduction مخترع، ومفيش تكرار لعنوان الأب في context_prefix. ده يمنع سياق embedding يوحي بعنوان مش موجود في المصدر.

A3 كل numeric string بيتربط بالـk-th reader occurrence بنفس النص وفي ترتيب words، بشرط العددين متساويين. اختلاف العدد يفضل digital-unlinked بسبب source_numeric_occurrence_count_mismatch؛ حتى تطابق الحروف المجمّعة ما يتجاوزش الشرط. السبب إن bbox مقنع مش دليل على وجود reader token مطابق؛ الرقمان المتكرران لازم يوصلوا لخليتين مختلفتين بأمان.

B0 التجمع الرسومي اللي فيه rotated/reversed axis labels يفضل figure_text حتى لو pdfplumber اكتشف grid كجدول. النص المجاور خارج الرسم يفضل body. B1 font face/weight change عند body size ما يقطعش السطر أو الفقرة؛ same-baseline face boundary يسمح بحد2em، size tolerance0.6pt وbaseline0.2em، من غير تغيير قواعد visibility/gutters. Fixture فيها bold run مكتوب متأخر في PDF تختبر إن النص يرجع لمكانه في الجملة، مش آخر الفقرة. قبل inline-face join، التجميع الأصلي يكشف gutters بين multiline body blocks بنفس find_gutters والـthresholds القديمة؛ join ما يعبرهاش. Fixture ثانية بنفس17pt gap لكن عمودين مستمرين كانت حمراء ثم خضراء. ده يحمي column boundaries من غير تعطيل inline emphasis أو تعديل thresholds.

B2 filled prose box يحتاج >=3 horizontal body-size lines، >=80% منها فيها >=4 words، >=2 sentence endings، صفر rotated words، <=3 numeric-only label lines، ومن غير interior axis strokes طويلة>=30pt. Body-size tolerance0.6pt؛ المحور أرفع<=1pt وبعيد>3pt عن الحافة. Border decorations القصيرة ما تتحسبش axes. غير الواضح يفضل figure_text ومعاه possible_prose_in_figure؛ precision قبل recall، ومفيش thresholds متضبطة على dev.

B3 digital lexical line break زي end- +to-end يحتفظ بالـhyphen لما أول fragment في السطر التالي فيه hyphen. govern- +ment يفضل government، وOCR defaults ثابتة. ده إصلاح ضيق للكلمة المركّبة، مش سياسة dehyphenation جديدة.

Reader fingerprint جديد يعني caches جديدة؛ القديمة immutable. الـacquisition كاملة؛ subset reads بتاعة guards ممكن تغيّر body size/furniture وتجزئة word، لأن دول محسوبين على الصفحات المختارة. ما نخلطش subsets عشان نبني مستند كامل؛ G5 يقارن نفس snapshot ونفس page selection. Acquisition يعيد digital فقط وينقل صفحات OCR القديمة كاملة بلا worker/inference. G-R1 يقارن مجموعة raw silent items مع HEAD بنفس doc/page/token/reference bbox/reader bbox؛ bbox tuples/lists تتحول JSON arrays بلا rounding. G-R2 reader-attributed errors=0. arXiv p19 signed +30.45% artifact متراجع بصريًا من4b.2؛ raw1/1 منفصل عن reader-attributed0/0. أي raw item جديد أو مختلف يوقف الشغل.

القياس الجديد في reports/r-lite-1.md وreports/r-lite-1-diff.md؛ G4 مسمّى seen after R-lite diagnostics. Before/after block ids ممكن تتغير لما النص أو geometry تتغير؛ citations القديمة تخص الـsnapshot القديم، مش نسخة reader جديدة. Chunk target250/max350/tiny50/page-window3 والـgold normalization ثابتين.

## R-lite.2: الـPDF نفسه وضّح إيه؟

P1 اتعمل قبل أي إصلاح، من chars/fonts/sizes/baselines، ترتيب text objects، الـfilled rects والـregions. `reports/r-lite-2-p1.md` و`out/r-lite-2/p1-evidence.json` فيهم الصفحة وsplit وكل branch. Dev-tune فقط لفهم الميكانيزم وبناء fixture؛dev-check تقرير، مش مصدر thresholds. المالكة حددت دي آخر خطوة reading قبل RAG core.

M3 كان defect في provenance: B2 حوّل prose داخل خلايا GAO لمسار prose، لكن `_table_block` كتب **كل** خلايا pdfplumber فوق نص block اللي سجله فيه headings بس. نفس الممارسات اتنسخت مرتين، والنسخة الجدولية فيها31 رقم بلا source-word record محلي. الإصلاح بيخلي نص الجدول من الكلمات اللي اتجمعت فعلًا؛الخلايا ملاحظات structure منفصلة. مفيش نسخ نص من block تاني، ولا pipes متصنّعة جوا مصدر القارئ. لو ربط الخلية بالنص مش واضح، الجدول يفضل unavailable بدل geometry مضللة.

M2 في WB p18 مش bold متأخر: `account / deficit / widened` كلمات بخط عادي جوه نفس text object، والـPDF مبرر السطر بفراغات أكبر من1.5em. B1 كان بيسمح بالjoin لما font face يتغير، فمطبقش. الفراغات قسمت السطر، ورفض `_continues` ضم fragments على نفس baseline؛block الفقرة الأقدم ظهر قبل الكلمات المنفصلة. دلوقتي join ينفع لكلمات body على نفس baseline ليها **unique text-object membership**، من غير توسيع gap threshold. Visibility والـcolumn gutters لسه حدود؛heading مستقل وأكبر يفضل مستقل. Cache بيحتفظ بـfont_face وtext_object_id وvisibility_reasons كمعلومات إضافية للكلمات، من غير تعديل عقد Block. Object مبهم أو تداخل طبقات ما يتصلّحش بالتخمين.

M1 الـ20 C3 samples دخلت figure من sparse connected drawing rectangles مع >=4 numeric labels؛ده جمع مناطق prose كأنها chart. 13 samples عندها prose10.02pt جوه cells، لكن document body11pt، فشرط global font رفضها. الإصلاح يستخدم modal font داخل كل filled region بنفس tolerance القديمة0.6pt؛عدد السطور والكلمات ونهايات الجمل والـnumeric-label/axis/rotation gates ثابتة. أربع samples بلا filled rect مؤهل وثلاث headings قصيرة؛دي حدود معلنة، مش سبب لتوسيع recovery rule. Counter-case chart بمحاور داخلية لسه figure_text.

`coverage` في document v2 فيها record لكل صفحة: excluded_words_by_reason، possible_prose_in_figure_count/block_ids، suspected_order_break_count/block_ids، unlinked_numbers_by_disposition. `coverage_summary` لازم يساوي مجموع الصفحات. Counts الاستبعاد بتستخدم whitespace words؛الأسباب غير حصرية، فblock عليه سببين يتعد في الاثنين. Unlinked counts للأرقام في **citable** elements فقط. Counts الاستبعاد والأرقام لازم تطابق المصدر، مش مجرد مجموع شكله سليم.

صفر source-word deficits معناه إن canonical reader text بيتبني من سجله، مش شهادة إن ترتيب كل كلمة في الورق صحيح. WB p34 فيها footnotes مسترجعة ونص القارئ القديم خالط فيها Box/title text؛دي limitation ظاهرة في crops/report. Detector ترتيب M2 بيرصد splits بين blocks، مش كل فساد ترتيب جوه block واحدة. ومثال unlinked الجديد WB p16: `19 percent` له source word، لكن paragraph merge جمع معاه COVID- /19، فشرط A3 لعدد numeric occurrences رفض link. القيمة ما اتغيّرتش والflag ما اتشالش. جداول GAO structured بقت12 بدل19 لأن cells مبهمة ما تتربطش بالنص بالتخمين.

Detectors flags فقط: figure visible فيها >=4 words ممكن تحتوي prose؛وdetector ترتيب M2 يرصد split بين blocks على baseline واحدة عند wide gap أو visibility change، داخل column boundaries، خصوصًا لما object link مفقود. ده احتمال يحتاج مراجعة، مش حكم إن الشكل prose ولا تصريح باستخدام hidden/uncertain. ولا detector بيغيّر Element.citable أو chunk text. RAG core يقدر يعرض نقص التغطية بدل ما loss يفضل صامت، من غير تحويل flags لدليل.

النتائج الفعلية والـbuckets والـbefore/after crops في `reports/r-lite-2.md` و`out/r-lite-2/`. G4 معلّم seen؛أي miss باقٍ مش تصريح بإعادة tuning. OCR/rules/gold وchunk parameters ثابتين، وقراءات OCR الموجودة اتعمل لها replay byte-identical. الإصلاحات الرقمية فقط لها fingerprint جديد. Citation يفضل block_id + span؛reader update ممكن يغيّر block ids، فلازم RAG يعيد الفهرسة من snapshot الجديدة.

## 9 أسئلة مقابلة

1. **ليه citation مش chunk_id؟** Chunk حدودها ممكن تتغير؛ block span بيرجع لنفس النص والمكان من غير ربطه بالـretrieval strategy.
2. **ليه فيه separators صناعية؟** عشان الكلمات والخلايا ما تتلزقش. Typed map يميز التنسيق عن evidence، ويمنع الاستشهاد بالتنسيق.
3. **ليه مفيش overlap؟** عشان primary ownership تتراجع بالحروف، والتكرار يبقى صريح. Neighbor ids توفر توسعة السياق.
4. **ليه whole sentences حتى لو طويلة؟** عشان ما نقطّعش evidence sentence. Overflow متسجل، والـverifier يقرر التعامل معاه في الخطوة الجاية.
5. **إزاي تثبت إن مفيش نص ضاع؟** Interval arithmetic لكل citable block، ثم reconstruction لكل chunk؛ مش word count تقريبي.
6. **هل OCR accepted يعني verified؟** لأ؛ accepted قرار القارئ. Flagged/unlinked ممنوع يتحسبوا verified، وحتى accepted ممكن يبقى correlated error.
7. **إمتى تقول الجدول unavailable؟** أول ما ownership/grid/source/number link مبهم أو bounds/totals تفشل. النص يفضل موجود؛ cells ما تتخمنش.
8. **إزاي highlights تبقى أمينة؟** نستخدم source geometry بالدقة المتاحة، ونرجع deskew للإطار الأصلي. Word box يتسمى word، مش char.
9. **إزاي تعيد نفس النتيجة بسرعة؟** Frozen fingerprint-keyed cache، versions ثابتة، canonical serialization، structure-only بلا inference، وG5 byte comparison في عمليات منفصلة.
