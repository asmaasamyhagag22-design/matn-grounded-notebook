# عقود البيانات في Matn

الملف ده شرح عملي للـ contracts اللي في `matn_contracts/`. الفكرة الأساسية إن أي sentence أو number يوصل
للـ summary أو الـ deck لازم نعرف نرجعه لمكان محدد في الـ PDF، من غير ما نعتمد على إن الـ prompt “أكيد هيلتزم”.

كل model هنا Pydantic v2، `frozen=True` و`extra="forbid"`. يعني القيمة ما تتغيرش بعد ما تتبني، وأي field مش
معروف يتترفض بدل ما يعدّي بصمت. كل model كمان فيه `schema_version` (`1`، ما عدا `Block=2`
و`Slide`/`DeckPlan` وdrafts بتوعهم = `3`): السؤال اللي بيجاوبه هو “أنا بقرا أنهي
نسخة من العقد؟”. لو غاب، consumer قديم ممكن يفسّر shape جديدة غلط. البديل المرفوض كان implicit versioning من
اسم الملف؛ ده ما ينفعش لما object يتنقل لوحده.

## الصورة الكبيرة

```text
PDF
  -> Block --code assigns block_id + visibility + extractor-->
  -> Section --code assigns section_id and checks coverage-->
  -> FactDraft --LLM uses b1/b2 refs, no IDs or status-->
  -> Fact --code maps refs, checks quotes/numbers, assigns fact_id + raw status-->
  -> SummarySentence / Slide --only fact_id references-->
```

الفصل بين domain models وdraft models مقصود. الـ domain هو الحقيقة الكاملة اللي الـ pipeline يتبادلها. الـ draft
هو أصغر surface مسموح للـ LLM يكتبه. لو استخدمنا model واحدة، الـ LLM كان يقدر يخترع `fact_id` أو يقول إن fact
`verified` أو يكتب offsets مش حقيقية. البديل المرفوض كان ننضّف output بعدين؛ ساعتها الغلط يدخل النظام الأول.

## قواعد مشتركة مهمة

- `doc_id` هو `sha256-<64 hex>` من bytes بتاعة الـ PDF. ده بيجاوب “أنهي ملف بالضبط؟”. اسم الملف بديل مرفوض
  لأنه بيتغير وممكن يتكرر.
- كل page جوه العقود `page_index` بتاعها zero-based. الخلط مع الـ current 1-based `pdf_page` يعمل citation
  على الصفحة الغلط.
- `bbox=(x0,y0,x1,y1)` بوحدة PDF points، origin فوق شمال، وبعد rotation normalization. ده بيجاوب “النص فين
  على الصفحة؟”. page number لوحده مش كفاية للـ highlighting أو كشف text مخفي.
- الـ IDs deterministic. الـ sequential claim IDs القديمة كانت بتتغير لو fact اتضافت في الأول؛ كل downstream
  reference كان بيتكسر.
- collections جوه domain models tuples. البديل list مرفوض لأنه mutable، وممكن ordering يتغير بعد validation.

## Extraction وstructure models

### `BlockStyle`

| Field | السؤال | لو ناقص/غلط | القرار والبديل المرفوض |
|---|---|---|---|
| `font_size_pt` | حجم الخط كام؟ | Step 3 ممكن ما يكتشفش heading | nullable float لأن extractor أحيانًا ما يعرفش؛ تخمين الحجم مرفوض |
| `is_bold` | النص bold؟ | heading detection تضعف | nullable bool؛ تحويل unknown لـ`False` مرفوض |

### `ExtractorInfo`

| Field | السؤال | لو ناقص/غلط | القرار |
|---|---|---|---|
| `name` | مين استخرج النص؟ | اختلاف extractor يبقى غير قابل للتفسير | string غير فاضي |
| `version` | أنهي build؟ | rerun مختلف يبان كأنه نفس التشغيل | string غير فاضي، مش “latest” |

### `Block`

| Field | السؤال | لو ناقص/غلط | القرار والبديل المرفوض |
|---|---|---|---|
| `block_id` | إيه الهوية القابلة للإعادة؟ | references تتكسر زي sequential claim IDs | code يحسبه من doc/page/rounded bbox/raw text؛ UUID مرفوض |
| `doc_id` | البلوك تابع أنهي PDF bytes؟ | ممكن evidence تتوصل بملف تاني | SHA-256 بصيغة registry الحالية |
| `page_index` | أنهي physical page؟ | off-by-one citations | zero-based و`>=0` |
| `page_label` | إيه الرقم المطبوع للقارئ؟ | “iv” أو label مختلفة تضيع | nullable string؛ اشتقاقها من index مرفوض |
| `bbox` | النص فين؟ | hidden/overlaid text ما يتراجعش | PDF points، top-left، rotation normalized، valid rectangle |
| `block_type` | ده prose ولا heading/table/figure…؟ | table أو figure text يدخل prose | closed `BlockType` enum |
| `text` | extractor شاف إيه حرفيًا؟ | hash والquote matching يتغيروا | raw text بدون normalization in place |
| `reading_order` | ترتيبه إيه؟ | summary يقلب المعنى | integer zero-based |
| `style` | إيه إشارات التنسيق؟ | headings تبقى keyword guesses | `BlockStyle` منفصلة |
| `extractor` | مين أنتجه؟ | provenance ناقصة | `ExtractorInfo` على كل block |
| `route` | text layer ولا OCR؟ | الجودة والمخاطر ما تتفسرش | `text_layer` أو `ocr` |
| `visibility` | ظاهر فعلًا؟ | hidden text يدخل كدليل | `visible`, `hidden`, `uncertain`; آخر اتنين برّه الـ prose ومعلّمين |
| `visibility_reasons` | ليه hidden/uncertain؟ | سبب الإخفاء يضيع أو يتقلب | tuple canonical من `invisible_render_mode`, `covered_by_image`, `covered_by_vector`, `fill_matches_background`, `outside_cropbox`, `near_zero_size`, `clipped`, `partial_ink`, `no_ink_unexplained`; فاضي بس مع `visible` |

تغيير visibility رفع `Block.schema_version` لـ2. الـ gold verifier يحتفظ بالمعنى: `covered_by_image` error
و`covered_by_vector` warning.

### `TableCell` و`Table`

`TableCell.row` و`col` بيجاوبوا الخلية فين، وقرارهم zero-based؛ لو غلط chart يختار series غلط. `text` هو القيمة
كما استُخرجت؛ normalization ممكن يغيّر number. `bbox` بيثبت مكان الخلية، و`is_header` يمنع إن label تتعامل كـ
data. `Table.table_id` هوية code-owned من doc/page/bbox؛ `doc_id` و`page_index` و`bbox` بيربطوا الجدول بالمصدر؛
`header_rows` indices sorted/unique؛ و`cells` tuple لكل الخلايا. تخزين Markdown blob بس اترفض لأنه ما يديش chart
column references ولا cell provenance.

### `PageRange`, `Section`, و`SectionCoverage`

`PageRange.first_page_index` و`last_page_index` بيجاوبوا section بتبدأ وتنتهي فين؛ الاتنين zero-based والأول ما
ينفعش يعدّي الأخير.

في `Section`: `section_id` بيتحسب من document + `heading_path` + أول block؛ `doc_id` يحدد الملف؛ `title` هو
العنوان الظاهر؛ `level` عمق heading وبيبدأ من 1؛ `heading_path` tuple من outermost للـ current heading؛
`block_ids` ترتيب المحتوى ولازم فيه عنصر؛ و`page_range` ملخص مكاني. الـ current keyword-built sections بديل
مرفوض لأنها document-specific ومش مربوطة بهيكل حقيقي.

`SectionCoverage.missing_block_ids` بيجاوب “أنهي visible prose ضاع؟”، و`duplicated_block_ids` بيجاوب “أنهي prose
اتحسب مرتين؟”. الفحص يغطي visible `text/heading/list_item/caption/footnote` فقط، ويستبعد `table/figure/header/footer`
وكل hidden block. count واحد مجمّع كان بديل مرفوض لأنه ما يفرقش loss عن duplication.

## Evidence وfacts

### `EvidenceRef`

| Field | السؤال | لو ناقص/غلط | القرار |
|---|---|---|---|
| `block_id` | quote جاية من أنهي block؟ | page citation من غير موضع دقيق | full code-owned ID |
| `quote` | إيه النص الداعم حرفيًا؟ | statement ما تتراجعش | non-empty exact substring |
| `char_start`, `char_end` | span فين جوه block؟ | UI ما يعملش exact highlight | الاتنين `null` لحد verifier، أو valid half-open pair؛ رقم واحد لوحده مرفوض |

### `NumberFactValue`

`label` بيجاوب الرقم معناه إيه، و`value_as_written` بيحفظ token زي ما اتكتب، و`unit` الوحدة أو `null`، و`page_label`
الlabel المطبوع المشتق بالكود من block. لو الـ model حوّل `64` إلى “six-four” يحصل
`spelled_number_mismatch`; ولو جمع figure digits وطلع `1008060` لازم ما يبقاش evidence صالح. إعادة الحساب أو
format conversion بدائل مرفوضة.

### `Fact`

| Field | السؤال | لو ناقص/غلط | القرار |
|---|---|---|---|
| `fact_id` | statement دي هويتها إيه عبر reruns؟ | summary/deck refs تتكسر | hash من أول evidence block + normalized statement |
| `kind` | نوع الحقيقة؟ | planning/eval يختلفوا | gold vocab بالضبط + `number` |
| `statement` | الادعاء atomic إيه؟ | evidence يبقى غامض | non-empty؛ يدخل في deterministic ID |
| `attributed_to` | مين قاله؟ | recommendation تتنسب غلط | nullable non-empty string |
| `evidence` | إيه الدليل؟ | ungrounded fact | tuple فيها `EvidenceRef` واحدة على الأقل |
| `importance` | أولوية العرض؟ | headline تضيع | `1=supporting`, `2=important`, `3=headline` زي gold |
| `status` | اتراجع لحد فين؟ | raw content يتعرض كأنه verified | `raw/verified/rejected` code-owned |
| `reject_reasons` | اترفض ليه؟ | audit غير مفهوم | closed enum، وفاضية إلا مع `rejected` |
| `number_value` | هل فيه number payload؟ | model number يهرب كـ finding | مطلوب iff `kind=number` |

الـ reject enum بيفرّق `quote_not_found`, `invalid_evidence_span`, `number_not_in_evidence`,
`unsupported_statement`, `attribution_mismatch`, `hedge_mismatch`, `evidence_hidden`, `evidence_in_figure`, و
`spelled_number_mismatch`. free-text reason اترفض لأنه ما ينفعش عليه metrics ثابتة.

## Summary models

`SummarySentence.text` هو sentence النهائي، `type` يحدد `extraction` ولا `interpretation`، و`fact_ids` tuple غير
فاضية بتجاوب كل كلمة مهمة متسندة على إيه. Sentence من غير IDs مرفوضة.

`SectionSummary.section_id` يربط الملخص بهيكل حقيقي بدل keyword bucket، و`sentences` هي الـ ordered tuple.
`section_summary_from_draft(..., section_id=...)` بياخد ID من الكود، مش من الـ model.

`KeyNumber.fact_id` يربط الرقم بـ verified fact؛ `label`, `value_as_written`, `unit`, و`page_label` نسخ code-owned
من `NumberFactValue`، وبيبنيهم `key_numbers_from_facts` من الـ verified number facts بس. الـ model ما بيكتبش `KeyNumber`، علشان “six-four” أو `1008060` ما يدخلوش output.

`Summary.doc_id` يحدد المصدر؛ `tldr` tuple من `SummarySentence` ولازم مش فاضية؛ `key_findings` نفس shape؛
`section_summaries` مربوطة بـ section IDs؛ و`key_numbers` مبنية بالكود. plain strings كانت هتقطع provenance.

## Slides وdeck

`SlideItem.text` assertion بحد أقصى 120 character، و`fact_ids` tuple غير فاضية. لو IDs ناقصة، renderer يطلع
bullet ما نقدرش ندافع عنه.

`ChartSpec.table_id` يحدد الجدول؛ `x_column` و`y_columns` zero-based references؛ و`chart_type` واحد من
`bar/column/line`. مافيش data values. column names اترفضت لأنها ممكن تتكرر أو تبقى فاضية، ونسخ الأرقام اترفض
علشان chart ما يبقاش مصدر أرقام تاني.

في `Slide`: `slide_type` يختار shape؛ `title` assertion non-empty وبحد أقصى 90؛ `items` tuple بحد أقصى 4؛
`kpi_fact_ids` بين 1 و4 على KPI فقط (من Step 2c.1؛ قبلها كان 2 لـ4)؛ `chart` موجود على chart فقط؛ و`notes` nullable. KPI item text ممنوع فيه digits،
والـ cross-object function يتأكد إن كل KPI ID نوعه `number`. كده renderer هو اللي ينسخ القيم المراجَعة.

Step 2b زوّد 3 أنواع، وعلشان كده `Slide` و`DeckPlan` و`SlideDraft` و`DeckPlanDraft` بقوا `schema_version=2`:
`section_divider` (عنوان + item واحد بالكتير = سؤال السكشن؛ الرقم الكبير بيحسبه الكود من ترتيب الـ dividers)،
`closing` (takeaways عادية لحد 4)، و`evidence_appendix` (ممنوع فيه items؛ الكود هو اللي يبني “الإيصالات”: كل رقم
مستشهد بيه مع الـ quote بتاعته). consumer قديم بيقرا v1 هيرفض v2 صراحة بدل ما يقابل type مش عارفه.

Step 2c.1 سمح بـ KPI slide فيها رقم واحد (`kpi:hero-number`: رقم كبير + سطر بيشرحه)، فالأربعة (`Slide` و`DeckPlan` و`SlideDraft` و`DeckPlanDraft`) بقوا `schema_version=3`. صفر أو خمسة أرقام لسه بيترفضوا، و`validate_deck_plan_against_facts` بيعيد نفس فحص العدد (`KPI_FACT_COUNT`) للـ objects اللي اتبنت من غير validation.

`DeckPlan.doc_id` يثبت المصدر و`slides` ordered non-empty tuple. `validate_deck_plan_against_facts` بيرفض unknown
fact IDs وKPI refs اللي مش numbers؛ القاعدة ما اتحطتش جوه `Slide` لأنها محتاجة objects خارجية.

## Run reproducibility

`PromptVersion.name` بيحدد prompt و`version` نسخته. `SamplingParameters.temperature`, `seed`, `top_p`, `num_ctx`,
و`num_predict` بيجاوبوا model اتشغل بإعدادات إيه؛ القيم nullable بس لما runtime ما يبعثهاش، والحدود تمنع إعدادات
مستحيلة.

`RunManifest.commit` يثبت code revision؛ `model_name` و`model_digest` يثبتوا model؛ `prompt_versions` يسجل كل
prompt؛ `sampling_parameters` يسجل inference؛ `extractor` يسجل extraction؛ و`started_at`/`completed_at` لازم UTC
ومرتبين. من غيرهم rerun مختلف ممكن يتقدم كأنه reproducible.

## LLM-facing draft models

كل draft ضيقة و`extra="forbid"`:

- `EvidenceRefDraft.block_ref` لازم `b1`, `b2`, … و`quote` non-empty. full block IDs وoffsets مرفوضين؛ code يعمل
  mapping ويرفض unknown ref.
- `NumberFactValueDraft.label`, `value_as_written`, وnullable `unit` اختيارات نصية للـ model. مافيش `page_label`؛
  conversion يشتقه. `value_as_written` لازم يساوي numeric token كامل داخل نفس quote والوحدة تظهر فيه.
  وأي رقم جوه `label` لازم يكون numeric token في الـ evidence، وإلا `LABEL_NUMBER_NOT_IN_EVIDENCE`. الرقم اللي بعده
  `.` أو `,` آخر الجملة (`64.`، `2021,`) بيتحسب token، و`1,234.5` كمان؛ بس جزء من رقم أكبر (`64` جوه `64.5`) لأ.
- `FactDraft.kind`, `statement`, `attributed_to`, `importance`, `evidence`, و`number_value` هي الاختيارات المسموحة.
  مافيش `fact_id/status/reject_reasons/offsets`. `number_value` موجود iff kind هو `number`.
- `SummarySentenceDraft.text`, `type`, و`fact_ids` نفس semantic choices، و`SectionSummaryDraft.sentences` يجمعهم؛
  `section_id` ييجي parameter من الكود.
- `SlideItemDraft.text` و`fact_ids` references فقط. `ChartSpecDraft.table_id`, `x_column`, `y_columns`, و`chart_type`
  من غير data values.
- `SlideDraft.slide_type`, `title`, `items`, `kpi_fact_ids`, `chart`, و`notes` عليها نفس limits بتاعة domain، لكن
  من غير document identity. `DeckPlanDraft.slides` هو الـ ordered output؛ `doc_id` ييجي من orchestration code.

الـ conversion functions ما تمسكش `ValidationError` وتسكت؛ أي unknown ref، quote مش موجودة، token أو unit مش
موجودين، أو cross-object reference غلط يوقف التحويل صراحة.

## ليه schema snapshots؟

كل public model له file في `schemas/contracts/`. Ollama ياخد draft schema من نفس Pydantic model اللي بيعمل runtime
validation. الـ snapshot test يقارن byte-for-byte؛ لو حد وسّع enum أو شال `minLength`، reviewer يشوف التغيير.
hand-written schema بديلة اترفضت لأن runtime/schema drift موجود أصلًا في الـ legacy pipeline.

## 10 أسئلة interview وإجابات نموذجية

1. **ليه deterministic IDs؟** علشان نفس المصدر ونفس المحتوى يطلعوا نفس refs في rerun، وإضافة fact ما تعيدش
   ترقيم كل حاجة زي sequential IDs.
2. **ليه models frozen؟** علشان object اتعمل له validation وID ما يتغيرش من ورا الـ downstream؛ التغيير يبني
   object جديدة.
3. **ليه `extra="forbid"`؟** علشان typo أو field model اخترعها ما تعديش بصمت وتضيع عند serialization.
4. **ليه PDF points وorigin top-left؟** points resolution-independent، وtop-left بعد rotation normalization يخلي
   القراءة والـ highlighting convention واحدة.
5. **ليه `visibility`؟** لأن النص ممكن يكون extractable لكنه مش ظاهر، زي hidden text على Egypt page 11؛ وجوده
   مش معناه إنه دليل صالح.
6. **ليه char offsets مع bbox؟** bbox يوصل للبلوك على الصفحة، والoffsets تحدد quote نفسها جوه البلوك للhighlight
   والتحقق.
7. **ليه الـ model ما يكتبش key numbers؟** علشان القيمة تتنسخ بالكود من verified number facts، وما تتحولش لـ
   “six-four” أو تتجمع غلط كـ`1008060`.
8. **ليه draft models أضيق؟** لأنها capability boundary: الـ model يختار content وreferences، والكود يملك identity
   وstatus وderived provenance.
9. **ليه schema snapshots؟** علشان contract change يبقى diff صريح، وOllama schema ما تنفصلش عن runtime model.
10. **ليه importance 3 هي headline؟** لأنها نفس دلالة gold schema والـ pipeline؛ عكس الاتجاه كان هيقلب ranking
    من غير validation error.
