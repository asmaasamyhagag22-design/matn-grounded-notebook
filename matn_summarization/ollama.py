from __future__ import annotations

import json
import ipaddress
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .io import Phase03Error


def validate_loopback_base_url(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise Phase03Error("NON_LOOPBACK_ENDPOINT_REJECTED")
    if parsed.path not in {"", "/"} or parsed.hostname is None:
        raise Phase03Error("NON_LOOPBACK_ENDPOINT_REJECTED")
    if parsed.hostname.lower() != "localhost":
        try:
            if not ipaddress.ip_address(parsed.hostname).is_loopback:
                raise Phase03Error("NON_LOOPBACK_ENDPOINT_REJECTED")
        except ValueError:
            raise Phase03Error("NON_LOOPBACK_ENDPOINT_REJECTED") from None
    return base_url.rstrip("/")


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434", timeout_seconds: int = 1800):
        self.base_url = validate_loopback_base_url(base_url)
        self.timeout_seconds = timeout_seconds
        self.contacted_hosts: list[str] = []

    def _record_contact(self) -> None:
        host = urllib.parse.urlparse(self.base_url).hostname
        if host and host not in self.contacted_hosts:
            self.contacted_hosts.append(host)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._record_contact()
        request = urllib.request.Request(self.base_url + path, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, urllib.error.URLError) as exc:
            raise Phase03Error(f"OLLAMA_REQUEST_FAILED:{type(exc).__name__}") from None
        if not isinstance(value, dict) or value.get("error"):
            raise Phase03Error("OLLAMA_RESPONSE_ERROR")
        return value

    def _get(self, path: str) -> dict[str, Any]:
        self._record_contact()
        request = urllib.request.Request(self.base_url + path, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, urllib.error.URLError) as exc:
            raise Phase03Error(f"OLLAMA_REQUEST_FAILED:{type(exc).__name__}") from None
        if not isinstance(value, dict) or value.get("error"):
            raise Phase03Error("OLLAMA_RESPONSE_ERROR")
        return value

    def show(self, model: str) -> dict[str, Any]:
        result = self._post("/api/show", {"model": model, "verbose": False})
        capabilities = result.get("capabilities", [])
        if "thinking" not in capabilities:
            raise Phase03Error("MODEL_THINK_FALSE_NOT_SUPPORTED")
        tags = self._get("/api/tags")
        match = next((item for item in tags.get("models", []) if item.get("name") == model or item.get("model") == model), None)
        if match is None:
            raise Phase03Error("MODEL_NOT_FOUND")
        result["resolved_digest"] = match.get("digest")
        result["ollama_version"] = self._get("/api/version").get("version")
        return result

    def ps(self) -> dict[str, Any]:
        return self._get("/api/ps")

    def generate(self, model: str, prompt: str, schema: dict[str, Any], num_ctx: int, num_predict: int, temperature: float = 0, think: bool = False) -> tuple[str, dict[str, Any]]:
        result = self._post("/api/generate", {"model": model, "prompt": prompt, "format": schema, "stream": False, "think": think, "options": {"num_ctx": num_ctx, "num_predict": num_predict, "temperature": temperature}})
        if result.get("thinking") not in {None, ""}:
            raise Phase03Error("THINKING_NOT_DISABLED")
        if not result.get("done", False):
            raise Phase03Error("OLLAMA_INCOMPLETE_RESPONSE")
        if result.get("done_reason") not in {"stop", None}:
            raise Phase03Error(f"OLLAMA_DONE_REASON:{result.get('done_reason')}")
        response = result.get("response")
        if not isinstance(response, str):
            raise Phase03Error("OLLAMA_MISSING_RESPONSE")
        metric_names = ["total_duration", "load_duration", "prompt_eval_count", "prompt_eval_cached_count", "prompt_eval_duration", "eval_count", "eval_duration", "done_reason"]
        metrics = {name: result.get(name, 0 if name != "done_reason" else None) for name in metric_names}
        metrics["configured_num_ctx"] = num_ctx
        metrics["configured_num_predict"] = num_predict
        return response, metrics
