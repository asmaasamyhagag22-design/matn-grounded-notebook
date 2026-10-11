# RAG core — قرار survey المعتمد (Part 1)

دي ملاحظة تصميم قبل التنفيذ؛ باقي شرح RAG واختباراته مستنيين اعتماد Part 1 بالاسم.

في focused، default depth=10 والتقييم depth=50. نفس ranking function بتستخدم depth كطول prefix؛ التقييم ملوش ranking path مختلف.

في survey، نحسب `B=max(10,3×عدد المصادر المختارة)`. نحجز `min(2,c)` لكل مصدر من ترتيب hybrid بتاعه، و`c` عدد chunks الصالحة للاستشهاد. نملأ قائمة الأساس لحد B من global fused list من غير تكرار. لو إجمالي المحتوى أقل من B، نرجع المتاح فقط مع summary لكل مصدر.

ترتيب قائمة الأساس: `global RRF score` تنازلي، ثم `per-source rank` تصاعدي، ثم `chunk_id` تصاعدي. الـreserved slot الغائب عن القائمتين العالميتين top50 ياخد globalRRF=0. بعدها نضيف باقي global fused candidates بترتيبهم العالمي، من غير عناصر الأساس.

**قائمة survey كلها مش مرتبة عالميًا حسب score من أولها لآخرها.** الأساس والامتداد كل واحد مرتب لوحده؛ coverage slot ممكن يظهر قبل عنصر أعلى score في الامتداد عمدًا. الهدف إن مصدر صغير ما يتزاحمش بره النتائج.

Default survey depth=B؛طلب depth أقل من B خطأ، من غير زيادة أو truncation صامتة. Evaluation depth=`max(50,B)`. اختبار prefix يقارن B معmax(50,B)، وIX7 يتفحص عندB؛focused يقارن10 مع50.

كل مصدر مختار يظهر في summary، حتى لو `c=0`: يتعلم `no_citable_content` وضمانه صفر. أي مصدر له أقل من نتيجتين يتسجل له `coverage_shortfall=2−slots`. جداول fixtures المستقبلية لازم تغطي c=0،c=1،c≥2. التنفيذ لسه ما بدأش.
