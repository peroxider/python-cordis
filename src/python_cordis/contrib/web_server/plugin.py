"""F16.4: the transport plugin (``web_server``).

A plain, reversible plugin: ``start(ctx)`` installs ``ctx.rpc`` /
``ctx.events`` / ``ctx.web``, starts the HTTP + WebSocket carriers, and records
every teardown as a context effect so ``Fiber.stop()`` (or any effect teardown)
stops the servers and releases the ports in reverse order — no privileged core
involvement. ``host`` / ``port`` come from the plugin configuration (overlay),
and ``ctx.sessions`` must already be registered by the application.

The module-level :data:`plugin` instance is discovered via the
``python_cordis.plugins`` entry point, so ``pip install python-cordis[web]``
makes it visible to ``HookRegistry.load_entry_points()``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ...session import SessionStore
from .events import EventBus
from .http import HttpServer
from .registry import MethodKind, RpcRegistry
from .ws import EVENT_METHOD, WebSocketServer

if TYPE_CHECKING:
    from ...core.context import Context

__all__ = ["WebServerPlugin", "plugin"]


class WebServerPlugin:
    """Installs the transport services and runs both carriers."""

    name = "web-server"

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        static_root: Path | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._static_root = static_root
        self._ctx: "Context | None" = None
        self._bus: EventBus | None = None
        self._registry: RpcRegistry | None = None
        self._ws: WebSocketServer | None = None
        self._http: HttpServer | None = None

    # ---- services ----
    #
    # Plugins are introspected by pluggy on registration (``dir()`` +
    # ``getattr`` over every attribute), so these getters must never raise.
    # They return ``None`` until :meth:`start` has installed the services.

    @property
    def bus(self) -> EventBus | None:
        """The thread-safe event bus (``ctx.events``), or ``None`` pre-start."""
        return self._bus

    @property
    def registry(self) -> RpcRegistry | None:
        """The RPC registry (``ctx.rpc``), or ``None`` pre-start."""
        return self._registry

    @property
    def http_port(self) -> int | None:
        """The bound HTTP port, or ``None`` pre-start."""
        if self._http is None:
            return None
        return self._http.bound_port

    @property
    def ws_port(self) -> int | None:
        """The bound WebSocket port, or ``None`` pre-start."""
        if self._ws is None:
            return None
        return self._ws.bound_port

    # ---- lifecycle ----

    def start(self, ctx: "Context") -> "WebServerPlugin":
        """Install services and start both carriers (idempotent).

        Requires ``ctx.sessions`` (a :class:`SessionStore`) to be registered
        first. Teardown effects run in reverse order: HTTP stops, WS stops,
        then the bus detaches from the store.
        """
        if self._bus is not None:
            return self
        sessions: SessionStore = ctx.sessions
        bus = EventBus()
        registry = RpcRegistry()
        # 两个载体各自绑定独立端口：配置的 ``port`` 给 HTTP（前端入口 URL）；
        # WS 用临时端口，启动后把实际端口暴露给 HTTP 的 ``/config.js`` 供前端发现。
        ws = WebSocketServer(bus, sessions, self._host, 0)
        http = HttpServer(registry, self._static_root, self._host, self._port)
        registry.set_downlink(ws.publish)
        # the downlink's own event stream is statically a push (no response)
        registry.register(EVENT_METHOD, MethodKind.PUSH)

        ctx.register("rpc", registry)
        ctx.register("events", bus)
        ctx.register("web", self)

        ctx.effect(bus.attach_store(sessions))
        ctx.effect(ws.stop)
        ctx.effect(http.stop)

        self._ctx = ctx
        self._bus = bus
        self._registry = registry
        self._ws = ws
        self._http = http
        ws.start()
        http.ws_port = ws.bound_port  # 前端据此连接 WS 下行
        http.start()
        return self


#: The entry-point instance discovered via ``python_cordis.plugins``.
plugin = WebServerPlugin()
