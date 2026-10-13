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

**التقييم human gold؟** Questions drafted bymodel family A. Provenance: "asmaa 6 items; model family A 14 items, delegated; not independent of the drafter; not human gold". التفويض اتطبّق من general approval phrase وقتها. بعدها "cross-family screen: model family B (senior-reviewer chat), not human". Owner verdicts ليها الأولوية؛model evidence فقط؛leak/not answerable يتشالوا بدون rewrite. Relevant sets تستخدم exact normalized targets، مش كل الإجابات المعنوية الممكنة؛elsewhere diagnostic فقط، بدون numeric undercount estimate.

**نطاق freeze؟**60 سؤال منarXiv/GAO/WB و12survey topics،commit5083164 قبل retrieval؛57reachable و3reading ceiling. Draft splits ثابتة. kp08/kn04 يشاركوا quote، وده قيد على CI. Hit@1/5/10/20/50 معWilson95 وMRR@10 معbootstrap10000 seed20261012، وتفصيل source/split/kp-kn/overlap tertiles. Survey structural coverage، بدون precision claim. Tune hit50−hit5≥.15 يقترح reranker فقط، من غير بناء أوtuning.

**WEF داخل freeze؟**لا. Sample20/20 chart text، ومعظم citable words فيtable kind. تجربة4-source منفصلة DIAGNOSTIC بعد frozen3، لقياس التكلفة وhit10 lost/gained وWEF table top10 slot share وsurvey coverage. R-lite.3(WEF) بعدRAG وقبلverification، mechanism diagnosis أولًا؛دخولWEF للـfreeze بعد الإصلاح وredraft وdifferent-family screen وowner review.

## Postgres parity والتشغيل

Postgres+pgvector تنفيذ server لاحق،docs فقط هنا. لازم يوفر نفس raw records/postings/vectors/per-source stats وtransaction/delete/cache refs semantics. Python scoring ثابت فوق backend؛مفيش SQL scoring أوANN replacement. `repository_factory` فيtests/rag/conftest.py نقطة تبديل backend للـcontract suite؛SQLite fault-injection tests منفصلة. Canonical export لكل tables بترتيب semantic keys، بدون rowids أوSQLite internals؛search JSON byte-identical بعد A,B,C-deleteB مقابل A,C. Timings/RSS/timestamps خارجIX4.

تشغيل live بعد `source scripts/dev_environment.sh`: `.venv/bin/python -m eval.rag.run`. إعادة الأرقام المشتقة من raw results/events بدون model calls: `.venv/bin/python -m eval.rag.run --reproduce`. Outputs فيout/rag-core/part2؛survey TSV فيهids و200-char preview،full text فيJSON. Latency القياس بعمق50؛متوصّفش كـdefault depth10. ممنوع test-split access، ومفيش registry generalization؛IX1–IX7 على3-source notebook؛full five-directory suite مرة واحدة آخر التنفيذ.

## ليه عملنا vector diagnosis قبل الإغلاق؟

Part2 نجح في gates، لكن الإغلاق كان مشروط بتفسير ضعف vector retrieval. التشخيص خلص على tune فقط، ومظهرش correctness defect في embedding path. Fresh baseline vectors مطابقة للكاش، والإجابة الصح في5 synthetic sets كانت rank1. اختلاف space بعد `Query:` موجود في الوثائق نفسها؛ حذفه غيّر بعض ranks لكن hit10/50 ثابتين. إضافة EOS اتقرت special token وضرّت النتائج؛ مش مبرر لتغيير production. اختبار document EOS شمل21 target chunk بس وباقي corpus ثابت؛ مش full-corpus تجربة.

**ليه prefix ممكن يضر؟** نفس document/section title بيتكرر قبل chunks مختلفة، فيقرّب vectors لبعض بدل ما يميّز تفاصيل كل chunk. Same-section mean cosine زاد0.453→0.781 مع prefix؛ vector hit50 على26 reachable tune زاد16→24 من غيره، لكن hit10 ثابت11. ده mechanism evidence، مش إذن نشيل prefix؛ lexical ranking بيتأثر بيه كمان.

**ليه RRF مع retriever أضعف ممكن يضر؟** RRF بيجمع votes حسب rank، ومش عارف مين أدق. Chunk ظهر في top50 القايمتين بياخد contribution من كل واحدة؛ target ظهر في BM25 بس بياخد واحدة. GAO tune kp04 كان BM25 rank39 وvector54، فخارج vector candidates، وبعد fusion بقى67. ده يشرح mechanism، لكن فرق BM25/hybrid الإجمالي صغير ومش finding يبرر default change.

**Hubness يعني إيه هنا؟** Chunk بيتكرر في top10 لأسئلة كتير. من270 slots،154 chunk من975 ظهروا؛ top20 خدوا30.37%، وlength correlation ضعيف −0.068. دي skew وصفية على27 query، مش اختبار calibrated ولا إثبات سبب. في arXiv،74/100 vector slots كانوا footnote-kind؛137 footnote chunks median2 words، وseeded excerpts فيها code/diff/line numbers من appendix. إصلاح typing من اختصاص reading step، مش RAG diagnosis.

**ليه check مش held-out دلوقتي؟** نتائجه اتشافت في كل ablations السابقة. اختيار prefix/weights/BM25 default/reranker بعد المشاهدة وبعدين الاستشهاد بنفس check كدليل مستقل هيبقى تقييم منحاز. القرارات دي محتاجة pre-registered tune-only protocol؛ confirmation من WEF questions تتجمد بعد R-lite.3 وredraft وdifferent-family screen وowner review، قبل تشغيل retrieval عليها. Reranker لسه proposed؛ مفيش واحد اتبنى.

**تكلفة التسليم؟** WEF embeddings~75min للنسختين؛ نسخة production واحدة~37min estimate، مش قياس cold مستقل، فوق~44min digital reading على CPU وOCR قديم إضافي منفصل. لنفس batch8،server+runner RSS كان1.460GiB عند context4096 و4.505GiB عند32768؛ `ollama ps` كان2.4/5.8GB allocation. ده قياس اللابتوب، مش GPU prediction؛ production context32768 ثابت.

RAG core مقفول بعد A–F؛ التقرير `reports/rag-core-vector-diagnosis.md`. إعادة التشخيص offline من الأدلة بدون model calls: `.venv/bin/python -m eval.rag.vector_diagnosis`. R-lite.3(WEF) التالي، مش بدأ.
