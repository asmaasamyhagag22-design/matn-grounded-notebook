"""The egress guard blocks every non-loopback connection inside its block (used by the offline OCR tests)."""
from __future__ import annotations

import socket

import pytest

from checks.egress_guard import EgressBlocked, block_egress


def test_non_loopback_connections_are_blocked_before_any_packet_leaves():
    with block_egress():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(EgressBlocked):
                sock.connect(("93.184.216.34", 443))
            with pytest.raises(EgressBlocked):
                sock.connect_ex(("8.8.8.8", 53))
        finally:
            sock.close()
        with pytest.raises(EgressBlocked):
            socket.create_connection(("huggingface.co", 443), timeout=1)
        with pytest.raises(EgressBlocked):
            socket.getaddrinfo("paddle-model-ecology.bj.bcebos.com", 443)


def test_loopback_stays_allowed_for_the_local_ollama():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        with block_egress():
            client = socket.create_connection(("127.0.0.1", port), timeout=2)
            client.close()
            assert socket.getaddrinfo("localhost", port)  # name lookup of loopback is allowed
    finally:
        server.close()


def test_the_guard_is_removed_after_the_block():
    original = socket.socket.connect
    with block_egress():
        assert socket.socket.connect is not original
    assert socket.socket.connect is original
