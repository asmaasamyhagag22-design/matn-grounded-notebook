"""Loopback HTTP, authenticated mutations and persisted SSE step summaries."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import secrets
import time
from urllib.parse import unquote, urlsplit

from .runtime import ROOT

STATIC = Path(__file__).with_name("static")


def make_server(app, port=8787, host="127.0.0.1"):
    if host != "127.0.0.1":
        raise ValueError("Matn binds to 127.0.0.1 only")
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def allowed(self):
            return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

        def reply(self, status, value, kind="application/json"):
            raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() if kind == "application/json" else value
            self.send_response(status)
            self.send_header("Content-Type", kind + ("; charset=utf-8" if kind.startswith("text/") or kind == "application/json" else ""))
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def events(self, conversation):
            app.store.get(conversation)
            try:
                cursor = int(self.headers.get("Last-Event-ID", "0"))
            except ValueError:
                cursor = 0
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            end = time.monotonic() + 45
            try:
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while time.monotonic() < end:
                    for row in app.store.get(conversation)["events"]:
                        if row["id"] > cursor:
                            self.wfile.write(("id: " + str(row["id"]) + "\ndata: " + json.dumps(row, ensure_ascii=False) + "\n\n").encode())
                            cursor = row["id"]
                    self.wfile.flush()
                    time.sleep(.3)
            except (BrokenPipeError, ConnectionResetError):
                pass
            self.close_connection = True

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, {"error": "Loopback host required"})
            parts = [unquote(x) for x in urlsplit(self.path).path.split("/") if x]
            try:
                if parts == ["api", "bootstrap"]:
                    return self.reply(200, dict(app.bootstrap(), token=token))
                if parts == ["api", "evaluation"]:
                    return self.reply(200, app.evaluation())
                if len(parts) >= 3 and parts[:2] == ["api", "conversations"]:
                    conversation = parts[2]
                    if len(parts) == 4 and parts[3] == "events":
                        return self.events(conversation)
                    if len(parts) == 3:
                        return self.reply(200, dict(app.store.get(conversation), evidence=app.evidence(conversation)))
                if len(parts) >= 4 and parts[0] == "artifacts":
                    state = app.store.get(parts[1])
                    version = int(parts[2])
                    if not 1 <= version <= len(state["decks"]):
                        raise ValueError("Unknown deck version")
                    folder = Path(state["decks"][version - 1]["pptx"]).resolve().parent
                    target = folder.joinpath(*parts[3:]).resolve()
                    if not target.is_relative_to(folder) or not target.is_relative_to(app.store.root) or not target.is_file():
                        raise ValueError("Artifact not found")
                    return self.reply(200, target.read_bytes(), mimetypes.guess_type(target)[0] or "application/octet-stream")
                if parts == ["assets", "font-sans.ttf"]:
                    target = Path("/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf")
                elif parts == ["assets", "font-serif.ttf"]:
                    target = Path("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf")
                else:
                    target = (STATIC / ("index.html" if not parts else "/".join(parts))).resolve()
                    if not target.is_relative_to(STATIC.resolve()):
                        raise ValueError("Not found")
                if not target.is_file():
                    return self.reply(404, {"error": "Not found"})
                return self.reply(200, target.read_bytes(), mimetypes.guess_type(target)[0] or "application/octet-stream")
            except (ValueError, FileNotFoundError, IndexError) as exc:
                return self.reply(404, {"error": str(exc)})

        def do_POST(self):
            origin = self.headers.get("Origin")
            origins = (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}")
            if not self.allowed() or (origin and origin not in origins) or not secrets.compare_digest(self.headers.get("X-Matn-Token", ""), token):
                return self.reply(403, {"error": "Local app token and same origin required"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 72 * 1024 * 1024:
                    raise ValueError("Request exceeds the 72 MiB upload limit")
                value = json.loads(self.rfile.read(size))
                if not isinstance(value, dict):
                    raise ValueError("JSON object required")
                parts = [unquote(x) for x in urlsplit(self.path).path.split("/") if x]
                if parts == ["api", "conversations"]:
                    return self.reply(201, app.store.create(value.get("title", "New conversation"), value.get("audience")))
                if len(parts) == 3 and parts[:2] == ["api", "conversations"]:
                    return self.reply(202, app.action(parts[2], value))
                return self.reply(404, {"error": "Unknown endpoint"})
            except (ValueError, TypeError, KeyError, OSError) as exc:
                return self.reply(400, {"error": str(exc)[:600]})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.app = app
    return server
