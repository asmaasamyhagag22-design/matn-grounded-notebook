"""In-process egress guard: inside ``block_egress()`` only loopback connections are allowed.

Used by the offline OCR tests (Step 4c): PaddleOCR/PaddleX try to reach model hosts when a model is missing or the
source check is on; under this guard such an attempt raises ``EgressBlocked`` instead of leaving the machine, so a
test that passes under the guard proves the run is offline. The Ollama server on 127.0.0.1 stays reachable.

Scope: Python sockets in this process only. A child process (e.g. a native downloader) is not covered; that needs
the OS firewall, which is a pre-delivery item (docs/PRE_DELIVERY_CHECKLIST.md).
"""
from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager

LOOPBACK_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


class EgressBlocked(ConnectionRefusedError):
    """A non-loopback connection or name lookup was attempted under ``block_egress()``."""


def _is_loopback(host: object) -> bool:
    if not isinstance(host, str):
        return False
    if host.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


@contextmanager
def block_egress() -> Iterator[None]:
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo

    def check(address: object) -> None:
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, bytes):
            host = host.decode(errors="replace")
        if not _is_loopback(host) and not (isinstance(address, (str, bytes))):  # AF_UNIX paths are local
            raise EgressBlocked(f"EGRESS_BLOCKED:{host}")

    def connect(self: socket.socket, address: object) -> None:
        check(address)
        return original_connect(self, address)

    def connect_ex(self: socket.socket, address: object) -> int:
        check(address)
        return original_connect_ex(self, address)

    def getaddrinfo(host: object, *args: object, **kwargs: object):
        if host is not None and not _is_loopback(host.decode() if isinstance(host, bytes) else host):
            raise EgressBlocked(f"EGRESS_BLOCKED_DNS:{host}")
        return original_getaddrinfo(host, *args, **kwargs)  # type: ignore[arg-type]

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = original_connect_ex  # type: ignore[method-assign]
        socket.getaddrinfo = original_getaddrinfo  # type: ignore[assignment]
