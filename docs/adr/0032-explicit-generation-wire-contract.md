# 0032 — Explicit generation shape and bounded prose grammar

2 نوفمبر 2026، قبل قياس أسئلة القبول. أول60attemptطلعوا أسئلة أوcopies في معظمهم:36span/sentenceفريدين،وصفرردمولّد ناجح. ده generation failure،مش قياسfalseblocks صالح. المحاولات والـ6generation/84nativeمحفوظين. البديل60صياغةdevelopmentمختلفةمتربطةبنفسGAO+CCBYspans؛author self-review AI،مشhuman gold.

أداةالـstructuredoutputبتقيّدالصياغةومابتشرحشمعنىالحقولللموديل. لذلك promptsبقتتشرحJSONshapeصراحة:claimهيجملةالإجابةومشالسؤال؛والـplanيختارspansبس. اتضافمثالstyleواضحغيرمحسوبكـevidence. إصلاحschema:patternsمقفولةبـ^و$وبتمنعسؤالًاكـclaim؛دهشرطreplyمشإذنحقيقة. التفاصيلوالقيودفي[الدليلالرسمي](https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md).

الـrepairبياخدسببsource_copy_not_answerصريحفيtrace،بدلرسالةunsupportedغامضة؛مسموحلهيرتبالجملةمنجديدمعالحفاظعلىactor/modal/qualifiers. الـL0–L4والـcutoffوالـscopeوالـregistryثابتين. مفيشruleاتحركبعدقياسacceptance؛الـ20سؤاللسهمااتشغلوش.
