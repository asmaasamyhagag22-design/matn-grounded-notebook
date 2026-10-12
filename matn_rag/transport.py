"""Embedding-only HTTP transport; literal IPv4 loopback and no proxies/redirects."""
import json
import urllib.request
from urllib.parse import urlsplit
from checks.egress_guard import block_egress


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('REDIRECT_REFUSED')


class LoopbackTransport:
    def __init__(self, base_url='http://127.0.0.1:11434', timeout=120):
        u = urlsplit(base_url)
        if (u.scheme != 'http' or u.hostname != '127.0.0.1' or u.username is not None or u.password is not None
                or u.path not in ('', '/') or u.query or u.fragment or not u.port):
            raise ValueError('LOOPBACK_URL_REFUSED')
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path, payload=None):
        if path not in ('/api/tags', '/api/show', '/api/embed'):
            raise ValueError('ENDPOINT_REFUSED')
        body = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(self.base_url + path, data=body, headers={'Content-Type': 'application/json'})
        with block_egress(), self.opener.open(req, timeout=self.timeout) as response:
            return json.load(response)
