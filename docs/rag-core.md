# RAG core

Matn بيجمع مصادر في notebook وبيفهرس الـ chunks الصالحة للاستشهاد من DocumentStructure محفوظ ومتحقق منه. RAG ما بيشغّلش reader أو OCR. كل hit بيرجع block_id وحدود الحروف والصفحة وbbox precision وnumeric ledger زي ما reader سجّلهم؛ وجود hit لسه مش verification للجملة.

SQLite هو backend اللابتوب وراء Repository interface. نفس doc_id في نفس notebook بنفس fingerprint والـversions يبقى no-op. إضافته لـnotebook تاني تعمل source مستقل، مع مشاركة embedding cache بالـrefcounts. حذف source يحذف chunks/postings/stats/refs بتاعته والـvectors غير المستخدمة. سياسة per-tenant caches تتقرر في server step.

الفهرسة تستخدم context_prefix، فاصل، ثم chunk text؛ الـprefix مش evidence. Numeric aliases تشارك base position ومش بتزوّد document length. BM25 يستخدم k1=1.2 وb=0.75، وN/df/avgdl من المصادر المختارة بس. TF هو عدد المواضع المختلفة؛query terms بتتعملها dedup كـset، والجمع بترتيب ثابت.

Embeddings من qwen3-embedding:0.6b المحلي،digest مثبت وdimension1024. Transport يقبل http على127.0.0.1 فقط، بدون credentials أوproxy أوredirect. /api/embed يستخدم truncate=false وnum_ctx32768 وbatch8، ثم L2 normalization وfloat32. اختبار حي بسياق64 ونص8192word رجع error، فرفض truncation مثبت فعليًا. Cache key هو digest+input version+textSHA، والـdigest/version بيتراجعوا قبل استخدام cache. Query vectors في memory؛التقييم يحفظ snapshot للـoffline ranking replay. Generation client القديم له F-03 منفصل.

Exact cosine يجمع float64 products بترتيب الإحداثيات باستخدام math.fsum، من غير ANN أوBLAS reduction. BM25top50 وvectortop50 يندمجوا بـRRF k=60 و1-based ranks وأوزان متساوية. Ties:score تنازلي ثم chunk_id تصاعدي. Ablations هي BM25-only وvector-only وno-prefix؛الأخير يعيد lexical stats وdocument embeddings من chunk text فقط.

Focused default depth10 وevaluation depth50؛نفس الدالة ترجع prefix. Survey يحسب B=max(10,3×عدد المصادر)، ويحجز min(2,c) من ranking كل source، ثم يملأ B من global fused list بدون تكرار. ترتيب الأساس:global RRF تنازلي، ثم per-source rank، ثم chunk_id. Reserved candidate الغائب عالميًا ياخد global RRF0؛بعد الأساس نضيف global remainder بترتيبه. قائمة survey كلها مش globally score-sorted؛الأساس والامتداد كل واحد مرتب لوحده.

Survey default depth=B؛depth<B خطأ. Summary يذكر كل source مختار وcitable count وhit count وno lexical match وno_citable_content. coverage_shortfall يظهر في survey بس وقيمته max(0,2−hits). Source c0 ضمانه0؛اختيار مصادر كلها c0 يرجع empty hits، لكن empty/unknown selection خطأ. Neighbors±1 في context array منفصل، مش hits ولا metrics.

## أسئلة المراجعة

**هوية الاستشهاد chunk_id؟** الدليل block_id+char span. Separators والـprefix مش صالحين؛repeated_context يتحل للـprimary chunk/block span. تغيير chunk IDs بعد structure fix يحتاج إعادة حساب relevant sets، من غير تغيير gold target.

**لو chunk فيه France وGermany؟** Verification لازم يربط statement ببلوكات الـnamed entity نفسها، مش بلوك الجار في نفس chunk. نفس الشرط مع Energy+Financial Services وFinancial Services+Government+IT؛section title أوcontext prefix مش بديل.

**accepted OCR معناه verified؟** ده reader verdict. Flagged/flagged-unlinked/digital-unlinked ما يتعلّموش verified؛unavailable table cells ما تدخلش charts/KPIs. RAG ينقل ledger كما هو.

**لو النص والرسم مختلفين؟** arXivkn02:النص "over 90%" والرسم Sonnet exactly90% حسب ملاحظة asmaa. Verification text-bound يضمن fidelity للنص، مش internal consistency للمصدر؛ممنوع قراءة أرقام من figures.

**التقييم human gold؟** Questions drafted byGPT(Codex). Provenance: "asmaa 6 items; GPT (Codex) 14 items, delegated; not independent of the drafter; not human gold". التفويض اتطبّق من general approval phrase وقتها. بعدها "cross-family screen: Claude (senior-reviewer chat), not human". Owner verdicts ليها الأولوية؛GPT evidence فقط؛leak/not answerable يتشالوا بدون rewrite. Relevant sets تستخدم exact normalized targets، مش كل الإجابات المعنوية الممكنة؛elsewhere diagnostic فقط، بدون numeric undercount estimate.

**نطاق freeze؟**60 سؤال منarXiv/GAO/WB و12survey topics،commit5083164 قبل retrieval؛57reachable و3reading ceiling. Draft splits ثابتة. kp08/kn04 يشاركوا quote، وده قيد على CI. Hit@1/5/10/20/50 معWilson95 وMRR@10 معbootstrap10000 seed20261012، وتفصيل source/split/kp-kn/overlap tertiles. Survey structural coverage، بدون precision claim. Tune hit50−hit5≥.15 يقترح reranker فقط، من غير بناء أوtuning.

**WEF داخل freeze؟**لا. Sample20/20 chart text، ومعظم citable words فيtable kind. تجربة4-source منفصلة DIAGNOSTIC بعد frozen3، لقياس التكلفة وhit10 lost/gained وWEF table top10 slot share وsurvey coverage. R-lite.3(WEF) بعدRAG وقبلverification، mechanism diagnosis أولًا؛دخولWEF للـfreeze بعد الإصلاح وredraft وdifferent-family screen وowner review.

## Postgres parity والتشغيل

Postgres+pgvector تنفيذ server لاحق،docs فقط هنا. لازم يوفر نفس raw records/postings/vectors/per-source stats وtransaction/delete/cache refs semantics. Python scoring ثابت فوق backend؛مفيش SQL scoring أوANN replacement. `repository_factory` فيtests/rag/conftest.py نقطة تبديل backend للـcontract suite؛SQLite fault-injection tests منفصلة. Canonical export لكل tables بترتيب semantic keys، بدون rowids أوSQLite internals؛search JSON byte-identical بعد A,B,C-deleteB مقابل A,C. Timings/RSS/timestamps خارجIX4.

تشغيل live بعد `source scripts/dev_environment.sh`: `.venv/bin/python -m eval.rag.run`. إعادة الأرقام المشتقة من raw results/events بدون model calls: `.venv/bin/python -m eval.rag.run --reproduce`. Outputs فيout/rag-core/part2؛survey TSV فيهids و200-char preview،full text فيJSON. Latency القياس بعمق50؛متوصّفش كـdefault depth10. ممنوع test-split access، ومفيش registry generalization؛IX1–IX7 على3-source notebook؛full five-directory suite مرة واحدة آخر التنفيذ.
