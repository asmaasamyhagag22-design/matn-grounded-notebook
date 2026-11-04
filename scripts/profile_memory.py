"""Memory profile of real app answer turns: what is resident at every stage.

Runs questions through the real app (zero searches) on reused immutable
reader/index snapshots and samples, twice a second: system available memory,
swap use and swap-in/out, RSS per process group, and Ollama's resident models
(size, context length). Job events and the memory-guard log mark the stages.
No behaviour changes; this only observes.
"""
import argparse
import json
import os
from pathlib import Path
import threading
import time
import urllib.request

from matn_app.server import make_server
from matn_app.service import App
from matn_app.smoke import _Client
from matn_app.store import write


def meminfo():
    rows = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        rows[key] = int(value.split()[0]) * 1024
    vm = {}
    for line in Path('/proc/vmstat').read_text().splitlines():
        key, value = line.split()
        if key in ('pswpin', 'pswpout', 'pgmajfault'):
            vm[key] = int(value)
    return dict(available=rows['MemAvailable'], total=rows['MemTotal'], swap_used=rows['SwapTotal'] - rows['SwapFree'],
                swap_total=rows['SwapTotal'], **vm)


def group(argv, own):
    text = ' '.join(argv)
    name = Path(argv[0]).name if argv else ''
    if int(own) == os.getpid():
        return 'app_server'
    if name == 'ollama' and argv[1:2] == ['runner'] or name == 'llama-server':
        return 'ollama_runner'
    if name == 'ollama':
        return 'ollama_server'
    if 'matn_verification.l4_worker' in text:
        return 'verifier_l4'
    if 'tokenizer_worker' in text:
        return 'tokenizer'
    if 'rerank_worker' in text:
        return 'reranker'
    if 'matn_app.' in text or 'matn_chat' in text:
        return 'app_worker'
    if 'chatgpt' in text.casefold() or 'codex' in text.casefold():
        return 'desktop_codex'
    if 'claude' in text.casefold():
        return 'desktop_claude'
    return 'other'


def processes():
    groups = {}
    for p in Path('/proc').glob('[0-9]*'):
        try:
            argv = (p / 'cmdline').read_bytes().decode(errors='replace').strip('\0').split('\0')
            rss = next(int(l.split()[1]) * 1024 for l in (p / 'status').read_text().splitlines() if l.startswith('VmRSS:'))
        except (OSError, StopIteration, ValueError):
            continue
        key = group(argv, p.name)
        entry = groups.setdefault(key, dict(rss=0, pids=[]))
        entry['rss'] += rss
        if key not in ('other', 'desktop_codex', 'desktop_claude'):
            entry['pids'].append(dict(pid=int(p.name), rss=rss, argv=' '.join(argv)[:160]))
    return groups


def ollama_ps():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:11434/api/ps', timeout=2) as stream:
            models = json.load(stream).get('models', [])
        return [dict(name=m['name'], size=m.get('size'), size_vram=m.get('size_vram'), context_length=m.get('context_length'),
                     quantization=m.get('details', {}).get('quantization_level'), parameters=m.get('details', {}).get('parameter_size'))
                for m in models]
    except OSError as exc:
        return dict(error=repr(exc))


class Sampler(threading.Thread):
    def __init__(self, path, interval=.5):
        super().__init__(daemon=True)
        self.path = path
        self.interval = interval
        self.stop = threading.Event()

    def run(self):
        tick = 0
        with self.path.open('a') as stream:
            while not self.stop.is_set():
                row = dict(at=time.time(), memory=meminfo(), groups={k: v['rss'] for k, v in processes().items()})
                if tick % 4 == 0:
                    row['ollama_ps'] = ollama_ps()
                    row['process_detail'] = {k: v['pids'] for k, v in processes().items() if v['pids']}
                stream.write(json.dumps(row) + '\n')
                stream.flush()
                tick += 1
                self.stop.wait(self.interval)


def run(state_path, questions, out):
    if out.exists():
        raise ValueError('Use a fresh profile output')
    out.mkdir(parents=True)
    source = json.loads(state_path.read_bytes())
    sampler = Sampler(out / 'samples.jsonl')
    sampler.start()
    app = App(out / 'app', search_budget=0)
    server = make_server(app, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    rows = []
    try:
        client = _Client(server)
        conversation = client.create('Memory profile — development question')
        app.store.update(conversation, lambda v: v.update(catalogs=source['catalogs'], documents=source['documents'],
                                                         notebooks=source['notebooks']))
        for question in questions:
            started = time.time()
            try:
                state = client.complete(conversation, dict(text=question), timeout=1800)
                error = None
            except Exception as exc:
                state = client.state(conversation)
                error = repr(exc)[:500]
            job = state['jobs'][-1]
            result = state['messages'][-1].get('result', {})
            rows.append(dict(question=question, started=started, ended=time.time(), job=job, error=error,
                             answer_kind=result.get('answer_kind'), failures=result.get('failures'),
                             sentences=[c.get('text') for c in result.get('citations', [])]))
            write(out / 'turns.json', rows)
            print(json.dumps(dict(question=question[:60], kind=result.get('answer_kind'), seconds=round(time.time() - started, 1),
                                  error=error)), flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
        app.close()
        time.sleep(2)
        sampler.stop.set()
        sampler.join(5)
    write(out / 'meta.json', dict(state=str(state_path), conversation=conversation, questions=questions, searches=0, fake=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--question', action='append', required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    run(a.state, a.question, a.out)
