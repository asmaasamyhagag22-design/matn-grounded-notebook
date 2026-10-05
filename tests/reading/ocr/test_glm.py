"""Reader 2 client (GLM-OCR via Ollama): loopback only, one line per call, stop at newline, cache by crop hash."""
from __future__ import annotations

import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from matn_reading.ocr.glm import GlmConfig, GlmReader


class _Fake:
    def __init__(self, reply: str = "Total 1,240\nTotal 1,240\nTotal 1,240", status: int = 200):
        self.reply, self.status, self.requests = reply, status, []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append((self.path, body))
                payload = json.dumps({"response": fake.reply}).encode()
                self.send_response(fake.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake():
    server = _Fake()
    yield server
    server.close()


def _reader(tmp_path, port: int) -> GlmReader:
    return GlmReader(GlmConfig(port=port, cache_dir=tmp_path / "cache"))


def test_request_reads_one_line_and_stops_at_the_first_newline(tmp_path, fake):
    result = _reader(tmp_path, fake.port).read_line(b"PNG-bytes-of-a-crop")
    assert result.text == "Total 1,240" and result.error is None and not result.cached
    path, body = fake.requests[0]
    assert path == "/api/generate"
    assert body["model"] == "glm-ocr:bf16" and body["prompt"] == "Text Recognition:" and body["stream"] is False
    assert base64.b64decode(body["images"][0]) == b"PNG-bytes-of-a-crop"
    options = body["options"]
    assert options["stop"] == ["\n"] and 0 < options["num_predict"] <= 256
    assert options["temperature"] == 0 and options["seed"] == 0 and options["num_ctx"] == 16384


def test_second_read_of_the_same_crop_comes_from_the_cache(tmp_path, fake):
    reader = _reader(tmp_path, fake.port)
    first = reader.read_line(b"same crop")
    second = _reader(tmp_path, fake.port).read_line(b"same crop")   # a new process would see the same cache
    assert second.cached and second.text == first.text and len(fake.requests) == 1
    reader.read_line(b"another crop")
    assert len(fake.requests) == 2


def test_a_failed_call_returns_an_error_and_is_not_cached(tmp_path):
    server = _Fake(status=500)
    try:
        reader = _reader(tmp_path, server.port)
        result = reader.read_line(b"crop")
        assert result.text is None and result.error
        reader.read_line(b"crop")
        assert len(server.requests) == 2
    finally:
        server.close()


def test_only_a_loopback_host_is_accepted(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        GlmReader(GlmConfig(host="ollama.example.com", cache_dir=tmp_path))


def test_leading_blank_output_and_spaces_are_trimmed(tmp_path):
    server = _Fake(reply="\n  12.5%  ")
    try:
        assert _reader(tmp_path, server.port).read_line(b"x").text == "12.5%"
    finally:
        server.close()
