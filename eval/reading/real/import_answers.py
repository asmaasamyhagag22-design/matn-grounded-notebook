"""Import an owner's exported sample answers; never generate or infer any answer.

Usage: .venv/bin/python -m eval.reading.real.import_answers /path/to/export.json
Validates every batch/page before writing. Full-page GT and existing history are preserved.
Conflicting existing answers abort; exact repeat imports are idempotent.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from .sample import digest, manifests
from .sample_review import require_committed
from .sample import INITIAL, GAO
from .review import HERE


def valid_answer(answer):
    return (isinstance(answer, dict)
            and isinstance(answer.get('verified_by'), str) and bool(answer['verified_by'].strip())
            and answer.get('kind') in ('number', 'not_number', 'illegible')
            and isinstance(answer.get('verified_at'), str) and bool(answer['verified_at'])
            and isinstance(answer.get('method'), str) and bool(answer['method'])
            and (isinstance(answer.get('value_as_printed'), str) and bool(answer['value_as_printed'].strip())
                 if answer['kind'] == 'number' else answer.get('value_as_printed') is None))


def import_answers(export, folder, batches):
    expected_key = json.dumps([[b['batch'], digest(b)] for b in batches], separators=(',', ':'))
    if export.get('schema') != 'matn-human-sample-answers/1' or export.get('manifest_key') != expected_key:
        raise ValueError('Export does not match the frozen manifests')
    answers = export.get('answers')
    items = {i['id']: (b, i) for b in batches for i in b['items']}
    if not isinstance(answers, dict) or any(k not in items or not valid_answer(a) for k, a in answers.items()):
        raise ValueError('Invalid or unknown human sample answer')
    history = export.get('history')
    if not isinstance(history, list) or any(not isinstance(h, dict) or h.get('item_id') not in items
            or not valid_answer(h.get('answer')) for h in history):
        raise ValueError('Invalid exported answer history')
    latest = {h['item_id']: h['answer'] for h in history}
    if latest != answers:
        raise ValueError('Answers do not match the exported history')
    pending = {}
    for item_id, answer in answers.items():
        batch, item = items[item_id]
        path = folder / (item['page'] + '.json')
        if path not in pending:
            gt = json.loads(path.read_text(encoding='utf8'))
            doc, index = item['page'].rsplit('_p', 1)
            if gt.get('doc_key') != doc or gt.get('page_index') != int(index):
                raise ValueError('Wrong GT page identity: ' + item['page'])
            pending[path] = gt
        gt = pending[path]
        review = gt.setdefault('sample_reviews', {}).setdefault(batch['batch'], {
            'manifest_sha256': digest(batch), 'scope': 'frozen_sample_only', 'answers': {}, 'history': []})
        if review.get('manifest_sha256') != digest(batch):
            raise ValueError('GT manifest mismatch: ' + item['page'])
        allowed = {i['id'] for i in batch['items'] if i['page'] == item['page']}
        if not set(review['answers']).issubset(allowed):
            raise ValueError('Unknown existing GT answer')
        if item_id in review['answers'] and review['answers'][item_id] != answer:
            raise ValueError('Conflicting existing answer; no files changed: ' + item_id)
        review['answers'][item_id] = answer
        for event in history:
            if event['item_id'] == item_id and event not in review['history']:
                review['history'].append(event)
        review['status'] = ('sampled GT complete' if allowed.issubset(review['answers']) else 'sampled GT partial')
    # All input validation precedes the first write; atomic replacement per template.
    for path, gt in pending.items():
        encoded = json.dumps(gt, ensure_ascii=False, indent=2) + '\n'
        if path.read_text(encoding='utf8') == encoded:
            continue
        temporary = path.with_suffix('.json.import-tmp')
        with temporary.open('x', encoding='utf8') as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    return len(answers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path)
    args = parser.parse_args()
    batches = manifests()
    for batch in batches:
        require_committed(GAO if batch['batch'] == 'gao' else INITIAL)
    count = import_answers(json.loads(args.export.read_text(encoding='utf8')), HERE / 'gt', batches)
    print(f'Imported {count} human sample answers into {HERE / "gt"}; full-page GT preserved')


if __name__ == '__main__':
    main()
