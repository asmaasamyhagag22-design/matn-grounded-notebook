"""Public HTTP only: validate every hop and pin the actual connected address.

No proxies, cookies, credentials, JavaScript, retries, or tool execution. DNS
answers containing even one non-public address are rejected before connection.
"""
import http.client
import ipaddress
import socket
import ssl
import time
import signal
import threading
from urllib.parse import urlsplit, urlunsplit, urljoin


_CONCURRENT = threading.local()


def concurrent_worker(fn):
    """Mark a bounded pool worker (v2 path) as allowed to fetch; every other check is unchanged."""
    def run(*args, **kwargs):
        _CONCURRENT.allowed = True
        try:
            return fn(*args, **kwargs)
        finally:
            _CONCURRENT.allowed = False
    return run


def canonical_url(url):
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise ValueError('PUBLIC_HTTP_URL_REQUIRED')
    host = p.hostname.encode('idna').decode().lower().rstrip('.')
    port = p.port or (443 if p.scheme == 'https' else 80)
    if port != (443 if p.scheme == 'https' else 80):
        raise ValueError('STANDARD_PORT_REQUIRED')
    if any(ord(c) < 33 for c in url) or '\\' in url:
        raise ValueError('INVALID_URL')
    authority = '[' + host + ']' if ':' in host else host
    return urlunsplit((p.scheme, authority, p.path or '/', p.query, ''))


def _resolve_in_thread(host, port, seconds=5.):
    """Worker-thread DNS with the same 5 s bound as the SIGALRM path (signals only reach the main thread)."""
    box = {}
    def resolve():
        try:
            box['answers'] = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except BaseException as exc:
            box['error'] = exc
    worker = threading.Thread(target=resolve, daemon=True); worker.start(); worker.join(seconds)
    if worker.is_alive():
        raise TimeoutError('DNS_TIMEOUT')
    if 'error' in box:
        raise box['error']
    return box['answers']


def public_addresses(host, port):
    if threading.current_thread() is not threading.main_thread():
        if not getattr(_CONCURRENT, 'allowed', False):
            raise ValueError('SEQUENTIAL_READER_MAIN_THREAD_REQUIRED')
        answers = _resolve_in_thread(host, port)
        addresses = list(dict.fromkeys(a[4][0] for a in answers))
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise ValueError('PRIVATE_NETWORK_TARGET')
        return addresses
    def expired(*_):
        raise TimeoutError('DNS_TIMEOUT')
    previous = signal.getsignal(signal.SIGALRM)
    timer = signal.getitimer(signal.ITIMER_REAL); start = time.monotonic()
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, min(5., timer[0]) if timer[0] else 5.)
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    finally:
        signal.signal(signal.SIGALRM, previous)
        signal.setitimer(signal.ITIMER_REAL, max(.000001, timer[0] - (time.monotonic() - start)) if timer[0] else 0, timer[1])
    addresses = list(dict.fromkeys(a[4][0] for a in answers))
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ValueError('PRIVATE_NETWORK_TARGET')
    return addresses


def request(url, *, method='GET', body=None, headers=None, timeout=25,
            max_bytes=4 * 1024 * 1024, redirects=3):
    """A single bounded transaction. POST never follows redirects."""
    start = time.monotonic(); history = []
    for hop in range(redirects + 1):
        url = canonical_url(url); p = urlsplit(url)
        port = 443 if p.scheme == 'https' else 80
        addresses = public_addresses(p.hostname, port)
        remaining = timeout - (time.monotonic() - start)
        if remaining <= 0:
            raise TimeoutError('FETCH_TIMEOUT')
        conn = http.client.HTTPConnection(p.hostname, port, timeout=remaining)
        # Connect once to the validated address; never resolve the host again.
        sock = socket.create_connection((addresses[0], port), remaining)
        try:
            if p.scheme == 'https':
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=p.hostname)
            conn.sock = sock
            conn.request(method, urlunsplit(('', '', p.path or '/', p.query, '')),
                         body=body, headers={'User-Agent': 'Matn-TopicResearch/1',
                                             'Accept-Encoding': 'identity', **(headers or {})})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                if method != 'GET' or hop == redirects or not response.getheader('Location'):
                    raise ValueError('REDIRECT_LIMIT')
                history.append(dict(url=url, status=response.status))
                url = urljoin(url, response.getheader('Location'))
                continue
            if response.status != 200:
                raise ValueError('HTTP_STATUS_' + str(response.status))
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise ValueError('COMPRESSED_RESPONSE_UNSUPPORTED')
            length = response.getheader('Content-Length')
            if length and int(length) > max_bytes:
                raise ValueError('DOWNLOAD_SIZE_LIMIT')
            chunks = []; size = 0
            while True:
                remaining = timeout - (time.monotonic() - start)
                if remaining <= 0:
                    raise TimeoutError('FETCH_TIMEOUT')
                sock.settimeout(remaining)
                chunk = response.read1(min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk); size += len(chunk)
                if size > max_bytes:
                    raise ValueError('DOWNLOAD_SIZE_LIMIT')
            return dict(body=b''.join(chunks), final_url=url, redirects=history,
                        content_type=response.getheader('Content-Type', '').lower(),
                        fetched_at=time.time(), seconds=time.monotonic() - start)
        finally:
            conn.close(); sock.close()
    raise ValueError('REDIRECT_LIMIT')
