"""Frozen, page-stratified real-scan draws; owner answers are never inferred from OCR.

No OCR or downloads here. GAO is a separate immutable extension, never a redraw.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from .review import HERE, make_proposals
from .verify import require_verified, verify_sources

SEED = 20261006
INITIAL = HERE / 'sample-frozen-20261006.json'
GAO = HERE / 'sample-gao-frozen-20261006.json'


def digest(data):
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf8')).hexdigest()


def rank(seed, domain, key):
    return hashlib.sha256(f'{seed}:{domain}:{key}'.encode('utf8')).digest()


def allocate(populations, count, minimum=5):
    """Constrained proportional allocation, largest remainder; ties by page key."""
    populations = dict(sorted(populations.items()))
    lower = {p: min(minimum, n) for p, n in populations.items()}
    if count > sum(populations.values()) or count < sum(lower.values()):
        raise ValueError('Requested sample cannot satisfy population/minimum constraints')
    fixed = {}; active = dict(populations)
    while active:
        remaining = count - sum(fixed.values())
        total = sum(active.values())
        shares = {p: remaining * n / total if total else 0 for p, n in active.items()}
        clamped = {p: lower[p] for p in active if shares[p] < lower[p]}
        if not clamped:
            break
        fixed.update(clamped)
        active = {p: n for p, n in active.items() if p not in clamped}
    shares = shares if active else {}
    quotas = {**fixed, **{p: math.floor(v) for p, v in shares.items()}}
    for p in sorted(active, key=lambda p: (-(shares[p] - quotas[p]), p))[:count - sum(quotas.values())]:
        quotas[p] += 1
    assert sum(quotas.values()) == count
    assert all(lower[p] <= quotas[p] <= n for p, n in populations.items())
    return dict(sorted(quotas.items()))


def draw(groups, count, seed, domain):
    quotas = allocate({p: len(values) for p, values in groups.items()}, count)
    return [(p, i) for p in sorted(groups)
            for i in sorted(groups[p], key=lambda i: rank(seed, domain, f'{p}:{i}'))[:quotas[p]]]


def freeze(path, data):
    encoded = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    if path.exists():
        if json.loads(path.read_text(encoding='utf8')) != data:
            raise ValueError(f'Frozen sample is immutable: {path}')
        return
    # Exclusive creation: neither a resumed run nor an extension can overwrite a draw.
    with path.open('x', encoding='utf8', newline='\n') as handle:
        handle.write(encoded)


def validate_records(manifest, folder):
    for page, expected in manifest['records'].items():
        path = folder / (page + '.json')
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Frozen prediction record changed or missing: {page}')


def manifests():
    if not INITIAL.is_file():
        raise ValueError('Freeze the initial sample before generating or reviewing')
    return [json.loads(p.read_text(encoding='utf8')) for p in (INITIAL, GAO) if p.is_file()]


def create_sample(gao=False):
    from eval.reading.closeout import OUT
    from PIL import Image
    target = GAO if gao else INITIAL
    if target.exists():
        existing = json.loads(target.read_text(encoding='utf8'))
        validate_records(existing, OUT / 'final/real')
        for doc in existing['sources']:
            require_verified(doc)
        print(f'Already frozen; unchanged: {target}')
        return existing
    states = verify_sources()
    batch = 'gao' if gao else 'initial'
    source_specs = json.loads((HERE / 'sources.json').read_text(encoding='utf8'))['documents']
    pages = {}; hashes = {}; sources = {}; groups = {'flagged': {}, 'accepted': {}}
    for doc in source_specs:
        key = doc['doc_key']
        if ('gao_' in key) != gao:
            continue
        if states[key]['status'] != 'ok':
            raise ValueError(f'BLOCKED-ON-OWNER: verified source required: {key}')
        require_verified(key)
        sources[key] = states[key]['actual']
        for spec in doc['gt_pages']:
            page = f"{key}_p{spec['page_index']:04d}"
            path = OUT / 'final/real' / (page + '.json')
            record = json.loads(path.read_text(encoding='utf8'))
            hashes[page] = hashlib.sha256(path.read_bytes()).hexdigest()
            image_path = HERE / 'review_assets' / (page + '.png')
            if not image_path.exists():
                from matn_reading.ocr.preprocess import render_page_image
                image_path.parent.mkdir(exist_ok=True)
                render_page_image(require_verified(key), spec['page_index']).save(image_path)
            image = Image.open(image_path)
            proposals = make_proposals(record['tokens'], record['text_layer'],
                                       record['preprocess']['rotation_deg'], image.size, record['cropbox'])
            image.close()
            lines = {line['index']: line['text'] for line in record['lines']}
            # Sampling unit is a detected reader-1 token. Layer/r2-only proposals are not this population.
            pages[page] = [{**p, 'context': lines.get(t['line'], t['word'])}
                           for p, t in zip(proposals, record['tokens'])]
            for group, flag in [('flagged', True), ('accepted', False)]:
                groups[group][page] = [i for i, t in enumerate(record['tokens']) if t['flagged'] == flag]
    counts = {'flagged': 15 if gao else 80, 'accepted': 15 if gao else 100}
    items = []
    for group, count in counts.items():
        for page, index in draw(groups[group], count, SEED, batch + ':' + group):
            p = pages[page][index]
            items.append({k: v for k, v in {
                **p, 'id': f'{batch}:{page}:t{index:04d}', 'page': page, 'token_index': index
            }.items() if k != 'chosen'})
    data = {'schema': 'matn-real-sample/1', 'batch': batch, 'seed': SEED,
            'frozen_at': datetime.now(timezone.utc).isoformat(),
            'method': 'SHA256 seeded random ranks without replacement within page; constrained proportional largest remainder; minimum min(5, population); separate blind-order domain',
            'unit': 'reader-1 detected numeric token; excludes layer/r2-only proposals and cannot measure missed-number recall',
            'sources': sources, 'records': hashes,
            'populations': {p: {g: len(groups[g][p]) for g in groups} for p in sorted(pages)},
            'quotas': {g: allocate({p: len(v) for p, v in groups[g].items()}, n) for g, n in counts.items()},
            'items': items,
            'review_order': [i['id'] for i in sorted(items, key=lambda i: rank(SEED, batch + ':blind-order', i['id']))],
            'pending': [] if gao else ['GAO 1990: source unavailable; separate 15 flagged + 15 accepted immutable extension with this seed; initial 180 unchanged']}
    if gao:
        data['initial_manifest_sha256'] = digest(json.loads(INITIAL.read_text(encoding='utf8')))
    freeze(target, data)
    print(f'Frozen {len(items)} items: {target}; manifest sha256 {digest(data)}')
    return data


def blind_payload(manifest, assets):
    by_id = {i['id']: i for i in manifest['items']}
    return {'batch': manifest['batch'], 'manifest_sha256': digest(manifest),
            'items': [{**{k: by_id[item_id][k] for k in ('id', 'page', 'reader1', 'reader2', 'layer', 'context', 'bbox')},
                       **assets[item_id]} for item_id in manifest['review_order']]}


def read_answers(manifest, folder):
    answers = {}
    for page in sorted({i['page'] for i in manifest['items']}):
        gt = json.loads((folder / (page + '.json')).read_text(encoding='utf8'))
        doc, index = page.rsplit('_p', 1)
        if gt.get('doc_key') != doc or gt.get('page_index') != int(index):
            raise ValueError(f'Wrong GT page identity: {page}')
        review = gt.get('sample_reviews', {}).get(manifest['batch'])
        if review is None:
            continue
        if review.get('manifest_sha256') != digest(manifest):
            raise ValueError(f'GT belongs to another frozen manifest: {page}')
        expected_ids = {i['id'] for i in manifest['items'] if i['page'] == page}
        if not set(review['answers']).issubset(expected_ids):
            raise ValueError(f'Unknown sample answer in {page}')
        answers.update(review['answers'])
    return answers


def wilson(k, n):
    if not n:
        return None
    z = 1.959963984540054
    p = k / n; denominator = 1 + z * z / n
    middle = (p + z * z / (2 * n)) / denominator
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [max(0, middle - radius), min(1, middle + radius)]


def binomial_upper(k, n, alpha=.05):
    """One-sided Clopper-Pearson upper bound: Pr_p(X <= k) = alpha."""
    if not n:
        return None
    if k == n:
        return 1.0
    if k == 0:
        return -math.expm1(math.log(alpha) / n)
    low, high = 0., 1.
    for _ in range(80):
        p = (low + high) / 2
        cdf = sum(math.exp(math.lgamma(n + 1) - math.lgamma(j + 1) - math.lgamma(n - j + 1)
                           + j * math.log(p) + (n - j) * math.log1p(-p)) for j in range(k + 1))
        if cdf > alpha:
            low = p
        else:
            high = p
    return (low + high) / 2


def statistics(manifest, answers):
    missing = []
    for item in manifest['items']:
        a = answers.get(item['id'], {})
        if (not a.get('verified_by') or a.get('kind') not in ('number', 'not_number', 'illegible')
                or (a.get('kind') == 'number' and not str(a.get('value_as_printed') or '').strip())):
            missing.append(item['id'])
    if missing:
        raise ValueError(f'BLOCKED-ON-OWNER: {len(missing)} unanswered/unsigned sample items; owner must review all drawn items')

    def aggregate(items, flagged):
        selected = [i for i in items if i['flagged'] == flagged]
        readable = [i for i in selected if answers[i['id']]['kind'] != 'illegible']
        correct = sum(answers[i['id']]['kind'] == 'number' and
                      answers[i['id']]['value_as_printed'].strip() == i['reader1'] for i in readable)
        k = correct if flagged else len(readable) - correct
        result = {'sampled': len(selected), 'n': len(readable), 'illegible': len(selected) - len(readable),
                  'rate': k / len(readable) if readable else None}
        if flagged:
            result.update(false_alarms=k, wilson_95=wilson(k, len(readable)))
        else:
            result.update(silent_errors=k, exact_binomial_upper_95=binomial_upper(k, len(readable)),
                          rule_of_three_upper_approx=3 / len(readable) if readable and k == 0 else None)
        return result

    pages = {p: {g: aggregate([i for i in manifest['items'] if i['page'] == p], g == 'flagged')
                 for g in ('flagged', 'accepted')} for p in sorted(manifest['populations'])}
    result = {g: aggregate(manifest['items'], g == 'flagged') for g in ('flagged', 'accepted')}
    result['pages'] = pages
    result['population_weighted_point_estimates'] = {
        g: sum(manifest['populations'][p][g] * (pages[p][g]['rate'] or 0) for p in pages) /
           sum(manifest['populations'][p][g] for p in pages)
        if all(pages[p][g]['rate'] is not None or manifest['populations'][p][g] == 0 for p in pages)
        and sum(manifest['populations'][p][g] for p in pages) else None
        for g in ('flagged', 'accepted')}
    result['interval_scope'] = ('Unweighted reviewed-sample binomial summaries: Wilson two-sided 95%; '
        'Clopper-Pearson one-sided 95%. Stratified quotas/minimums mean these are not exact design-based '
        'population intervals. Population-weighted point estimates are separate; illegible exclusion may bias them. '
        'No missed-number recall or full-page accuracy claim; holdout-2 remains primary evidence.')
    return result


def measure_samples():
    from eval.reading.closeout import OUT
    results = []
    for manifest in manifests():
        for doc in manifest['sources']:
            require_verified(doc)
        validate_records(manifest, OUT / 'final/real')
        results.append({'batch': manifest['batch'], 'manifest_sha256': digest(manifest),
                        **statistics(manifest, read_answers(manifest, HERE / 'gt'))})
    target = OUT / 'real-sample-metrics.json'
    target.write_text(json.dumps({'batches': results, 'gao': 'measured' if GAO.exists() else
                                 'BLOCKED-ON-OWNER: approved GAO source missing; 30-item extension pending'},
                                ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'extend-gao', 'measure'])
    args = parser.parse_args()
    if args.action == 'measure':
        measure_samples()
    else:
        create_sample(args.action == 'extend-gao')


if __name__ == '__main__':
    main()
