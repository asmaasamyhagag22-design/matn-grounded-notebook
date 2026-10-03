# Design brief — شكل كل الـ decks في Matn

> **اتلغى في Step 2b (2026-10-03):** `design/tokens.json` و`design/layouts.json` والـ renderer v0 اللي كان بيرسم بالكود اتشالوا. التصميم دلوقتي جوه PowerPoint templates (`design/templates/`) والكود بيملا placeholders بالاسم بس: `docs/design/template-contract.md` و`docs/design/tricks.md`. الأجزاء الباقية هنا (الـ assertion titles، الـ contrast، الـ RTL في §11) لسه مرجع للأفكار.

المصدر الوحيد للقيم: `design/tokens.json` (ألوان، خطوط، مقاسات، margins بالـ EMU) و`design/layouts.json`
(مكان كل slot في كل archetype). الـ renderer (`matn_deck/`) بيملا الـ slots دي بس، ومفيش أي style مكتوب في الكود.

## 1. الجمهور والقصة
- الجمهور: قيادات الوزارة. وقتهم قليل، ومحتاجين يعرفوا الخلاصة ومصدرها.
- الإجابة الأول: الـ slide التانية دايمًا executive summary.
- كل title جملة كاملة فيها حكم (assertion)، مش عنوان موضوع. مثال: "التبني زاد 18% في 2025"، مش "التبني".
- كل رقم أو ادعاء ليه مصدر ظاهر (رقم الصفحة)، والتفاصيل (fact ID والـ quote) في الـ speaker notes.

## 2. الـ archetypes (واحد لكل `SlideType` في `matn_contracts`)
| slide_type | الشكل |
|---|---|
| `title` | خلفية داكنة، title كبير، subtitle من الـ items (لو موجودة). من غير footer. |
| `executive_summary` | لحد 4 صفوف مرقّمة، كل صف item واحد بخط 20pt وخط رفيع فوقه. |
| `kpi` | 2-4 tiles: القيمة والوحدة والـ label بيتنسخوا من الـ number fact بالكود، وتحت كل tile رقم الصفحة. الـ items (من غير أرقام) تحت الـ tiles. |
| `finding` | bullets على الشمال (7 أعمدة)، وعلى اليمين panel فيه الـ quote الأصلي لأول fact ورقم صفحته. |
| `chart` | native chart (8 أعمدة) من الـ `Table` المذكور في `ChartSpec`، والـ takeaways على الجنب (4 أعمدة). |
| `implications` | 4 cards (2×2)، كل card رقم ونص. |
| `limitations` | قائمة caveats بسيطة. |
| `sources` | "Sources and verification": صفحات كل slide، وعدد الـ facts الـ verified، والـ document ID، وجملة إن الأرقام بيتنسخها الكود. |

## 3. حدود المحتوى (من `matn_contracts.domain`)
- title: من 1 لـ 90 حرف. الـ item: من 1 لـ 120 حرف، وكل item لازم يكون ليه fact_id واحد على الأقل.
- items في الـ slide: 4 بالكتير. KPI: من 2 لـ 4 `kpi_fact_ids`، ونص الـ items مفيهوش أرقام.
- `chart` لازم يكون في chart slide بس، و`kpi_fact_ids` في KPI slide بس.
- الـ renderer بيقيس النص بالـ font metrics الحقيقية (PIL + ملف الخط) ويطلّع **overflow report** بدل autofit.
  قيمة الـ KPI بس ليها مقاسات متدرجة (54/44/36/28pt)، والكود بيختار أكبر مقاس يكفي كل الـ tiles.
- fact حالته `rejected` ممنوع يظهر (الـ render يقف). fact حالته `raw` بيطلع warning، وبيتعد في الـ sources slide.

## 4. Type scale (pt)
deck title 40 · slide title 28 · deck subtitle / lead 20 · body 18 · body small 16 · KPI value 54 (ينزل لحد 28) ·
KPI unit 24 · KPI label 16 · quote 16 italic · panel/list 14 · footer وsource line 12. الـ titles بـ line spacing 0.9.

## 5. الألوان
| token | hex | الاستخدام |
|---|---|---|
| background | FFFFFF | خلفية الـ content slides |
| surface | EEF3F4 | tiles وcards وpanels |
| dark | 0E3A4A | خلفية الـ title slide |
| ink | 1D2A33 | النص الأساسي (14.7:1 على الأبيض) |
| muted | 56646E | footer وsource (6.1:1 على الأبيض، 5.5:1 على surface) |
| accent | 0B5C6B | الأرقام والـ KPI والـ bullets (7.6:1) |
| on_dark / on_dark_muted | FFFFFF / C6D8DE | نص الـ title slide (12.2:1 و8.3:1) |
| rule | C9D3D8 | خطوط فاصلة وgridlines بس، مش نص |
| series_1..4 | 0B5C6B, 7C8C96, A8701A, 4E7D5B | ألوان الـ chart series |

القاعدة: كل text role في `tokens.json` بيقول لونه (`color`) والخلفية اللي بيتكتب عليها (`on`)، والـ test بيتأكد إن
الـ contrast ≥ 4.5:1 لكل role (حتى الكبير).

## 6. Grid وmargins
- 16:9، ‏13.333 × 7.5 inch (‏12192000 × 6858000 EMU).
- 12 عمود، gutter ‏0.2 inch، margins يمين وشمال 0.6 inch.
- مناطق ثابتة: title من 0.6 لـ 1.55 inch، الـ body من 1.85 لـ 6.75 inch، الـ footer من 6.95 لـ 7.25 inch.
- كل content slide: accent bar صغير فوق الـ title، و"Source: p. 14, 22" تحت على الشمال، ورقم الـ slide على اليمين.

## 7. الـ charts
- native PowerPoint charts بس (bar / column / line)، عشان تفضل editable والداتا جوّاها.
- مفيش 3D، ولا shadows، ولا gradients، ولا chart title (الـ slide title هو الحكم).
- data labels ظاهرة، gridlines رفيعة بلون `rule`، legend تحت بس لو أكتر من series.
- القيم بتتقرا من خلايا الـ `Table` بالكود؛ لو خلية مش رقم واضح الـ render يقف بـ `CHART_CELL_NOT_NUMERIC`.
  الـ number format (عدد الـ decimals، الـ thousands separator، الـ %) بيتاخد من طريقة كتابة الأرقام في الجدول.

## 8. المصادر والتحقق
- footer على كل content slide: "Source: p. N" (رقم الصفحة الفعلي في الـ PDF، عشان يتفتح في أي viewer).
- آخر slide "Sources and verification".
- الـ speaker notes لكل slide فيها: fact_id · الصفحة · الحالة · الـ quote بالنص.

## 9. الخطوط (قرار)
- **Calibri** للنص اللاتيني: موجود على كل Windows عليه Office، وpython-pptx مش بيعرف يعمل embed للخطوط.
- **Segoe UI** في الـ complex-script slot (`a:cs`) عشان العربي بعدين: موجود في Windows نفسه وفيه Arabic glyphs.
- على Linux (rendering checks): **Carlito** metric-compatible مع Calibri، فالقياس بيدي نفس النتيجة.
  الـ renderer بيدوّر على `calibri.ttf` الأول وبعدين `Carlito-*.ttf` (أو `MATN_FONT_DIR`).
- الـ line height بـ 1.2207 em (Calibri win metrics: 2500/2048)، وهامش أمان 3% في العرض.

## 10. اللي مش بنعمله أبدًا
- صور معمولة بالـ AI، أو أي صورة أصلًا في v0 (shapes مسموحة: text boxes، rectangles، native charts).
- رقم من غير مصدر، أو رقم كتبه الموديل (الكود بس اللي بينسخ الأرقام من الـ facts والـ tables).
- assets أو icons أو خطوط من غير license واضح.
- لوجو الوزارة من غير إذن مكتوب.

## 11. العربي (RTL) بعدين
- الأعمدة في `layouts.json` بتتعد من **بداية القراءة**، والـ alignment مكتوب `start`/`end` مش left/right.
- الـ margins متماثلة، فالـ mirror بسيط: `x' = slide_width - x - width` (`resolve_box(..., rtl=True)`).
- لسه ناقص للعربي: `rtl="1"` على الـ paragraphs، والـ chart axis reversal، وقياس النص بـ shaping
  (PIL محتاج `raqm`)، وفحص Segoe UI مقابل خط الوزارة لو عندهم واحد.
- لو template الوزارة وصل: بنعمل map للـ archetypes دي على layouts بتاعته، ونغير `tokens.json` بس.
