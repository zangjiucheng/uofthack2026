from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading
from typing import Callable, Dict


class CommandRegistry:
    def __init__(self):
        self._handlers: Dict[str, Callable[[dict], dict]] = {}

    def register(self, name: str, handler: Callable[[dict], dict]):
        self._handlers[name] = handler

    def dispatch(self, name: str, payload: dict) -> dict:
        if name not in self._handlers:
            return {"error": f"unknown command '{name}'"}
        try:
            return self._handlers[name](payload)
        except Exception as exc:  # pragma: no cover
            return {"error": str(exc)}


def start_rest_server(command_registry: CommandRegistry, host: str = "0.0.0.0", port: int = 8080):
    """
    Start a simple REST server that accepts POST /<command> with JSON body.
    Dispatches to registered command handlers.
    """

    class Handler(BaseHTTPRequestHandler):
        def _set_cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

        def do_OPTIONS(self):  # noqa: N802
            self.send_response(200)
            self._set_cors()
            self.end_headers()

        def do_GET(self):  # noqa: N802
            cmd = self.path.lstrip("/")
            resp = command_registry.dispatch(cmd, {})
            data = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self._set_cors()
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(body.decode("utf-8") or "{}")
            except Exception:
                payload = {}
            cmd = self.path.lstrip("/")
            resp = command_registry.dispatch(cmd, payload)
            data = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self._set_cors()
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):  # noqa: ANN001
            return  # silence

    server = HTTPServer((host, port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[rest] HTTP POST server on http://{host}:{port}")
    return server
