# Runbook الديمو: متن | Matn

## التشغيل (أمر واحد)

من فولدر `matn` في PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\run_dashboard.ps1
```

- المتصفح بيفتح لوحده بعد 5 ثواني على `http://127.0.0.1:8501`. لو مفتحش، افتحيه بإيدك.
- للإيقاف: `Ctrl+C` في الـ PowerShell.
- الـ app شغال على 127.0.0.1 بس (`.streamlit/config.toml`: `address`, `headless`, `gatherUsageStats = false`).

## قبل الديمو بـ 10 دقايق

1. شغّلي الأمر اللي فوق، ولفّي على الـ 7 صفحات مرة.
2. لو الصفحة الرئيسية بتقول إن مفيش `manifest.json`، ابني الـ cache (تحت).
3. اقفلي PowerPoint لو مفتوح (الـ Generate live بيفتح نسخة لوحده).

## لو PowerPoint أو Ollama فشلوا

- الـ dashboard **مش محتاج** أي واحد فيهم: كل الصفحات بتقرا من الـ cache في `out/demo/`.
- **PowerPoint فشل:** "Generate live" هيطلع رسالة صفرا ويعرض النسخة المحفوظة. متدوسيش عليه تاني؛ كمّلي بالـ cache.
- **Ollama فشل:** مش مستخدم في الديمو أصلاً (العناوين والنصوص من الكود). مفيش حاجة تتعمل.

## الملفات فين

| الحاجة | المكان |
|---|---|
| العروض PPTX | `out/demo/decks/<doc>/<template>/deck.pptx` |
| العروض PDF | `out/demo/decks/<doc>/<template>/deck.pdf` |
| صور الشرايح | `out/demo/decks/<doc>/<template>/png/slide_NN.png` |
| خطة العرض | `out/demo/decks/<doc>/plan.json` |
| الحقايق والإيصالات | `out/demo/facts/<doc>.json` |
| صور صفحات الـ PDF (للإيصالات) | `out/demo/pages/<doc>/` |
| صور التطور (2b → 2d) | `out/gallery/contact_sheet_v2.png`, `contact_sheet_v3.png`, `contact_sheet_v4.png`, `before_after_v4.png`, `contact_sheet_creative.png`, `families.png` |

المستندات (`<doc>`): `wb_eem_2021_12` (البنك الدولي)، `gao_21_519sp` (GAO)، `2601.14525v1` (الورقة البحثية).
العروض: wb في `modulo`, `nile-night`, `film-burn-dark`, `facet-dark`, `integral-dark`؛ gao في `modulo`,
`nile-night-teal`؛ 2601 في `papyrus`, `modulo`.

## الخطة البديلة (لو الـ app نفسه وقع)

1. افتحي `out/demo/decks/wb_eem_2021_12/nile-night/deck.pdf` (أو `deck.pptx` في PowerPoint) واعرضي منه.
2. للإيصالات: افتحي `out/demo/pages/wb_eem_2021_12/p0006_kn01_crop.png` (اقتباس رقم 9.8% متظلل)
   و `p0006_kn01.png` (الصفحة كاملة).
3. للمقارنة بين القوالب: افتحي `deck.pdf` بتاع `modulo` و `nile-night` جنب بعض.

## إعادة بناء الـ cache (لو اتمسح)

```powershell
.venv\Scripts\python.exe eval/gold_to_facts.py
.venv\Scripts\python.exe -m matn_deck.demo_build
```

- الأول بيحوّل الـ dev gold لـ Facts ويرسم صور الصفحات (حوالي 15 ثانية).
- التاني بيرسم الـ 9 عروض ويصدّر PNG و PDF من PowerPoint (حوالي 3 دقايق). من غير PowerPoint:
  `--no-export` (الـ PPTX بس).
- اختياري: `.venv\Scripts\python.exe -m matn_deck.demo_phrasing` بيخلي الموديل يقترح عناوين، و
  `demo_build --model-phrases` بيستخدمها بعد الفحص. **مش للديمو**: في المراجعة الموديل كتب عناوين أرقامها صح
  ومعناها غلط.
- الـ test split مقفول: الأدوات دي بتقرا الـ dev gold بس.
