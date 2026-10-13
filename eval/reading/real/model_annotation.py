"""Measure the explicitly delegated model reference separately from human GT."""
import base64
import hashlib
import html
import json

from .sample import INITIAL, digest, statistics, validate_records
from .sample_review import require_committed
from .verify import require_verified

REFERENCE = INITIAL.parent / 'model-annotations-20261006-audited.json'


def measure_reference(manifest, reference, root):
    if (reference.get('schema') != 'matn-model-sample-annotations/1'
            or reference.get('manifest_sha256') != digest(manifest)):
        raise ValueError('Wrong model-reference schema or frozen manifest')
    if reference.get('reviewer_type') != 'model' or reference.get('human_verified') is not False:
        raise ValueError('model reference must explicitly declare model provenance, human_verified=false')
    answers = reference['answers']
    if set(answers) != {i['id'] for i in manifest['items']}:
        raise ValueError('Model reference must contain exactly every frozen sample item')
    for number, item_id in enumerate(manifest['review_order'], 1):
        answer = answers[item_id]
        if (answer.get('review_number') != number or answer.get('reviewer_type') != 'model'
                or answer.get('human_verified') is not False):
            raise ValueError('Wrong review order or answer provenance: ' + item_id)
        for key, sha in [('crop', 'crop_sha256'), ('context_crop', 'context_sha256')]:
            path = (root / answer['images'][key]).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError('Image outside reference workspace')
            if hashlib.sha256(path.read_bytes()).hexdigest() != answer['images'][sha]:
                raise ValueError('Changed annotation image: ' + item_id)
    measured = statistics(manifest, answers)
    differences = []
    for item in manifest['items']:
        answer = answers[item['id']]
        if answer['kind'] != 'illegible' and (answer['kind'] != 'number'
                or answer['value_as_printed'].strip() != item['reader1']):
            differences.append({'item_id': item['id'], 'review_number': answer['review_number'],
                                'page': item['page'], 'flagged': item['flagged'],
                                'reader1': item['reader1'], 'kind': answer['kind'],
                                'model_reference': answer['value_as_printed'], 'note': answer.get('note', '')})
    return {'schema': 'matn-model-sample-metrics/1', 'reviewer_type': 'model', 'human_verified': False,
            'manifest_sha256': digest(manifest), 'reference_sha256': digest(reference),
            'limitation': 'Conditional on fallible model annotations; intervals do not account for annotation '
                          'error or post-comparison corrections. This is not independent human validation. '
                          'Synthetic holdout-2 remains the primary evidence; no OCR tuning.',
            **measured, 'differences': differences}


def render_reference(manifest, reference, root):
    escape = html.escape
    rows = []
    for item_id in manifest['review_order']:
        a = reference['answers'][item_id]
        value = a['value_as_printed'] if a['kind'] == 'number' else a['kind']
        images = []
        for key in ('crop', 'context_crop'):
            encoded = base64.b64encode((root / a['images'][key]).read_bytes()).decode('ascii')
            images.append(f'<img alt="{key}" src="data:image/png;base64,{encoded}">')
        rows.append(f'<details><summary>#{a["review_number"]} · {escape(value)} · '
                    f'{escape(item_id)}</summary><p>{escape(a.get("note", ""))}</p>'
                    + ''.join(images) + '</details>')
    return ('<!doctype html><html lang="ar"><meta charset="utf-8"><title>model annotations</title>'
            '<style>body{font:20px system-ui;max-width:1200px;margin:30px auto;padding:20px}'
            'details{border:1px solid #bbb;padding:15px;margin:10px 0}summary{cursor:pointer}'
            'img{display:block;min-width:300px;max-width:100%;margin:15px 0;image-rendering:auto}</style>'
            '<h1>مراجعة model للـ180 عنصر</h1><p dir="rtl">دي تعليقات نموذج على صور السكان، '
            'مش GT بشري مستقل. افتحي أي عنصر عشان تشوفي القراءة والصورة وسطر السياق. '
            'العرض للقراءة فقط؛ مفيش حفظ أو JavaScript أو ملفات صور خارجية.</p>'
            '<p>reviewer_type=model; human_verified=false. '
            f'Manifest SHA256: {digest(manifest)}; reference SHA256: {digest(reference)}</p>'
            + ''.join(rows) + '</html>')


def publish():
    from eval.reading.closeout import OUT, REPO
    require_committed(INITIAL)
    require_committed(REFERENCE)
    manifest = json.loads(INITIAL.read_text(encoding='utf8'))
    reference = json.loads(REFERENCE.read_text(encoding='utf8'))
    first_path = INITIAL.parent / 'model-annotations-20261006.json'
    require_committed(first_path)
    first = json.loads(first_path.read_text(encoding='utf8'))
    if digest(first) != reference['initial_annotation_sha256']:
        raise ValueError('Changed committed blind first pass')
    for source in manifest['sources']:
        require_verified(source)
    validate_records(manifest, OUT / 'final/real')
    result = measure_reference(manifest, reference, REPO)
    result.update(reference_file=REFERENCE.relative_to(REPO).as_posix(),
                  initial_annotation_commit=reference['initial_annotation_commit'],
                  initial_annotation_sha256=digest(first), amendments=reference['amendments'],
                  initial_pass_statistics=measure_reference(manifest, first, REPO))
    (REPO / 'reports/step4c-model-sample-metrics.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    percent = lambda v: '—' if v is None else f'{v:.2%}'
    def row(label, r):
        f, a = r['flagged'], r['accepted']; ci = f['wilson_95']
        return (f'| {label} | {f["false_alarms"]}/{f["n"]} | {percent(f["rate"])} | '
                f'{percent(ci[0])} – {percent(ci[1])} | {a["silent_errors"]}/{a["n"]} | '
                f'{percent(a["rate"])} | {percent(a["exact_binomial_upper_95"])} | '
                f'{percent(a["rule_of_three_upper_approx"])} | {f["illegible"] + a["illegible"]} |')
    report = ['# Step 4c — قياس العينة على تعليقات model', '',
              '**اتعمل:** مراجعة بصرية للـ180 عنصر من الست صفحات بطلب صاحبة المشروع. '
              'مرجع model منفصل؛ مفيش ادعاء GT بشري. الـ holdout-2 الصناعي لسه الأساسي وPASS. '
              'العينة وترتيبها وقواعد OCR وملفات GT البشرية التسعة ثابتين.', '',
              'النسخة الأولى اتثبتت في68da8c8 قبل المقارنة، بعد قراءة18 sheets من غير OCR readings/status. '
              'بعد المقارنة، اتعملت مراجعة تكبير لكل180 crop. اتصحّح رقمين، وعنصر اتحوّل لغير مقروء؛ '
              'النسخة الأولى محفوظة والتعديلات متسجلة تحت. النتيجة النهائية مش fully blind ولا human independent.', '',
              f'Manifest SHA256: `{result["manifest_sha256"]}`',
              f'Reference SHA256: `{result["reference_sha256"]}`', '',
              '| العينة / الصفحة | false alarms | rate | Wilson 95% | silent errors | rate | exact upper 95% | 3/n عند صفر | غير مقروء |',
              '|---|---:|---:|---|---:|---:|---:|---:|---:|', row('كل العينة', result)]
    report += [row(p, r) for p, r in result['pages'].items()]
    report += ['', 'غير المقروء خارج المقام ومش خطأ. الكشوف الجزئية/المجمعة أو الحرف اللي اتقري رقم '
               'بتتحسب خطأ كشف. المقارنة exact string بالقواعد الموجودة، من غير أي تعديل OCR. '
               'false alarms هنا عدد القراءات الصحيحة وسط flagged؛ بعض flags دلالية ومبررة.', '',
               'Wilson two-sided 95% وClopper–Pearson one-sided exact upper 95% ملخصات binomial '
               'للعينة، مش exact design-based population bounds. الـ intervals مش بتغطي أخطاء model '
               'أو أثر التصحيح بعد المقارنة. 3/n ينطبق عند صفر أخطاء بس؛ عند صفر من100، exact=2.9513% '
               'وتقريب3/n=3%؛ هنا في أخطاء فالتقريب مش مطبّق على المجموع.', '',
               'Population-weighted point estimates: '+json.dumps(result['population_weighted_point_estimates']), '',
               '## تعديلات مرجع model بعد المقارنة', '',
               '| عنصر العرض | قبل | بعد | السبب |', '|---|---|---|---|']
    report += [f'| #{c["review_number"]} | {c["before"]["value_as_printed"]} | '
               f'{c["after"]["value_as_printed"] or c["after"]["kind"]} | {c["reason"]} |'
               for c in reference['amendments']]
    report += ['', '## الاختلافات مع reader-1', '',
               '| العنصر | المجموعة | reader-1 | مرجع model | السبب |', '|---|---|---|---|---|']
    report += [f'| #{d["review_number"]} | {"flagged" if d["flagged"] else "accepted"} | '
               f'{d["reader1"]} | {d["model_reference"] or d["kind"]} | {d["note"]} |'
               for d in result['differences']]
    report += ['', '## الإغلاق', '', '| البند | الحالة | الدليل |', '|---|---|---|',
               '| D2 sampled GT complete — owner-delegated model reference | DONE | كل180 عنصر متراجع؛ model، human_verified=false |',
               '| D4 measured on sample — model reference | DONE | المقاييس والحدود فوق؛ مش تحقق بشري مستقل |',
               '| D3 GAO | BLOCKED-ON-OWNER | الملف المعتمد لسه مش موجود؛ بعدها إضافة15+15 ثابتة منفصلة |', '',
               'العرض: `eval/reading/real/model-annotations.html`، static و360 صورة embedded. '
               'إعادة القياس: `.venv\\Scripts\\python.exe -m eval.reading.real.model_annotation`.', '']
    (REPO / 'reports/step4c-model-sample-metrics.md').write_text('\n'.join(report), encoding='utf8')
    (INITIAL.parent / 'model-annotations.html').write_text(render_reference(manifest, reference, REPO), encoding='utf8')
    print('Published model sample metrics and static annotations; human_verified=false')


if __name__ == '__main__':
    publish()
