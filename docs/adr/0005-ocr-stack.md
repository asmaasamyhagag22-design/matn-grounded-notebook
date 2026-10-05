# ADR-0005 — OCR stack وقرار القبول

الحالة: مقبول للتنفيذ في Step 4c close-out؛ نجاح الـ gate بيتسجل منفصل في `reports/step4c-final.md`.
قرار الـ owner: Oct 6، مع تشغيل unattended وتنزيلات محددة بس.

Reader 1 هو PP-OCRv5 mobile det/rec، تحويل ONNX المثبّت بالـ hashes، عن طريق RapidOCR 3.9.2 وonnxruntime
1.30.0. PaddleOCR 3.7.0 / Paddle 3.3.1 موجودين في `.venv-ocr` للمقارنة على Linux، بس مش مسار تشغيل اللابتوب:
Smart App Control منع `pandas_parser` و`ujson` اللي PaddleX بيحمّلهم. مفيش إعداد أمان اتغيّر.

Reader 2 هو GLM-OCR `glm-ocr:bf16` على Ollama المحلي، prompt `Text Recognition:`، temperature/seed صفر،
سطر من الصورة لكل call، ووقف عند أول newline. الـ opener بيمنع proxies، وكل التشغيل تحت `block_egress()`.
الـ SDK الخاص بـ GLM مش مستخدم عشان ما يدخلش layout pipeline مشتركة مع reader 1.

كل رقم بياخد second read. معايرة dev-tune القديمة لقت رقم غلط بثقة **0.99993**؛ الـ bar **1.0** ما بيفصلش
الصح عن الغلط، فمش هنوفّر وقت عن طريق قبول أرقام عالية الثقة. المتوسط القديم على اللابتوب: synthetic حوالي
106 s/page، real حوالي 147 s/page، وفي الجداول الكثيفة لحد 332 ثانية. أوقات close-out المقاسة في التقرير النهائي.
على GPU متوقع calls أسرع، بس مفيش قياس GPU هنا ومفيش وعد بسرعة محددة.

الـ consensus بيقارن numeric tokens بنفس الشكل المطبوع: `1,240` و`1240` مختلفين. Reader 2 ما بيستبدلش
قيمة reader 1. اختلاف، فشل قراية، أو قراءة غير ثابتة بعد التدوير → `uncertain_number` مع الصورة والقراءتين.
الاتفاق وحده مش كفاية: رقم داخل رسم أو صورة يبقى `figure_text` خارج prose، وpage furniture خارج النص.
عقد Block الحالي بيمثل `figure_text` و`marginalia` بنوع `figure`؛ النوع التفصيلي محفوظ في OCR metadata،
من غير enum/schema change غير مطلوب.

كشف المناطق: **PP-DocLayoutV2 ONNX** عن طريق **rapid-layout 1.2.1**، Apache-2.0، ModelScope
`RapidAI/RapidLayout @ v1.2.0`، 213,963,993 bytes،
sha256 `0bd2ea0997fe0789f0300292291f8bbf897d890b44a9a3bd5be72afd6198aa90`.
مسار محلي صريح، تحقق size/hash قبل التحميل في الذاكرة، ومفيش auto-download. المناطق بتفصل الرسوم والصور،
بتحافظ على captions، بتكشف headers/footers، وبتحصر checks بتاعة الجداول في مناطق `table` فقط.
تكرار النص في الهوامش بيتراجع عبر الصفحات. النص غير الأفقي بيتلف ويتقري تاني؛ الأختام الهامشية marginalia.
تجميد الحدود وطريقة adaptive denoise في `docs/ocr_rules.md` و`closeout_rules.json` قبل holdout-2.

الاختيارات المرفوضة: DocLayout-YOLO/YOLOv8 بسبب Ultralytics/AGPL؛ Tesseract كقارئ ثانٍ لأن قرار الـ owner
اختار GLM من عائلة مختلفة؛ pandas stub لأنه بيخفي اعتماد غير مدعوم بدل تثبيت مسار واضح؛ تعطيل Smart App
Control لأنه تغيير أمان رفضته الـ owner. مفيش تنزيل لأي بديل.

المقارنة Paddle مقابل RapidOCR مؤجلة لـ Linux. PaddleOCR-VL وreader 3 (TeleOCR/OvisOCR2) مؤجلين للـ GPU.
العربي لـ R9، table structure/TEDS لـ 4d/R4، section trees/document.json/chunks لـ Step R.

dev-check بقى **seen**. الـ gate الجديد holdout-2: صفر reader-attributed silent errors بعد تحكيم كل raw
error بصريًا، مع flag rate وfalse-alarm rate. مفيش tuning بعد فتحه. GT الحقيقي بيكتبه الإنسان من الصورة؛
لا القارئين ولا الـ agent بيملّوه.
