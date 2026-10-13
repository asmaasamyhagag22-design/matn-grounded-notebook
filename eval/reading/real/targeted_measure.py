"""Measure a mixed AI reference with a complete, separately preserved owner audit.

No human answer is generated. Original AI snapshots and full-page GT stay unchanged.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime
from pathlib import Path
from .review import HERE, REPO
from .sample import digest, statistics, validate_records
from .sample_review import require_committed
from .import_answers import valid_answer
from .targeted_audit import INITIAL, FIRST, LATEST, PLAN, load_inputs, select_problems, original_embedded_images
from .verify import verify_sources

ANSWERS = HERE / 'targeted-audit-answers-asmaa-20261010.json'
MIXED = HERE / 'sample-mixed-reference-20261010.json'
REPORT = REPO / 'reports/step4c-targeted-sample-metrics'


def validate_export(export, plan):
    key = json.dumps([[plan['batch'], digest(plan)]], separators=(',', ':'))
    if export.get('schema') != 'matn-human-sample-answers/1' or export.get('manifest_key') != key:
        raise ValueError('Wrong frozen targeted-audit identity')
    answers = export.get('answers')
    if not isinstance(answers, dict) or set(answers) != set(plan['review_order']):
        raise ValueError('Targeted audit must contain exactly every planned item')
    for item_id, answer in answers.items():
        if not valid_answer(answer) or answer['verified_by'].strip().casefold() != 'asmaa':
            raise ValueError('Missing signed owner answer: ' + item_id)
        try:
            timestamp = datetime.fromisoformat(answer['verified_at'].replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                raise ValueError('missing timezone')
        except (ValueError, TypeError):
            raise ValueError('Invalid owner answer timestamp: ' + item_id) from None
    history = export.get('history')
    if not isinstance(history, list) or any(not isinstance(h, dict) or h.get('item_id') not in answers
            or not valid_answer(h.get('answer')) or h['answer']['verified_by'].strip().casefold() != 'asmaa'
            for h in history):
        raise ValueError('Invalid targeted-audit history')
    if {h['item_id']: h['answer'] for h in history} != answers:
        raise ValueError('Current answers do not match exported history')


def build_mixed_reference(sample, first, latest, plan, export):
    if plan != select_problems(sample, first, latest):
        raise ValueError('Changed frozen targeted-audit plan')
    validate_export(export, plan)
    audited = set(plan['review_order']); agreement = set(plan['three_way_agreement_not_audited'])
    if audited & agreement or audited | agreement != set(sample['review_order']):
        raise ValueError('Audit/agreement partition must cover original sample exactly once')
    by_id = {i['id']: i for i in sample['items']}
    answers = {}; changes = []
    for item_id in sample['review_order']:
        initial = latest['answers'][item_id]
        if item_id in audited:
            answer = dict(export['answers'][item_id])
            changed = (answer['kind'], answer['value_as_printed']) != (initial['kind'], initial['value_as_printed'])
            answer.update(review_number=initial['review_number'], reviewer_type='human', human_verified=True,
                          initial_annotation='model family A', targeted_audit='asmaa',
                          provenance='owner_targeted_audit', ai_annotation_before_audit={
                              'kind': initial['kind'], 'value_as_printed': initial['value_as_printed']})
            if changed:
                changes.append({'item_id': item_id, 'review_number': initial['review_number'],
                                'before': answer['ai_annotation_before_audit'],
                                'after': {'kind': answer['kind'], 'value_as_printed': answer['value_as_printed']}})
        else:
            item = by_id[item_id]
            if initial['kind'] != 'number' or initial['value_as_printed'] != item['reader1'] or initial['value_as_printed'] != item.get('reader2'):
                raise ValueError('Unaudited item lacks three-way agreement: ' + item_id)
            answer = dict(initial)
            answer.update(initial_annotation='model family A', targeted_audit=None,
                          provenance='ai_three_way_agreement_not_human_audited')
        answers[item_id] = answer
    return {'schema': 'matn-mixed-sample-reference/1',
            'provenance_statement': 'initial annotation: model family A; targeted audit: asmaa',
            'reviewer_type': 'mixed', 'all_items_human_verified': False,
            'sample_manifest_sha256': digest(sample), 'audit_manifest_sha256': digest(plan),
            'initial_ai_reference_sha256': digest(first), 'latest_ai_reference_sha256': digest(latest),
            'owner_export_sha256': digest(export), 'human_audited_ids': plan['review_order'],
            'unaudited_three_way_agreement_ids': plan['three_way_agreement_not_audited'],
            'changes_from_latest_ai': changes, 'answers': answers}


def import_export(path):
    sample, first, latest = load_inputs()
    plan = json.loads(PLAN.read_text(encoding='utf8'))
    raw = path.read_bytes(); export = json.loads(raw)
    build_mixed_reference(sample, first, latest, plan, export)
    if ANSWERS.exists():
        if ANSWERS.read_bytes() != raw:
            raise ValueError('Owner audit archive is immutable; do not overwrite')
    else:
        with ANSWERS.open('xb') as handle:
            handle.write(raw)
    print(f'Archived {len(export["answers"])} owner answers unchanged: {ANSWERS}; commit before measurement')


def publish():
    from eval.reading.closeout import OUT
    for path in (INITIAL, FIRST, LATEST, PLAN, ANSWERS):
        require_committed(path)
    sample, first, latest = load_inputs()
    plan = json.loads(PLAN.read_text(encoding='utf8'))
    export = json.loads(ANSWERS.read_text(encoding='utf8'))
    states = verify_sources()
    for doc, expected in sample['sources'].items():
        if states.get(doc, {}).get('status') != 'ok' or states[doc]['actual'] != expected:
            raise ValueError('Changed or missing sampled real source: ' + doc)
    validate_records(sample, OUT / 'final/real')
    original_embedded_images(sample, latest, (HERE / 'model-annotations.html').read_text(encoding='utf8'))
    mixed = build_mixed_reference(sample, first, latest, plan, export)
    gaokey = 'gao_cg_annual_report_1990'
    if states[gaokey]['status'] == 'mismatch':
        raise ValueError('GAO source SHA256 mismatch; no substitution allowed')
    result = {'schema': 'matn-targeted-mixed-sample-metrics/1',
              'provenance_statement': mixed['provenance_statement'],
              'reviewer_type': 'mixed', 'all_items_human_verified': False,
              'human_audited': len(mixed['human_audited_ids']),
              'ai_agreement_only': len(mixed['unaudited_three_way_agreement_ids']),
              'mixed_reference_sha256': digest(mixed), 'owner_export_sha256': digest(export),
              'audit_manifest_sha256': digest(plan), 'sample_manifest_sha256': digest(sample),
              'human_audited_ids': mixed['human_audited_ids'],
              'unaudited_three_way_agreement_ids': mixed['unaudited_three_way_agreement_ids'],
              'changes_from_latest_ai': mixed['changes_from_latest_ai'],
              'sources': states,
              'gao': 'DEFERRED: owner permits NBS and StatAb to close 4c; add when manually supplied' if states[gaokey]['status'] == 'missing' else 'PRESENT: separate 15+15 review required',
              'limitation': 'Conditional on a mixed reference: 43 targeted human audits and 137 unaudited AI/reader agreements. '
                            'Agreement can be wrong in all three readers. Audit selection was not random or independent of predictions; '
                            'binomial intervals do not account for unaudited labeling error, correlated errors or targeted-selection bias. '
                            'Synthetic holdout-2 remains primary; no full-page accuracy or missed-number recall claim.',
              **statistics(sample, mixed['answers'])}
    by_id = {i['id']: i for i in sample['items']}
    result['silent_error_items'] = [
        {'item_id': item_id, 'review_number': a['review_number'], 'reader1': by_id[item_id]['reader1'],
         'reference': a['value_as_printed'], 'kind': a['kind'], 'provenance': a['provenance']}
        for item_id, a in mixed['answers'].items()
        if not by_id[item_id]['flagged'] and a['kind'] != 'illegible'
        and (a['kind'] != 'number' or a['value_as_printed'] != by_id[item_id]['reader1'])]
    for path, data in ((MIXED, mixed), (REPORT.with_suffix('.json'), result)):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    pct = lambda v: '—' if v is None else f'{v:.2%}'
    def row(label, values):
        f, a = values['flagged'], values['accepted']; ci = f['wilson_95']
        return (f'| {label} | {f["false_alarms"]}/{f["n"]} | {pct(f["rate"])} | '
                f'{"—" if ci is None else pct(ci[0])+" – "+pct(ci[1])} | '
                f'{a["silent_errors"]}/{a["n"]} | {pct(a["rate"])} | {pct(a["exact_binomial_upper_95"])} | '
                f'{pct(a["rule_of_three_upper_approx"])} | {f["illegible"] + a["illegible"]} |')
    report = ['# Step 4c — القياس بعد targeted audit', '',
              '**initial annotation: model family A; targeted audit: asmaa**', '',
              f'المراجعة البشرية **{result["human_audited"]}/180**؛ الباقي **{result["ai_agreement_only"]}/180** AI مع exact three-way agreement، مش human-verified.',
              f'إجابات المالكة اتنقلت bytes من Downloads بدون تعديل قيمة أو method/timestamp؛ ملف الأصل `{ANSWERS.relative_to(REPO)}`.',
              f'Export canonical SHA256: `{digest(export)}`؛ mixed reference SHA256: `{digest(mixed)}`.', '',
              '| العينة / الصفحة | false alarms | rate | Wilson 95% | silent errors | rate | exact upper 95% | 3/n لو صفر | illegible |',
              '|---|---:|---:|---|---:|---:|---:|---:|---:|', row('كل العينة', result)]
    report += [row(p, v) for p, v in result['pages'].items()]
    report += ['', 'false-alarm rate هنا correct reader1 وسط flagged، مش population FPR. بعض flags دلالية ومبررة.',
               'Wilson two-sided95% وClopper-Pearson exact one-sided95% conditional على المرجع المختلط؛ مش ضمان human accuracy لكل180 ولا exact stratified-population intervals.',
               'الاختيار للمراجعة targeted وباين فيه predictions؛137 untouched ممكن يحصل فيهم correlated wrong agreement. الأرقام مش missing-number recall ولا full-page accuracy.',
               'Illegible خارج المقام ويُذكر منفصلًا؛ بعد أجوبة المالكة العدد0. مفيش تعديل أو normalization لقيمها: المقارنة exact string بالقواعد المجمّدة.',
               'Rule of three: لو صفر أخطاء من100 يبقى تقريب3/n=3%، والـexact=2.9513%. هنا1/100 فالـ3/n غير مطبق؛exact upper هو4.66%.',
               'Population-weighted point estimates: '+json.dumps(result['population_weighted_point_estimates']), '',
               '## كل اختلاف صامت', '', '| Sample # | Item id | reader1 | مرجع المالكة | النسبة |', '|---:|---|---|---|---|']
    report += [f'| {i["review_number"]} | `{i["item_id"]}` | {i["reader1"]} | {i["reference"] or i["kind"]} | {i["provenance"]} |' for i in result['silent_error_items']]
    report += ['', '## العناصر اللي راجعتها asmaa — كل43', '',
               '| Sample # | Item id | model قبل owner audit | إجابة asmaa | method |', '|---:|---|---|---|---|']
    for item_id in plan['review_order']:
        a = mixed['answers'][item_id]; before = a['ai_annotation_before_audit']
        report.append(f'| {a["review_number"]} | `{item_id}` | {before["value_as_printed"] or before["kind"]} | {a["value_as_printed"] or a["kind"]} | {a["method"]} |')
    report += ['', f'عدد التغييرات مقارنة آخر AI snapshot: **{len(mixed["changes_from_latest_ai"])}**؛ محفوظة before/after في JSON.', '',
               '## العناصر اللي تعتمد على three-way agreement فقط — كل137', '', '| Sample # | Item id | model = reader1 = reader2 |', '|---:|---|---|']
    for item_id in plan['three_way_agreement_not_audited']:
        a = mixed['answers'][item_id]
        report.append(f'| {a["review_number"]} | `{item_id}` | {a["value_as_printed"]} |')
    report += ['', 'GAO: '+result['gao'], '', 'Holdout-2 synthetic gate remains primary PASS: raw10 / reader-attributed0؛no OCR tuning.', '']
    REPORT.with_suffix('.md').write_text('\n'.join(report), encoding='utf8')
    print(json.dumps({k: result[k] for k in ('human_audited', 'ai_agreement_only', 'flagged', 'accepted', 'gao')}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-export', type=Path)
    args = parser.parse_args()
    import_export(args.import_export) if args.import_export else publish()


if __name__ == '__main__':
    main()
