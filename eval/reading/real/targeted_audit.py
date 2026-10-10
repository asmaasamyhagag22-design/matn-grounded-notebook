"""Freeze and display only problematic items from the existing 180-item AI sample.

No new draw, random controls, OCR, or human answers. Human audit is a separate layer.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import re
from collections import Counter
from .review import HERE, REPO
from .sample import INITIAL, digest, freeze
from .sample_review import require_committed, render_sample_html

FIRST = HERE / 'gpt-annotations-20261006.json'
LATEST = HERE / 'gpt-annotations-20261006-audited.json'
PLAN = HERE / 'targeted-audit-problems-20261010.json'
PAGE = HERE / 'targeted-review.html'


def answer_key(answer):
    return answer['kind'], answer['value_as_printed']


def select_problems(sample, first, latest):
    wanted = {i['id'] for i in sample['items']}
    for reference in (first, latest):
        if reference['manifest_sha256'] != digest(sample) or set(reference['answers']) != wanted:
            raise ValueError('AI reference does not match the complete frozen sample')
        if reference.get('reviewer_type') != 'model' or reference.get('human_verified') is not False:
            raise ValueError('Initial annotation must retain AI provenance')
    selected = []
    by_id = {i['id']: i for i in sample['items']}
    for item_id in sample['review_order']:
        item = by_id[item_id]; before = first['answers'][item_id]; after = latest['answers'][item_id]
        reasons = []
        if answer_key(before) != answer_key(after):
            reasons.append('AI snapshots differ')
        if after['kind'] == 'illegible':
            reasons.append('AI: illegible')
        if after['kind'] != 'number' or after['value_as_printed'] != item['reader1']:
            reasons.append('AI differs from reader 1')
        if not item.get('reader2'):
            reasons.append('Reader 2 unavailable')
        elif after['kind'] != 'number' or after['value_as_printed'] != item['reader2']:
            reasons.append('AI differs from reader 2')
        if reasons:
            selected.append({'id': item_id, 'original_review_number': after['review_number'],
                             'page': item['page'], 'reasons': reasons})
    # Changes and abstentions first; stable original review order within each priority.
    selected.sort(key=lambda i: (0 if 'AI snapshots differ' in i['reasons'] else
                                 1 if 'AI: illegible' in i['reasons'] else 2,
                                 i['original_review_number']))
    selected_ids = {i['id'] for i in selected}
    agreement = [i for i in sample['review_order'] if i not in selected_ids]
    return {'schema': 'matn-targeted-ai-audit/1', 'batch': 'targeted-audit',
            'initial_annotation': 'GPT (Codex)', 'targeted_audit': 'pending: asmaa',
            'sample_manifest_sha256': digest(sample),
            'first_reference_sha256': digest(first), 'latest_reference_sha256': digest(latest),
            'selection': 'Union: changed AI values/kinds, AI illegible, AI mismatch with either reader; missing reader 2 included. Problems only; no random controls by owner instruction.',
            'random_control_count': 0, 'items': selected,
            'review_order': [i['id'] for i in selected],
            'three_way_agreement_not_audited': agreement,
            'reason_counts': dict(Counter(r for i in selected for r in i['reasons']))}


def load_inputs():
    return [json.loads(p.read_text(encoding='utf8')) for p in (INITIAL, FIRST, LATEST)]


def make_plan():
    for path in (INITIAL, FIRST, LATEST):
        require_committed(path)
    plan = select_problems(*load_inputs())
    freeze(PLAN, plan)
    print(f'Frozen targeted audit: {len(plan["items"])} problems; no random controls; {len(plan["three_way_agreement_not_audited"])} unaudited three-way agreements')


def render_targeted(payload):
    source = render_sample_html([payload])
    source = source.replace('Matn · sampled number review', 'Matn · targeted AI audit')
    source = source.replace('Sampled number review · مراجعة العينة', 'Problem items · مراجعة الحالات اللي عليها مشاكل')
    source = source.replace('Sampling status is hidden.', 'Initial annotation: GPT (Codex). Targeted audit: asmaa (pending). No random items.')
    source = source.replace('id="owner" autocomplete="name"', 'id="owner" value="asmaa" autocomplete="name"')
    source = source.replace('<button id="folder">', '<button id="folder" hidden disabled>')
    source = source.replace('<div class="keys">', '<p id="aiReading"></p><p id="auditReason"></p><div class="keys"><button id="aiAccept">G · Confirm current GPT reading</button>')
    source = source.replace("link.download='matn-human-sample-answers.json'", "link.download='matn-targeted-audit-answers.json'")
    source = source.replace('Sample complete.', 'Targeted audit complete.')
    source = source.replace('No full-page review is required.', 'Only these problem items are audited; other items remain AI annotations with reader agreement.')
    source = source.replace("'r1','r2','r3','type','illegible','notNumber','back'", "'r1','r2','r3','type','illegible','notNumber','back','aiAccept'")
    source = source.replace("const item=current();if(!item)return;", """const item=current();if(!item)return;
 el('aiReading').textContent='GPT initial: '+item.ai_before+' → current: '+item.ai_current+' · original sample #'+item.original_review_number;
 el('auditReason').textContent='Audit reasons: '+item.audit_reasons.join('; ');
 el('aiAccept').textContent='G · Confirm GPT: '+item.ai_current;""")
    source = source.replace("el('r1').onclick=", "el('aiAccept').onclick=()=>choose(current().ai_kind,current().ai_value,'confirm-ai-after-scan-review');\nel('r1').onclick=")
    source = source.replace("'t':'type','x':'illegible'", "'t':'type','g':'aiAccept','x':'illegible'")
    source = source.replace('1 / 2 / 3 choose that reading;', 'G confirms the displayed GPT reading after checking the scan; 1 / 2 / 3 choose that reading;')
    source = source.replace('Chrome/Edge can also choose eval/reading/real/gt for direct saving.', 'This audit saves separately; export JSON when finished.')
    return source


def original_embedded_images(sample, reference, annotation_html):
    """Use the archived original PNG bytes, independent of Linux crop regeneration."""
    encoded = re.findall(r'src="data:image/png;base64,([^"\s]+)"', annotation_html)
    if len(encoded) != 2 * len(sample['review_order']):
        raise ValueError('Wrong archived annotation image count')
    images = {}
    for index, item_id in enumerate(sample['review_order']):
        images[item_id] = {}
        for offset, (key, sha) in enumerate([('crop', 'crop_sha256'), ('context_crop', 'context_sha256')]):
            content = encoded[2 * index + offset]
            data = base64.b64decode(content, validate=True)
            if hashlib.sha256(data).hexdigest() != reference['answers'][item_id]['images'][sha]:
                raise ValueError('Changed archived AI scan image: ' + item_id)
            images[item_id][key] = 'data:image/png;base64,' + content
    return images


def generate():
    for path in (INITIAL, FIRST, LATEST, PLAN):
        require_committed(path)
    sample, first, latest = load_inputs()
    plan = json.loads(PLAN.read_text(encoding='utf8'))
    if plan != select_problems(sample, first, latest):
        raise ValueError('Frozen targeted audit changed')
    by_id = {i['id']: i for i in sample['items']}
    originals = original_embedded_images(sample, latest, (HERE / 'gpt-annotations.html').read_text(encoding='utf8'))
    items = []
    for selected in plan['items']:
        item_id = selected['id']; item = by_id[item_id]; after = latest['answers'][item_id]; before = first['answers'][item_id]
        images = originals[item_id]
        label = lambda a: a['value_as_printed'] if a['kind'] == 'number' else a['kind']
        items.append({**{k: item[k] for k in ('id', 'page', 'reader1', 'reader2', 'layer', 'context', 'bbox')},
                      **images, 'ai_before': label(before), 'ai_current': label(after),
                      'ai_kind': after['kind'], 'ai_value': after['value_as_printed'],
                      'audit_reasons': selected['reasons'], 'original_review_number': selected['original_review_number']})
    payload = {'batch': plan['batch'], 'manifest_sha256': digest(plan), 'items': items}
    PAGE.write_text(render_targeted(payload), encoding='utf8')
    print(f'{PAGE}: {len(items)} items; no human answers generated')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'generate'])
    args = parser.parse_args()
    (make_plan if args.action == 'freeze' else generate)()


if __name__ == '__main__':
    main()
