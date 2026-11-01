"""Persistent P1 deadlines and an external process-group watchdog (no inference)."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from matn_chat.readiness import write, lock
from matn_chat.memory import sample_memory

PHASES = ('experiments', 'validation', 'closure')
DEADLINES = dict(experiments='experiment_deadline', validation='validation_deadline', closure='deadline')


def phase_checkpoint(folder, phase, *, initialize=False):
    """Durable admission: idle time counts and resume never grants a new window.

    Legacy inference journals are not migrated implicitly. The supervisor opts
    a journal into this guard on its first experiment command; calls inside it
    then share exactly the same deadline. Historical ledgers are never reopened.
    """
    path=Path(folder)/'ledger.json';ledger=json.loads(path.read_bytes());now=time.time()
    state=ledger.get('phase_guard')
    if state is None:
        if not initialize:raise ValueError('PHASE_GUARD_REQUIRED')
        if phase!='experiments':raise ValueError('INITIAL_PHASE_MUST_BE_EXPERIMENTS')
        start=ledger['started_at']
        state=dict(phase=phase,started_at=start,
                   deadline=min(ledger[DEADLINES[phase]],start+ledger['limits'][phase]),
                   status='active',running=None,events=[dict(phase=phase,at=start)])
        ledger['phase_guard']=state;write(path,ledger)
    if state['status']!='active' or now>=min(state['deadline'],ledger[DEADLINES[state['phase']]]):
        state.update(status='expired',stopped_at=state.get('stopped_at',now));write(path,ledger)
        raise TimeoutError('PHASE_CUTOFF')
    if state['phase']!=phase:raise ValueError('PHASE_TRANSITION_REQUIRED')
    return min(state['deadline'],ledger[DEADLINES[phase]])


def transition(folder, phase):
    """Advance before expiry, sequentially, without borrowing or renewal."""
    with lock(Path(folder)/'phase.lock'):
        return _transition(folder,phase)


def _transition(folder, phase):
    path=Path(folder)/'ledger.json';ledger=json.loads(path.read_bytes())
    current=ledger.get('phase_guard',{}).get('phase','experiments')
    phase_checkpoint(folder,current,initialize=True)
    ledger=json.loads(path.read_bytes());state=ledger['phase_guard']
    if state['running'] is not None:raise ValueError('PHASE_COMMAND_RUNNING')
    if PHASES.index(phase)!=PHASES.index(current)+1:raise ValueError('PHASE_ORDER')
    now=time.time();deadline=min(ledger[DEADLINES[phase]],now+ledger['limits'][phase])
    if now>=deadline:raise TimeoutError('PHASE_CUTOFF')
    state.update(phase=phase,started_at=now,deadline=deadline)
    state['events'].append(dict(phase=phase,at=now));write(path,ledger)
    return dict(state)


def open_ledger(folder, *, experiment=2400, validation=900, closure=300):
    path = Path(folder)/'ledger.json'
    if path.exists(): raise ValueError('LEDGER_ALREADY_EXISTS_USE_SAVED_DEADLINES')
    start = time.time()
    value = dict(started_at=start, experiment_deadline=start+experiment,
        validation_deadline=start+experiment+validation, deadline=start+experiment+validation+closure,
        limits=dict(experiments=experiment, validation=validation, closure=closure),
        calls=dict(generation=0, native=0, query_embedding=0, warmup=0, retry=0, ocr=0, corpus_embedding=0),
        commands=[], baseline_memory=sample_memory())
    write(path, value); return value


def terminate_group(process, grace=3):
    try: os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError: pass
    stop = time.monotonic()+grace
    while time.monotonic()<stop:
        try: os.killpg(process.pid, 0)
        except ProcessLookupError: break
        process.poll(); time.sleep(.05)
    try: os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError: pass
    process.wait(timeout=5)


def supervise(folder, phase, command, *, timeout=None):
    with lock(Path(folder)/'phase.lock'):
        return _supervise(folder,phase,command,timeout=timeout)


def _supervise(folder, phase, command, *, timeout=None):
    folder = Path(folder); path = folder/'ledger.json'; ledger = json.loads(path.read_bytes())
    phase_deadline=phase_checkpoint(folder,phase,initialize=True)
    ledger=json.loads(path.read_bytes())
    if ledger['phase_guard']['running'] is not None:raise ValueError('PHASE_COMMAND_RUNNING')
    deadline = phase_deadline
    if timeout is not None: deadline = min(deadline, time.time()+timeout)
    if deadline<=time.time(): raise TimeoutError('PHASE_CUTOFF')
    # Wall-clock rollback must not extend a running command's allowance.
    monotonic_deadline=time.monotonic()+deadline-time.time()
    # This supervisor is outside the child session. It outlives a hung native/LLM
    # operation and kills the entire child group, including model sidecars.
    start = time.time()
    # Persist before launch so the child cannot reserve a call that an old
    # supervisor snapshot subsequently overwrites.
    ledger['phase_guard']['running']=dict(command=command,started_at=start);write(path,ledger)
    if time.time()>=deadline or time.monotonic()>=monotonic_deadline:
        ledger['phase_guard'].update(running=None,status='expired',stopped_at=time.time());write(path,ledger)
        raise TimeoutError('PHASE_CUTOFF')
    try:process = subprocess.Popen(command, start_new_session=True)
    except BaseException:
        ledger['phase_guard']['running']=None;write(path,ledger);raise
    reason = None; samples = []; low = 0
    try:
        while process.poll() is None:
            if time.time()>=deadline or time.monotonic()>=monotonic_deadline:
                reason='deadline' if deadline==phase_deadline else 'command_timeout'
                terminate_group(process,grace=0);break
            memory = sample_memory(); rss = 0
            for p in Path('/proc').glob('[0-9]*'):
                try:
                    if os.getpgid(int(p.name)) == process.pid:
                        rss += int(next(l.split()[1] for l in (p/'status').read_text().splitlines() if l.startswith('VmRSS:')))*1024
                except (OSError, StopIteration, ValueError): pass
            samples.append(dict(**memory, child_group_rss_bytes=rss))
            low = low+1 if memory['available_bytes']<512*1024**2 else 0
            if low>=2:
                reason='memory_pressure';terminate_group(process);break
            time.sleep(min(.5, max(.001, deadline-time.time())))
    except BaseException:
        terminate_group(process);raise
    if reason is None and (time.time()>=deadline or time.monotonic()>=monotonic_deadline):
        reason='deadline' if deadline==phase_deadline else 'command_timeout'
    # A command must not escape its window by exiting while leaving a model or
    # another background child alive in its session.
    try:os.killpg(process.pid,0);remaining_group=True
    except ProcessLookupError:remaining_group=False
    if remaining_group:
        terminate_group(process,grace=0)
        if reason is None:reason='undrained_descendants'
    ledger = json.loads(path.read_bytes())  # preserve child call reservations
    row = dict(command=command, phase=phase, started_at=start, ended_at=time.time(),
               seconds=time.time()-start, returncode=process.returncode, stop_reason=reason,
               phase_deadline=phase_deadline,command_deadline=deadline)
    ledger['phase_guard']['running']=None
    if time.time()>=phase_deadline or (reason=='deadline'):
        ledger['phase_guard'].update(status='expired',stopped_at=time.time())
    ledger['commands'].append(row); write(path, ledger)
    write(folder/('memory-'+str(len(ledger['commands']))+'.json'), dict(samples=samples,
        peak_group_rss_bytes=max((s['child_group_rss_bytes'] for s in samples), default=0),
        min_available_bytes=min((s['available_bytes'] for s in samples), default=None)))
    return row


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--folder', required=True)
    p.add_argument('--open', action='store_true'); p.add_argument('--phase', choices=['experiments','validation','closure'])
    p.add_argument('--transition', choices=PHASES)
    p.add_argument('--timeout', type=float); p.add_argument('command', nargs=argparse.REMAINDER)
    a = p.parse_args()
    if a.open: print(json.dumps(open_ledger(a.folder)))
    elif a.transition:print(json.dumps(transition(a.folder,a.transition)))
    else:
        cmd = a.command[1:] if a.command[:1]==['--'] else a.command
        row = supervise(a.folder, a.phase, cmd, timeout=a.timeout); print(json.dumps(row))
        raise SystemExit(0 if row['returncode']==0 and row['stop_reason'] is None else 1)
