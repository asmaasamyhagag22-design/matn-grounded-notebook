"""Summarize a profile_memory.py run: peak memory per stage and the guard's view."""
import argparse
import json
from pathlib import Path

GiB = 1024 ** 3


def stages(app):
    """Stage windows from job events and the generation/native call journal."""
    marks = []
    for events in sorted(app.rglob('events.jsonl')):
        if 'coverage-attempt' in events.parts:
            continue
        for line in events.read_text().splitlines():
            row = json.loads(line)
            marks.append((row['at'], row['stage'] + (f" {row.get('sentence')}/{row.get('sentences_total')}" if row.get('sentences_total') else '')))
    for calls in sorted(app.rglob('qa-ledger/calls.json')):
        prefix = 'coverage ' if 'coverage-attempt' in calls.parts else ''
        for row in json.loads(calls.read_bytes()):
            label = row['kind'] + (' unload' if row['kind'] == 'model_unload' else '')
            marks.append((row['started_at'], prefix + 'call ' + label + ' start'))
            if row.get('seconds') is not None:
                marks.append((row['started_at'] + row['seconds'], prefix + 'call ' + label + ' end'))
    return sorted(marks)


def summarize(folder):
    folder = Path(folder)
    samples = [json.loads(l) for l in (folder / 'samples.jsonl').read_text().splitlines() if l.strip()]
    marks = stages(folder / 'app')
    turns = json.loads((folder / 'turns.json').read_bytes())
    guard = [json.loads(l) for p in sorted((folder / 'app').rglob('memory-guard.jsonl')) for l in p.read_text().splitlines()]
    windows = []
    edges = [(samples[0]['at'], 'start (idle, before the question)')] + marks + [(samples[-1]['at'] + 1, 'end')]
    for (start, label), (stop, _) in zip(edges, edges[1:]):
        rows = [s for s in samples if start <= s['at'] < stop]
        if not rows:
            continue
        low = min(rows, key=lambda s: s['memory']['available'])
        models = next((s['ollama_ps'] for s in reversed(rows) if 'ollama_ps' in s), None)
        windows.append(dict(stage=label, seconds=round(stop - start, 1), min_available_gib=round(low['memory']['available'] / GiB, 2),
                            used_gib=round((low['memory']['total'] - low['memory']['available']) / GiB, 2),
                            swap_used_mib=max(s['memory']['swap_used'] for s in rows) >> 20,
                            swap_in_pages=rows[-1]['memory']['pswpin'] - rows[0]['memory']['pswpin'],
                            swap_out_pages=rows[-1]['memory']['pswpout'] - rows[0]['memory']['pswpout'],
                            groups_at_low_gib={k: round(v / GiB, 2) for k, v in sorted(low['groups'].items(), key=lambda x: -x[1])},
                            ollama_models=models))
    return dict(turns=[dict(question=t['question'], seconds=round(t['ended'] - t['started'], 1), answer_kind=t['answer_kind'],
                            failures=t['failures'], sentences=t['sentences'],
                            resource_wait=t['job'].get('queue_seconds')) for t in turns],
                guard=[dict(g, available_gib=round(g['available_bytes'] / GiB, 2), threshold_gib=round(g['threshold_bytes'] / GiB, 2),
                            runner_gib=round(g['ollama_runner_rss_bytes'] / GiB, 2), l4_gib=round(g['l4_worker_rss_bytes'] / GiB, 2)) for g in guard],
                peak=dict(min_available_gib=round(min(s['memory']['available'] for s in samples) / GiB, 2),
                          max_swap_used_mib=max(s['memory']['swap_used'] for s in samples) >> 20,
                          swap_in_pages=samples[-1]['memory']['pswpin'] - samples[0]['memory']['pswpin'],
                          major_faults=samples[-1]['memory']['pgmajfault'] - samples[0]['memory']['pgmajfault']),
                stages=windows)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('folder', type=Path)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    value = summarize(a.folder)
    text = json.dumps(value, indent=1)
    if a.out:
        a.out.write_text(text + '\n')
    print(text)
