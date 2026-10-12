"""Safety contracts: explicit loopback, digest and no silent embedding truncation."""
import importlib
import json
import math
import os
import pytest


def api(module, name):
    try:
        result = getattr(importlib.import_module(module), name, None)
    except ModuleNotFoundError:
        result = None
    assert callable(result), f'Missing required behavior: {module}.{name}'
    return result


@pytest.mark.parametrize('url', ['http://localhost:11434', 'http://example.com', 'https://127.0.0.1:11434', 'http://127.0.0.1:11434/other', 'http://user@127.0.0.1:11434'])
def test_transport_refuses_noncanonical_hosts(url):
    Transport = api('matn_rag.transport', 'LoopbackTransport')
    with pytest.raises(ValueError):
        Transport(url)


def test_transport_has_no_proxy_even_with_proxy_environment(monkeypatch):
    Transport = api('matn_rag.transport', 'LoopbackTransport')
    monkeypatch.setenv('HTTP_PROXY', 'http://example.com:8080')
    monkeypatch.setenv('ALL_PROXY', 'http://example.com:8080')
    t = Transport()
    import urllib.request
    assert not any(isinstance(h, urllib.request.ProxyHandler) and h.proxies for h in t.opener.handlers)


class Fake:
    def __init__(self, digest=None, vectors=None):
        self.digest = digest
        self.vectors = vectors
        self.calls = []

    def request(self, path, payload=None):
        from matn_rag.embedding import DIGEST
        self.calls.append((path, payload))
        if path == '/api/tags':
            return {'models': [{'name': 'qwen3-embedding:0.6b', 'digest': self.digest or DIGEST}]}
        return {'embeddings': self.vectors or [[3., 4.] + [0.] * 1022 for _ in payload['input']]}


def test_digest_refused_before_embedding():
    Embedder = api('matn_rag.embedding', 'Embedder')
    fake = Fake(digest='different')
    with pytest.raises(ValueError, match='DIGEST'):
        Embedder(fake).embed(['text'])
    assert all(path != '/api/embed' for path, _ in fake.calls)


def test_embedding_payload_and_float32_normalization():
    Embedder = api('matn_rag.embedding', 'Embedder')
    fake = Fake()
    values = Embedder(fake).embed(['text'])
    path, payload = fake.calls[-1]
    assert path == '/api/embed' and payload['truncate'] is False
    assert payload['options']['num_ctx'] == 32768
    assert len(values[0]) == 1024 and math.isclose(math.fsum(v*v for v in values[0]), 1., abs_tol=1e-6)
    assert values[0][0] != .6  # float32 storage rounding, not the original float64


@pytest.mark.parametrize('vector', [[0.] * 1024, [1.] * 2, [float('nan')] * 1024])
def test_invalid_vectors_refused(vector):
    Embedder = api('matn_rag.embedding', 'Embedder')
    with pytest.raises(ValueError, match='VECTOR'):
        Embedder(Fake(vectors=[vector])).embed(['text'])


def test_empty_userinfo_is_refused():
    Transport=api('matn_rag.transport','LoopbackTransport')
    with pytest.raises(ValueError):Transport('http://@127.0.0.1:11434')


def test_live_loopback_fixture_ignores_proxy_and_refuses_redirect(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler,HTTPServer
    from matn_rag.transport import LoopbackTransport
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path=='/api/tags':
                self.send_response(200);self.end_headers();self.wfile.write(b'{"models":[]}')
            else:
                self.send_response(302);self.send_header('Location','http://external.invalid/');self.end_headers()
        def log_message(self,*args):pass
    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'):
        monkeypatch.setenv(key,'http://external.invalid:8080')
    for key in ('NO_PROXY','no_proxy'):monkeypatch.setenv(key,'')
    server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        transport=LoopbackTransport(f'http://127.0.0.1:{server.server_port}')
        assert transport.request('/api/tags')=={'models':[]}
        with pytest.raises(ValueError,match='REDIRECT'):transport.request('/api/show')
    finally:server.shutdown();server.server_close();thread.join()
