# 0030 — Generated chat answers, source copies reserved for decks

قرار التنفيذ بطلب المالكة، 2 نوفمبر 2026؛ قبول الجودة لسه غير مقاس.

مسار التطبيق يستعمل hybrid retrieval لكل مصدر (BM25 prefilter 12 ثم embedding+RRF)، ويحتفظ بمصدر مستقل في packing. ده coverage للبحث، مش إجبار على الاستشهاد بمصدر غير مفيد. الموديل يطلع plan JSON ثم prose جملة بجملة من spans محددة. كود التطبيق يرفض نقل handle من جملة لخطة جملة تانية.

الـL0–L4 والـnumeric/entity/scope gates والـnative cutoff ثابتين. اتضاف شرط reply على مستوى التطبيق: النص المنسوخ أو source substring مش إجابة، حتى لو receipt الحقائق صحيحة. الجمل المركبة لازم تتقسم، والفاشل يتصلح مرة واحدة من نفس spans، ثم يتحذف. المصدر الكامل يظهر عند فتح citation فقط. الـlegacy engines والـdeck copy path ثابتين.

الـreceipt reason يستعمل vocabulary العقود الموجودة، وtrace منفصل بيوضح generated_prose/single_sentence. مفيش relaxation للـverifier ولا تعديل registry أوtestsplit. False blocks هتتقاس بـ60 candidate sentences؛ owner labels منفصلة عن AI review. أي tuning لاحق للـverifier محتاج ADR جديد وdev فقط.

فشل كل الجمل يظهر كحالة تشغيل صريحة غير محسوبة كإجابة مولّدة متحققة. دي limitation متعمدة في هذه النسخة: generated verified coverage/absence prose مش مضمون بعد؛ لا نسمّي حالة الرفض deterministic دي نجاحًا. acceptance ممكن FAIL، ومفيش excerpt fallback.


التطوير كشف إن الـhybrid chunk ممكن يضم checklist cells، فـblock ranking بقى يرتّب الفقرات lexically مع الاحتفاظ بالـsemantic-only tail. أسئلة القوائم، التعليمات بلا actor، والـmerged columns بتتمنع من التخطيط. References بتستمر عبر صفحاتها لحد appendix heading. دي reading/generation fixes على dev؛ ما اتغيّرش verifier threshold أو موضوع قبول.
