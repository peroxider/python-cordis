"""F16.2: the HTTP up-link server.

Runs on the standard-library ``ThreadingHTTPServer`` so each request executes
on its own thread and can call the synchronous kernel directly — no async
bridge is needed for the request/response half. Routes:

- ``POST /api/<method>``:  a ``client-request`` message in the body → the
  synchronous ``server-response`` message (the carrier carries the logical
  message, so ``rpc_id`` correlation survives the round trip).
- ``POST /api/respond``:   a ``client-response`` message → routed back to the
  waiting asker, answered with an ``accepted`` / ``not-pending`` receipt.
- ``GET /config.js``:      the WS down-link's bound port, so the frontend can
  open the event stream on the right port (HTTP and WS bind separate ports).
- ``GET /`` and ``GET /static/*``: the reference frontend.

The body is always a logical message or an ``RpcResult`` envelope, so the
client only ever parses JSON. Undecodable bodies are rejected with
``invalid_request`` (HTTP 400); method-level outcomes use HTTP 200.
"""

from __future__ import annotations

import json
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from .messages import (
    ClientRequest,
    ClientResponse,
    RpcErrorCode,
    RpcResult,
    ServerResponse,
    decode_message,
    encode_message,
)
from .registry import RpcRegistry

__all__ = ["HttpServer"]


class HttpServer:
    """The HTTP up-link server (synchronous request/response)."""

    def __init__(
        self,
        registry: RpcRegistry,
        static_root: Path | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self._registry = registry
        self._static_root = static_root
        self._host = host
        self._port = port
        self._ws_port: int | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._bound_port: int | None = None

    @property
    def bound_port(self) -> int:
        """The port the server actually bound (useful with ``port=0``)."""
        if self._bound_port is None:
            raise RuntimeError("HTTP server is not bound")
        return self._bound_port

    @property
    def ws_port(self) -> int | None:
        """The WS down-link's bound port, advertised via ``/config.js``."""
        return self._ws_port

    @ws_port.setter
    def ws_port(self, value: int | None) -> None:
        self._ws_port = value

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Bind and serve forever on a daemon thread."""
        handler = make_handler(self._registry, self._static_root)
        server = ThreadingHTTPServer((self._host, self._port), handler)
        setattr(server, "ws_port", self.ws_port)  # read by /config.js
        self._server = server
        self._bound_port = int(server.server_address[1])
        self._thread = threading.Thread(
            target=server.serve_forever, name="python-cordis-http", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop serving, release the port, and join the daemon thread."""
        server = self._server
        if server is not None:
            server.shutdown()
            server.server_close()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self._server = None
        self._bound_port = None
        self._thread = None


def make_handler(
    registry: RpcRegistry, static_root: Path | None
) -> type[BaseHTTPRequestHandler]:
    """Build a handler bound to ``registry`` and ``static_root``."""

    class _Handler(BaseHTTPRequestHandler):
        server_version = "python-cordis-web/0.1"
        #: Set per-handler-class by :func:`make_handler` after definition
        #: (a bare ``static_root = static_root`` in the class body would read
        #: the class-local name); declared here so the methods type-check.
        static_root: Path | None = None

        # ---- routing ----

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/":
                self._serve_index()
            elif path == "/config.js":
                self._config_js()
            elif path.startswith("/static/"):
                self._serve_static(path[len("/static/"):])
            else:
                self._json(404, RpcResult.failure(RpcErrorCode.METHOD_NOT_FOUND, f"no such resource {path!r}").to_dict())

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path == "/api/respond":
                self._api_respond()
            elif path.startswith("/api/"):
                self._api_call()
            else:
                self._json(404, RpcResult.failure(RpcErrorCode.METHOD_NOT_FOUND, f"no such route {path!r}").to_dict())

        # ---- API ----

        def _api_call(self) -> None:
            """POST /api/<method>: client-request → server-response."""
            payload = self._read_json()
            if payload is None:
                self._json(400, RpcResult.failure(RpcErrorCode.INVALID_REQUEST, "body is not a JSON object").to_dict())
                return
            try:
                message = decode_message(payload)
            except ValueError as exc:
                self._json(400, RpcResult.failure(RpcErrorCode.INVALID_REQUEST, str(exc)).to_dict())
                return
            if not isinstance(message, ClientRequest):
                self._json(400, RpcResult.failure(RpcErrorCode.INVALID_REQUEST, f"/api/<method> expects a client-request, got {message.kind!r}").to_dict())
                return
            response = registry.answer(message)
            self._json(200, encode_message(response))

        def _api_respond(self) -> None:
            """POST /api/respond: client-response → delivery receipt."""
            payload = self._read_json()
            if payload is None:
                self._json(400, RpcResult.failure(RpcErrorCode.INVALID_REQUEST, "body is not a JSON object").to_dict())
                return
            try:
                message = decode_message(payload)
            except ValueError as exc:
                self._json(400, RpcResult.failure(RpcErrorCode.INVALID_REQUEST, str(exc)).to_dict())
                return
            if not isinstance(message, ClientResponse):
                self._json(400, RpcResult.failure(RpcErrorCode.INVALID_REQUEST, "/api/respond expects a client-response, got %r" % (message.kind,)).to_dict())
                return
            receipt = registry.respond(message.rpc_id, message.result)
            self._json(200, receipt.to_dict())

        # ---- static ----

        def _config_js(self) -> None:
            """Advertise the WS down-link port for the frontend to discover."""
            ws_port = getattr(self.server, "ws_port", None) or 0
            body = f"window.WS_PORT = {ws_port};\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _serve_index(self) -> None:
            if self.static_root is None:
                self._json(404, RpcResult.failure(RpcErrorCode.METHOD_NOT_FOUND, "no frontend configured").to_dict())
                return
            file = self.static_root / "index.html"
            if not file.is_file():
                self._json(404, RpcResult.failure(RpcErrorCode.METHOD_NOT_FOUND, "index.html not found").to_dict())
                return
            self._file(file, "text/html; charset=utf-8")

        def _serve_static(self, name: str) -> None:
            if self.static_root is None:
                self._json(404, RpcResult.failure(RpcErrorCode.METHOD_NOT_FOUND, "no frontend configured").to_dict())
                return
            root = self.static_root.resolve()
            file = (root / unquote(name)).resolve()
            if file != root and root not in file.parents:
                self._json(404, RpcResult.failure(RpcErrorCode.METHOD_NOT_FOUND, f"no such resource {name!r}").to_dict())
                return
            if not file.is_file():
                self._json(404, RpcResult.failure(RpcErrorCode.METHOD_NOT_FOUND, f"no such resource {name!r}").to_dict())
                return
            content_type = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            self._file(file, content_type)

        # ---- io helpers ----

        def _read_json(self) -> dict[str, Any] | None:
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                return None
            if length <= 0:
                return None
            try:
                raw = self.rfile.read(length)
            except OSError:
                return None
            try:
                data = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            return data if isinstance(data, dict) else None

        def _file(self, file: Path, content_type: str) -> None:
            data = file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: int, obj: dict[str, Any]) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Any) -> None:
            """Suppress per-request logging (keeps tests and demos quiet)."""

    # 类体无法在同一作用域内以闭包变量自引用（`static_root = static_root`
    # 会让右侧也解析为类局部名），故在类定义后挂上静态资源根目录。
    _Handler.static_root = static_root
    return _Handler
