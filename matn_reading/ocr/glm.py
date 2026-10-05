"""Reader 2: GLM-OCR through Ollama on 127.0.0.1, one number-bearing line crop per call.

- Only a loopback host is accepted, and the request goes through a no-proxy opener (audit F-03: the default opener
  follows HTTP_PROXY, so a request could leave the machine through a proxy).
- The model's own task prompt ``Text Recognition:``; ``temperature`` 0 and a fixed ``seed`` make reads repeatable.
- Generation stops at the first newline and ``num_predict`` is capped: GLM-OCR otherwise repeats the line until the
  limit (docs/ocr_setup.md section 7).
- Results are cached by the sha256 of the crop bytes plus the model and options, so a re-run (or an ablation that
  produces the same crop) never asks the model twice. Failures are returned, never cached, never raised.
"""
from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class GlmConfig:
    model: str = "glm-ocr:bf16"
    prompt: str = "Text Recognition:"
    num_ctx: int = 16384
    temperature: float = 0.0
    seed: int = 0
    num_predict: int = 128
    stop: tuple[str, ...] = ("\n",)
    host: str = "127.0.0.1"
    port: int = 11434
    timeout_s: float = 300.0
    keep_alive: str = "30m"                 # keep the model loaded between lines
    cache_dir: Path = field(default=REPO / "out" / "ocr_cache" / "glm")

    def options(self) -> dict:
        return {"num_ctx": self.num_ctx, "temperature": self.temperature, "seed": self.seed,
                "num_predict": self.num_predict, "stop": list(self.stop)}


@dataclass(frozen=True)
class GlmRead:
    text: str | None
    cached: bool
    seconds: float
    key: str
    error: str | None = None


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def first_line(response: str) -> str:
    return next((line.strip() for line in response.splitlines() if line.strip()), "")


class GlmReader:
    def __init__(self, config: GlmConfig = GlmConfig()):
        if not _is_loopback(config.host):
            raise ValueError(f"GLM-OCR must run on a loopback host, not {config.host!r}")
        self.config = config
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.calls = 0

    def cache_key(self, png: bytes) -> str:
        identity = json.dumps({"model": self.config.model, "prompt": self.config.prompt,
                               "options": self.config.options()}, sort_keys=True).encode()
        return hashlib.sha256(identity + b"\0" + png).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return Path(self.config.cache_dir) / key[:2] / f"{key}.json"

    def read_line(self, png: bytes) -> GlmRead:
        key = self.cache_key(png)
        cached = self._cache_path(key)
        if cached.is_file():
            record = json.loads(cached.read_text(encoding="utf-8"))
            return GlmRead(record["text"], True, float(record.get("seconds", 0.0)), key)  # seconds of the original call
        body = json.dumps({"model": self.config.model, "prompt": self.config.prompt, "stream": False,
                           "images": [base64.b64encode(png).decode("ascii")], "keep_alive": self.config.keep_alive,
                           "options": self.config.options()}).encode()
        request = urllib.request.Request(f"http://{self.config.host}:{self.config.port}/api/generate", body,
                                         {"Content-Type": "application/json"})
        started = time.perf_counter()
        self.calls += 1
        try:
            with self.opener.open(request, timeout=self.config.timeout_s) as response:
                text = first_line(json.loads(response.read())["response"])
        except Exception as error:  # a failed second read flags the line; it never stops the page
            return GlmRead(None, False, round(time.perf_counter() - started, 3), key, f"{type(error).__name__}: {error}")
        seconds = round(time.perf_counter() - started, 3)
        if not text:
            return GlmRead(None, False, seconds, key, "empty second read")
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps({"text": text, "seconds": seconds}, ensure_ascii=False), encoding="utf-8")
        return GlmRead(text, False, seconds, key)
