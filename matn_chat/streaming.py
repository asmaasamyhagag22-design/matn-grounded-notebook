"""Opt-in local NDJSON transport. Partial response is diagnostic, never verified."""
import http.client
import json
import socket
import threading
import time
from .generation import LocalGenerator, MODEL, GENERATOR_DIGEST
from matn_rag.contracts import canonical


class NDJSON:
    def __init__(self): self.buffer = b''
    def feed(self, data):
        self.buffer += data
        if len(self.buffer) > 8 * 1024 * 1024: raise ValueError('EVENT_TOO_LARGE')
        rows = []
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if line.strip(): rows.append(json.loads(line.decode('utf-8')))
        return rows
    def finish(self):
        if self.buffer.strip(): raise EOFError('TRUNCATED_NDJSON')


class StreamingGenerator(LocalGenerator):
    def generate_stream(self, body, emit, *, total=420, connect=10, read_idle=420, cancel=None):
        started = time.monotonic()
        tags = self.request('/api/tags')
        if not any(m['name'] == MODEL and m['digest'] == GENERATOR_DIGEST for m in tags['models']):
            raise ValueError('GENERATOR_DIGEST_MISMATCH')
        show = self.request('/api/show', {'model': MODEL})
        if 'thinking' not in show.get('capabilities', []): raise ValueError('THINK_FALSE_UNSUPPORTED')
        remaining = total - (time.monotonic() - started)
        if remaining <= 0: raise TimeoutError('preflight_deadline')
        return stream_http(body, emit, total=remaining, connect=min(connect, remaining), read_idle=min(read_idle, remaining), cancel=cancel)


def stream_http(body, emit, *, total, connect, read_idle, cancel=None, port=11434):
    """Fixed loopback endpoint, no proxy/redirect. Timer closes actual socket at cap."""
    start = time.monotonic(); end = start + total
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=min(connect, total))
    phase = 'connect'; sock = None; stop = threading.Event(); reason = []; response = None
    def abort(why):
        reason.append(why)
        if sock is not None:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        conn.close()
    def watch():
        while not stop.wait(.01):
            if time.monotonic() >= end: abort('total_deadline'); return
            if cancel is not None and cancel.is_set(): abort('cancelled'); return
    thread = threading.Thread(target=watch, daemon=True)
    stats = dict(events=0, response_bytes=0, response_characters=0, thinking_bytes=0,
                 first_event_seconds=None, first_content_seconds=None, first_thinking_seconds=None,
                 done=False, done_reason='unknown', final_statistics='unknown')
    text = []; parser = NDJSON()
    def event(kind, **data): emit(dict(kind=kind, elapsed=time.monotonic()-start, **data))
    event('request_start', wall=time.time(), total_seconds=total, connect_seconds=connect, read_idle_seconds=read_idle)
    thread.start()
    try:
        conn.connect(); sock = conn.sock; phase = 'read'
        sock.settimeout(min(read_idle, max(.001, end-time.monotonic())))
        conn.request('POST', '/api/generate', canonical(dict(body, stream=True)), {'Content-Type':'application/json'})
        response = conn.getresponse()
        event('headers', status=response.status)
        if response.status != 200: raise ConnectionError('HTTP_STATUS_'+str(response.status))
        while True:
            if reason: raise TimeoutError(reason[0])
            sock.settimeout(min(read_idle, max(.001, end-time.monotonic())))
            chunk = response.read1(65536)
            if reason: raise TimeoutError(reason[0])
            if not chunk: break
            for row in parser.feed(chunk):
                stats['events'] += 1
                if stats['first_event_seconds'] is None: stats['first_event_seconds'] = time.monotonic()-start
                content = row.get('response', ''); thinking = row.get('thinking', '')
                if content and stats['first_content_seconds'] is None: stats['first_content_seconds'] = time.monotonic()-start
                if thinking and stats['first_thinking_seconds'] is None: stats['first_thinking_seconds'] = time.monotonic()-start
                stats['response_bytes'] += len(content.encode()); stats['response_characters'] += len(content)
                stats['thinking_bytes'] += len(thinking.encode()); text.append(content)
                # Never persist thinking text, context token IDs, or treat chunks as token counts.
                safe = {k:v for k,v in row.items() if k not in ('thinking','context','response')}
                event('event', response=content, thinking_present=bool(thinking), thinking_bytes=len(thinking.encode()), metadata=safe, counts=dict(stats))
                if row.get('error'): raise ConnectionError(row['error'])
                if row.get('done'):
                    stats.update(done=True, done_reason=row.get('done_reason','unknown'),
                        final_statistics={k:row.get(k,'unknown') for k in ('total_duration','load_duration','prompt_eval_count','prompt_eval_duration','eval_count','eval_duration')})
                    event('terminal', **stats)
                    return dict(response=''.join(text), **stats)
        parser.finish()
        raise EOFError('DISCONNECT_BEFORE_DONE')
    except BaseException as exc:
        why = reason[0] if reason else ('total_deadline' if time.monotonic() >= end else
            (('connect_timeout' if phase == 'connect' else 'read_idle') if isinstance(exc, socket.timeout) else type(exc).__name__))
        event('failure', error=repr(exc), stop_reason=why, **stats)
        raise
    finally:
        stop.set()
        if response is not None: response.close()
        conn.close(); thread.join(timeout=1)
        event('transport_closed', **stats)
