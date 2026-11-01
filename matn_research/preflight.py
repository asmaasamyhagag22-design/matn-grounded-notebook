"""Live preflight: GO / NO-GO with reasons in under 60 s. Read-only except the model preload.

Checks the Tavily key and remaining credits, public network reachability, memory
headroom, the pinned generator digest, the verifier and embedding pins, and that no
foreign model or L4 worker is resident. With --preload it then loads the pinned model
with the live preset's context so the first planning call needs no load.

  .venv/bin/python -B -m matn_research.preflight --preload --progress out/live/progress.html
"""
import argparse
import json
from pathlib import Path
import time
import urllib.request

BASE = 'http://127.0.0.1:11434'
NEED_BEFORE_PRELOAD = 7 * 1024 ** 3  # pinned qwen3.5:9b resident ≈ 6.1–6.6 GB


def local(path, body=None, timeout=60):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as r:
        return json.load(r)


def check(preload=False, search_budget=12, context=2048):
    from matn_chat.generation import MODEL, GENERATOR_DIGEST
    from matn_chat.memory import sample_memory
    from matn_rag.embedding import MODEL as EMBED, DIGEST as EMBED_DIGEST
    from .providers import load_settings, account_usage, qualify
    started = time.time(); rows = []
    def row(name, ok, detail):
        rows.append(dict(check=name, ok=bool(ok), detail=detail, at=round(time.time() - started, 2)))
    settings = load_settings(); row('tavily_key', settings['key_present'], 'key present' if settings['key_present'] else 'TAVILY_API_KEY missing')
    try:
        usage = account_usage(); verdict = qualify(None, usage=usage, free_credit_budget=search_budget)
        account = usage.get('account', {})
        remaining = account.get('plan_limit', 0) - account.get('plan_usage', 0)
        row('network', True, 'api.tavily.com reachable')
        row('tavily_quota', verdict['status'] == 'READY', 'remaining credits ' + str(remaining) + ' (need ' + str(search_budget) + ')')
    except Exception as exc:
        if str(exc) == 'HTTP_STATUS_429':  # reachable, but the usage endpoint is rate limited
            row('network', True, 'api.tavily.com reachable')
            row('tavily_quota', False, 'usage endpoint rate-limited (HTTP 429); wait 60 s without calls and rerun preflight')
        else:
            row('network', False, type(exc).__name__ + ': ' + str(exc)[:120]); row('tavily_quota', False, 'not checked')
    try:
        tags = local('/api/tags', timeout=5)['models']; ps = local('/api/ps', timeout=5)['models']
        row('generator_digest', any(m['name'] == MODEL and m['digest'] == GENERATOR_DIGEST for m in tags), MODEL + ' pinned digest')
        row('embedding_digest', any(m['name'] == EMBED and m['digest'] == EMBED_DIGEST for m in tags), EMBED + ' pinned digest')
        foreign = [m['name'] for m in ps if m['name'] != MODEL]
        row('no_foreign_model', not foreign, 'resident: ' + (', '.join(m['name'] for m in ps) or 'none'))
    except Exception as exc:
        row('ollama', False, type(exc).__name__ + ': ' + str(exc)[:120]); ps = []
    try:
        from matn_storyboard.units import identity
        ident = identity(); row('verifier_pin', bool(ident), 'verification identity ' + str(ident.get('version', ''))[:60])
    except Exception as exc:
        row('verifier_pin', False, type(exc).__name__ + ': ' + str(exc)[:120])
    memory = sample_memory(); loaded = any(m['name'] == MODEL for m in ps)
    row('no_l4_worker', not memory['workers'], str(len(memory['workers'])) + ' L4 workers')
    need = 0 if loaded else NEED_BEFORE_PRELOAD
    row('memory_headroom', memory['available_bytes'] >= max(need, 1536 * 1024 ** 2),
        str(round(memory['available_bytes'] / 1024 ** 3, 1)) + ' GiB available' + ('' if loaded else ' (need 7.0 before preload)'))
    if preload and all(r['ok'] for r in rows):
        try:
            began = time.time()
            r = local('/api/generate', dict(model=MODEL, prompt='', keep_alive='60m',
                      options=dict(num_ctx=context, num_thread=4, seed=20261026, temperature=0)), timeout=90)
            ps = local('/api/ps', timeout=5)['models']
            ok = [m.get('name') for m in ps] == [MODEL] and any(m.get('context_length', context) == context for m in ps)
            row('model_resident', ok, 'preloaded in ' + str(round(time.time() - began, 1)) + ' s, context ' + str(context))
        except Exception as exc:
            row('model_resident', False, type(exc).__name__ + ': ' + str(exc)[:120])
    go = all(r['ok'] for r in rows)
    return dict(verdict='GO' if go else 'NO-GO', reasons=[r['check'] + ': ' + r['detail'] for r in rows if not r['ok']],
                checks=rows, seconds=round(time.time() - started, 1), at=time.time())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--preload', action='store_true'); ap.add_argument('--out')
    ap.add_argument('--progress', help='Progress page to open after GO')
    ap.add_argument('--search-budget', type=int, default=12)
    a = ap.parse_args(argv)
    value = check(preload=a.preload, search_budget=a.search_budget)
    for r in value['checks']:
        print(('  ok  ' if r['ok'] else '  FAIL ') + r['check'] + ' — ' + r['detail'])
    print(value['verdict'] + ' in ' + str(value['seconds']) + ' s' + ('' if value['verdict'] == 'GO' else ': ' + '; '.join(value['reasons'])))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True); Path(a.out).write_text(json.dumps(value, indent=1))
    if value['verdict'] == 'GO' and a.progress:
        print('Progress view: ' + str(Path(a.progress).resolve()))
    return 0 if value['verdict'] == 'GO' else 2


if __name__ == '__main__':
    raise SystemExit(main())
