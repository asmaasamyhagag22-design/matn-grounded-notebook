"""Public offline suite: explicit test embeddings and no real service/network calls."""
import hashlib
import math
import re
import socket
import pytest


@pytest.fixture(autouse=True)
def offline_test_boundary(monkeypatch, tmp_path, request):
    original = socket.socket.connect
    def connect(sock, address):
        if isinstance(address, tuple):
            host, port = address[:2]
            if port == 11434 or host not in ('127.0.0.1', '::1', 'localhost'):
                pytest.fail('Offline test attempted a real model or external network connection')
        return original(sock, address)
    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setenv('MATN_RESEARCH_EMBED_CACHE', str(tmp_path / 'fixture-embeddings'))
    if request.path.name in ('test_fast_path.py', 'test_quality_v3.py'):
        from matn_rag import embedding
        class FixtureEmbedder:
            def embed(self, texts, **kwargs):
                result = []
                for text in texts:
                    vector = [0.] * 1024
                    for word in re.findall(r'\w+', text.lower()):
                        index = int.from_bytes(hashlib.sha256(word.encode()).digest()[:2], 'big') % 1024
                        vector[index] += 1
                    norm = math.sqrt(sum(x*x for x in vector)) or 1
                    result.append([x/norm for x in vector])
                return result
        monkeypatch.setattr(embedding, 'Embedder', FixtureEmbedder)
