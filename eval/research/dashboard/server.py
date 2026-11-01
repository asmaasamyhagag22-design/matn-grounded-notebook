"""Loopback console. Preflight is read-only; only explicit /api/run launches live.sh."""
from __future__ import annotations

import fcntl
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import math
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
from urllib.parse import unquote, urlsplit

from .data import DELIVERY_ROOT, V2_ROOT, collect, digest, read, summarize
from .render import render


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.' + secrets.token_hex(6) + '.pending')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def ledger_status(folder, now=None):
    """Validate the frozen continuation hash/parent and deadline without touching it."""
    now = time.time() if now is None else now
    folder = Path(folder); ledger = read(folder / 'ledger.json', {})
    auth = read(folder / 'continuation-authorization.json', {})
    ledger = ledger if isinstance(ledger,dict) else {}
    auth = auth if isinstance(auth,dict) else {}
    reasons = []; caps = auth.get('additional', {})
    caps = caps if isinstance(caps,dict) else {}
    calls = ledger.get('calls',{}); calls = calls if isinstance(calls,dict) else {}
    remaining={}
    for k in ('generation','native'):
        if type(caps.get(k)) is not int or caps[k]<0 or type(calls.get(k)) is not int or calls[k]<0:
            reasons.append('Invalid '+k+' cap/call counter'); remaining[k]=0
        else:
            remaining[k]=caps[k]-calls[k]
    if not auth or digest(auth) != ledger.get('continuation_authorization'):
        reasons.append('Continuation authorization missing or changed')
    parent = read(auth.get('parent_final', ''), {})
    parent=parent if isinstance(parent,dict) else {}
    if not parent or digest(parent) != auth.get('parent_sha256'):
        reasons.append('Authorization parent missing or changed')
    historical = parent.get('cumulative')
    if historical is None and parent.get('lineage'):
        historical = dict(generation=parent['lineage'].get('total_generation'),native=parent['lineage'].get('native_total'))
    prior=auth.get('historical',{}); prior=prior if isinstance(prior,dict) else {}
    cumulative=auth.get('cumulative_cap',{}); cumulative=cumulative if isinstance(cumulative,dict) else {}
    if not isinstance(historical,dict) or any(historical.get(k) != prior.get(k) for k in ('generation','native')):
        reasons.append('Authorization history does not match parent')
    if not all(type(caps.get(k)) is int and caps[k] >= 0 and type(prior.get(k)) is int and prior[k]>=0 and
               prior[k] + caps[k] == cumulative.get(k)
               for k in ('generation','native')):
        reasons.append('Cumulative caps inconsistent')
    limits=ledger.get('limits',{}); limits=limits if isinstance(limits,dict) else {}
    def number(value):
        return value if type(value) in (int,float) and math.isfinite(value) else 0
    deadline = min(number(ledger.get('experiment_deadline')),
                   number(ledger.get('started_at')) + number(limits.get('experiments')))
    phase = ledger.get('phase_guard')
    if phase:
        if not isinstance(phase,dict):
            phase={}; reasons.append('Invalid phase guard')
        if phase.get('phase') != 'experiments' or phase.get('status') != 'active' or phase.get('running'):
            reasons.append('Ledger phase unavailable or already running')
        deadline = min(deadline, number(phase.get('deadline')))
    if deadline - now < 1200:
        reasons.append('Less than 1200 seconds remain in the experiment window')
    search_budget = ledger.get('search_budget', {})
    search_budget=search_budget if isinstance(search_budget,dict) else {}
    # Owner search grants in older ledgers were prose-only: do not infer permission.
    search_cap = search_budget.get('cap')
    spent = search_budget.get('spent',0)
    if type(spent) is not int or spent < 0 or (type(search_cap) is int and spent > search_cap):
        reasons.append('Search budget counters invalid'); spent = 0
    journal=read(folder / 'dashboard-reservations.json', {})
    reservations=journal.get('runs',{}) if isinstance(journal,dict) else None
    if not isinstance(reservations,dict) or any(not isinstance(r,dict) or type(r.get('searches')) is not int or r['searches']<0 for r in reservations.values()):
        reasons.append('Search reservation journal invalid'); reservations={}
    allocated = sum(r['searches'] for r in reservations.values())
    remaining['search'] = max(0, search_cap - spent - allocated) if type(search_cap) is int else None
    if remaining['search'] is None:
        reasons.append('No explicit machine-readable owner search cap on this ledger')
    elif remaining['search'] < 12:
        reasons.append('A full 12-search run allowance is unavailable')
    for kind, needed in (('generation',7),('native',60)):
        if remaining[kind] < needed:
            reasons.append(f'Insufficient {kind} reserve: need {needed}')
    return dict(verdict='NO-GO' if reasons else 'GO', remaining=remaining, experiment_deadline=deadline,
                reasons=reasons, provider_quota='UNCHECKED: live.sh checks it before paid calls',
                model_calls=0, search_calls=0)


class Console:
    def __init__(self, root=DELIVERY_ROOT, v2=V2_ROOT, ledgers=(), runner=None, identity_checker=None):
        self.root=Path(root).resolve(); self.v2=Path(v2).resolve()
        self.output=self.root/'out/dashboard'; self.output.mkdir(parents=True,exist_ok=True)
        self.ledgers=tuple(Path(p).resolve() for p in ledgers)
        self.runner=runner or self._real_runner; self.token=secrets.token_urlsafe(32)
        self.identity_checker=identity_checker or self._check_identity
        self.runs={}; self.lock=threading.Lock(); self.build_lock=threading.Lock()

    def build(self):
        with self.build_lock:
            value=collect(self.root)
            write(self.output/'scoreboard.json',value)
            (self.output/'index.html').write_text(render(value,self.output,self.ledgers,self.token),encoding='utf-8')
            return value

    def selection(self, value):
        if value.get('code') not in ('delivery','v2'):
            raise ValueError('Choose delivery or v2')
        if not value.get('ledger'):
            raise ValueError('Choose an explicit ledger')
        ledger=Path(value['ledger']).resolve()
        if ledger not in self.ledgers:
            raise ValueError('Ledger is not in the explicit server allowlist')
        return (self.root if value['code']=='delivery' else self.v2),ledger

    def preflight(self,value):
        tree,ledger=self.selection(value)
        result=ledger_status(ledger)
        py=self.root/'.venv/bin/python'
        missing=[str(p) for p in (py, tree/'live.sh', tree/'scripts/dev_environment.sh') if not p.is_file()]
        if missing:
            result['reasons'].append('Missing runtime files: '+', '.join(missing)); result['verdict']='NO-GO'
        identity=self.identity_checker(tree,value['code'])
        result['code_identity']=identity
        if not identity.get('ok'):
            result['reasons'].append('Code identity: '+identity.get('reason','does not match freeze')); result['verdict']='NO-GO'
        result.update(code=value['code'], ledger=str(ledger),scope='LOCAL preflight; provider/network readiness is checked by live.sh on explicit start')
        return result

    def _check_identity(self,tree,code):
        freeze=self.root/('out/leap-20261030/code-round2-freeze.json' if code=='delivery' else 'out/research-v2/candidate-freeze.json')
        if not freeze.is_file():
            return dict(ok=False,reason='Candidate has not been frozen' if code=='v2' else 'Delivery freeze missing')
        program='''import hashlib,json,socket,sys
from pathlib import Path
def refuse(*a,**k): raise RuntimeError('DASHBOARD_IDENTITY_NETWORK_FORBIDDEN')
socket.socket.connect=refuse; socket.create_connection=refuse
from matn_research.workflow import code_identity
from matn_storyboard.core import digest
f=json.loads(Path(sys.argv[1]).read_bytes()); actual=digest(code_identity())
files_ok=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in f['files'].items())
print(json.dumps(dict(ok=actual==f['code_identity_sha256'] and files_ok,identity=actual,expected=f['code_identity_sha256'],reason='identity or file hash drift' if not files_ok or actual!=f['code_identity_sha256'] else 'matched freeze')))
'''
        try:
            result=subprocess.run([str(self.root/'.venv/bin/python'),'-B','-c',program,str(freeze)],cwd=tree,
                env=dict(os.environ,PYTHONPATH=str(tree),PYTHONDONTWRITEBYTECODE='1'),
                capture_output=True,text=True,timeout=30,check=False)
            return json.loads(result.stdout) if result.returncode==0 else dict(ok=False,reason='Identity checker failed (exit '+str(result.returncode)+')')
        except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
            return dict(ok=False,reason=type(exc).__name__)

    def start(self,value):
        tree,ledger=self.selection(value)
        for key in ('topic','audience'):
            if not isinstance(value.get(key),str) or not 1 <= len(value[key].strip()) <= 500 or '\x00' in value[key]:
                raise ValueError(key+' must contain 1–500 characters')
        with self.lock:
            if any(not r.get('done') for r in self.runs.values()):
                raise ValueError('A console run is already active')
            with (ledger/'dashboard.lock').open('a') as handle:
                fcntl.flock(handle,fcntl.LOCK_EX)
                preflight=self.preflight(value)
                if preflight['verdict']!='GO':
                    raise ValueError('NO-GO: '+'; '.join(preflight['reasons']))
                run_id=time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4)
                folder=self.root/'out/research-v2/runs'/run_id; folder.mkdir(parents=True)
                reservations=read(ledger/'dashboard-reservations.json',{'runs':{}})
                reservations['runs'][run_id]=dict(searches=12,status='reserved',folder=str(folder),at=time.time())
                write(ledger/'dashboard-reservations.json',reservations)
            identity=preflight['code_identity'].get('identity')
            metadata=dict(id=run_id,topic=value['topic'],audience=value['audience'],code=value['code'],code_identity=identity,
                          ledger=str(ledger),done=False,started_at=time.time(),folder=str(folder))
            write(folder/'dashboard-run.json',metadata); write(folder/'preflight-local.json',preflight)
            self.runs[run_id]=metadata
            thread=threading.Thread(target=self._execute,args=(metadata,tree,ledger),daemon=True); thread.start()
            return dict(id=run_id,folder=str(folder))

    def _execute(self,metadata,tree,ledger):
        folder=Path(metadata['folder'])
        try:
            rc=self.runner(tree,folder,ledger,metadata['topic'],metadata['audience'])
            metadata.update(returncode=rc,done=True,ended_at=time.time())
        except Exception as exc:
            metadata.update(error=type(exc).__name__+': '+str(exc)[:300],done=True,ended_at=time.time())
        if not (folder/'index.html').exists():
            reason=metadata.get('error') or 'The research launcher stopped without a result (exit '+str(metadata.get('returncode'))+').'
            metadata.update(failure_page=True,status='FAILED: no research result',failure_reason=reason)
            (folder/'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Matn · run failed</title>'
                '<style>body{font:17px system-ui;max-width:800px;margin:50px auto;padding:20px;line-height:1.6}</style>'
                '<h1>Research stopped</h1><p>'+escape(reason)+'</p><p>No research units are being presented as a successful result.</p>'
                '<p>Topic: '+escape(metadata['topic'])+'</p><p>Audience: '+escape(metadata['audience'])+'</p>'
                '<p><a href="preflight-local.json">Local preflight</a> · <a href="console.log">Run log</a> · '
                '<a href="../../../dashboard/index.html">Dashboard</a></p></html>',encoding='utf-8')
        with (ledger/'dashboard.lock').open('a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX)
            reservations=read(ledger/'dashboard-reservations.json',{'runs':{}})
            row=reservations['runs'][metadata['id']]
            state=read(folder/'state.json',{})
            # Missing state is uncertain: keep the full reservation. A known preflight
            # refusal with no state and a saved NO-GO made no search and releases it.
            full_preflight=read(folder/'preflight.json',{})
            actual=state.get('search_attempts')
            if type(actual) is int and actual >= 0:
                row.update(searches=actual,status='completed')
            elif full_preflight.get('verdict')=='NO-GO':
                row.update(searches=0,status='provider_preflight_refused')
            else:
                row.update(status='uncertain_full_reservation_retained')
            write(ledger/'dashboard-reservations.json',reservations)
        write(folder/'dashboard-run.json',metadata)
        self.build()

    def _real_runner(self,tree,folder,ledger,topic,audience):
        env=dict(os.environ,MATN_PYTHON=str(self.root/'.venv/bin/python'),MATN_LIVE_LEDGER=str(ledger),
                 MATN_LIVE_OUT=str(folder),MATN_OPEN='0',PYTHONDONTWRITEBYTECODE='1')
        command=['systemd-inhibit','--what=sleep:idle:handle-lid-switch','--why=Matn dashboard research run',
                 'bash',str(tree/'live.sh'),topic,audience]
        with (folder/'console.log').open('w') as output:
            return subprocess.run(command,cwd=tree,env=env,stdout=output,stderr=subprocess.STDOUT,check=False).returncode

    def status(self,run_id):
        # Completed runs also survive a server restart.
        metadata=self.runs.get(run_id)
        if metadata is None:
            if not run_id or any(c not in '0123456789abcdef-' for c in run_id):
                raise ValueError('Unknown run')
            metadata=read(self.root/'out/research-v2/runs'/run_id/'dashboard-run.json')
        if not metadata:
            raise ValueError('Unknown run')
        folder=Path(metadata['folder']); row=dict(metadata)
        def url(name):
            return '/'+str((folder/name).relative_to(self.root/'out')) if (folder/name).exists() else None
        row.update(progress_url=url('progress.html'),result_url=url('index.html'),log_url=url('console.log'),
                   provider_preflight=read(folder/'preflight.json'),progress=read(folder/'progress.json'))
        if row.get('done'):
            row['quality']=summarize(run_id,folder,self.root)
        return row


def make_server(console,port=8765,host='127.0.0.1'):
    if host!='127.0.0.1':
        raise ValueError('Dashboard binds to 127.0.0.1 only')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def reply(self,status,value,kind='application/json'):
            raw=json.dumps(value,ensure_ascii=False).encode() if kind=='application/json' else value
            self.send_response(status); self.send_header('Content-Type',kind+'; charset=utf-8')
            self.send_header('Content-Length',str(len(raw))); self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Cache-Control','no-store'); self.send_header('Referrer-Policy','same-origin')
            self.end_headers(); self.wfile.write(raw)

        def valid_host(self):
            return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403,{'error':'Loopback host required'})
            path=urlsplit(self.path).path
            if path=='/':
                self.send_response(302); self.send_header('Location','/dashboard/index.html'); self.end_headers(); return
            if path.startswith('/api/run/'):
                try: return self.reply(200,console.status(unquote(path[len('/api/run/'): ])))
                except ValueError as exc: return self.reply(404,{'error':str(exc)})
            if path=='/api/scoreboard':
                return self.reply(200,console.build())
            if path=='/dashboard/index.html':
                # A concurrent static regeneration has another token. Always render
                # this process's token into the served page without rewriting evidence.
                value=read(console.output/'scoreboard.json',{})
                return self.reply(200,render(value,console.output,console.ledgers,console.token).encode(),'text/html')
            target=(console.root/'out'/unquote(path).lstrip('/')).resolve()
            if not target.is_relative_to(console.root/'out') or not target.is_file():
                return self.reply(404,{'error':'Not found'})
            return self.reply(200,target.read_bytes(),mimetypes.guess_type(target)[0] or 'application/octet-stream')

        def do_POST(self):
            if not self.valid_host() or not secrets.compare_digest(self.headers.get('X-Matn-Token',''),console.token):
                return self.reply(403,{'error':'Local console token required'})
            origin=self.headers.get('Origin')
            if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
                return self.reply(403,{'error':'Same origin required'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0 < size <= 8192:
                    raise ValueError('Invalid request size')
                value=json.loads(self.rfile.read(size))
                if not isinstance(value,dict):
                    raise ValueError('Object required')
                if self.path=='/api/preflight':
                    return self.reply(200,console.preflight(value))
                if self.path=='/api/run':
                    return self.reply(202,console.start(value))
                return self.reply(404,{'error':'Unknown endpoint'})
            except (ValueError,OSError) as exc:
                return self.reply(400,{'error':str(exc)})
    return ThreadingHTTPServer((host,port),Handler)
