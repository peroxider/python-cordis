"""F16.2: the RPC registry and static method table.

``RpcRegistry`` owns three responsibilities:

- hold the *method table*: each method name is statically classified as
  ``call`` (a server-side handler), ``ask`` (the server asks the client and
  waits for a ``client-response``) or ``push`` (the server pushes, no response
  expected). There is strictly no third mode, and the message content never
  decides — the table does.
- answer a ``client-request`` synchronously, always through an ``RpcResult``
  envelope: an unknown method, a wrong-quadrant method, or a raised handler
  folds into a coded error, never a bare exception.
- route a ``client-response`` back to the waiting asker via a pending table
  keyed by ``rpc_id``, returning an ``accepted`` / ``not-pending`` receipt so
  the HTTP up-link can acknowledge delivery without throwing.

The registry does not own a carrier: an injected ``downlink`` callable (set by
the transport plugin) publishes ``server-request`` messages to the client.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Mapping

from .messages import (
    ClientRequest,
    RpcErrorCode,
    RpcResult,
    ServerRequest,
    ServerResponse,
)

__all__ = ["MethodKind", "Method", "RpcRegistry"]

Handler = Callable[[Mapping[str, Any]], Any]
Downlink = Callable[[ServerRequest], None]


class MethodKind(str, Enum):
    """The static classification of a method in the table (strictly three)."""

    CALL = "call"  # server-side handler; client-request → server-response
    ASK = "ask"  # server asks the client; server-request → client-response
    PUSH = "push"  # server pushes; server-request, no response expected


@dataclass(frozen=True)
class Method:
    """One table entry: the static kind plus the (optional) call handler."""

    kind: MethodKind
    handler: Handler | None = None


@dataclass(frozen=True)
class _Pending:
    """A waiting asker: the signal and the slot the responder fills in."""

    event: threading.Event
    holder: dict[str, Any]


class RpcRegistry:
    """Method table + synchronous answer + ask/respond routing."""

    def __init__(self, downlink: Downlink | None = None) -> None:
        self._downlink = downlink
        self._methods: dict[str, Method] = {}
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.RLock()

    # ---- method table (reversible) ----

    def register(
        self,
        method: str,
        kind: MethodKind,
        handler: Handler | None = None,
    ) -> Callable[[], None]:
        """Register ``method`` with its static ``kind``; returns a disposer.

        A later registration of the same name shadows an earlier one; the
        disposer restores the previous entry (or removes the name).
        """
        with self._lock:
            previous = self._methods.get(method)
            self._methods[method] = Method(kind, handler)

        def dispose() -> None:
            with self._lock:
                if self._methods.get(method) == Method(kind, handler):
                    if previous is None:
                        self._methods.pop(method, None)
                    else:
                        self._methods[method] = previous

        return dispose

    def lookup(self, method: str) -> Method | None:
        """Return the table entry for ``method``, or ``None`` when absent."""
        with self._lock:
            return self._methods.get(method)

    def methods(self) -> list[str]:
        """Return the registered method names, sorted."""
        with self._lock:
            return sorted(self._methods)

    def set_downlink(self, downlink: Downlink | None) -> None:
        """Set the publisher used by ``ask`` / ``push`` (wired by the plugin)."""
        self._downlink = downlink

    # ---- client-request → server-response (HTTP up-link) ----

    def answer(self, request: ClientRequest) -> ServerResponse:
        """Synchronously resolve a client-request; always returns an envelope."""
        method = self.lookup(request.method)
        if method is None:
            return ServerResponse(
                "server-response",
                request.rpc_id,
                RpcResult.failure(
                    RpcErrorCode.METHOD_NOT_FOUND,
                    f"no such method {request.method!r}",
                ),
            )
        if method.kind is not MethodKind.CALL or method.handler is None:
            return ServerResponse(
                "server-response",
                request.rpc_id,
                RpcResult.failure(
                    RpcErrorCode.INVALID_METHOD,
                    f"method {request.method!r} is {method.kind.value}, "
                    "not callable by the client",
                ),
            )
        try:
            value = method.handler(request.params)
        except Exception as exc:  # noqa: BLE001  (folded into the envelope)
            return ServerResponse(
                "server-response",
                request.rpc_id,
                RpcResult.failure(
                    RpcErrorCode.INTERNAL_ERROR,
                    f"{type(exc).__name__}: {exc}",
                ),
            )
        return ServerResponse("server-response", request.rpc_id, RpcResult.success(value))

    # ---- server-request (ask / push, WS down-link) ----

    @staticmethod
    def mint() -> str:
        """Mint a fresh ``rpc_id`` for a server→client request."""
        return uuid.uuid4().hex

    def push(self, method: str, params: Mapping[str, Any]) -> ServerRequest | None:
        """Issue a fire-and-forget ``server-request`` (method must be PUSH).

        Returns the request (published to the downlink), or ``None`` when the
        method is unknown / not PUSH / no downlink is connected.
        """
        request = self._guard_server_request(method, params, MethodKind.PUSH)
        if request is None:
            return None
        if self._downlink is not None:
            self._downlink(request)
        return request

    def ask(
        self, method: str, params: Mapping[str, Any], timeout: float = 30.0
    ) -> RpcResult[Any]:
        """Issue an ask and block for the ``client-response`` (method ASK).

        The request is published to the downlink, then this thread waits on the
        pending entry. ``respond`` (from the HTTP up-link) fills the slot and
        wakes the waiter. A timeout returns a ``timeout`` error; the pending
        entry is always removed before returning.
        """
        request = self._guard_server_request(method, params, MethodKind.ASK)
        if request is None:
            return RpcResult.failure(
                RpcErrorCode.METHOD_NOT_FOUND,
                f"no ASK method {method!r} (or no downlink)",
            )
        pending = _Pending(threading.Event(), {})
        with self._lock:
            self._pending[request.rpc_id] = pending
        try:
            if self._downlink is not None:
                self._downlink(request)
            if not pending.event.wait(timeout):
                return RpcResult.failure(
                    RpcErrorCode.TIMEOUT,
                    f"no client-response for ask {request.rpc_id!r} "
                    f"within {timeout:g}s",
                )
            value = pending.holder.get("result")
            return value if isinstance(value, RpcResult) else RpcResult.failure(
                RpcErrorCode.INTERNAL_ERROR,
                "ask completed without a result",
            )
        finally:
            with self._lock:
                self._pending.pop(request.rpc_id, None)

    def _guard_server_request(
        self, method: str, params: Mapping[str, Any], kind: MethodKind
    ) -> ServerRequest | None:
        """Build a server-request only when the table says ``kind`` (static)."""
        entry = self.lookup(method)
        if entry is None or entry.kind is not kind:
            return None
        return ServerRequest("server-request", self.mint(), method, dict(params))

    # ---- client-response routing (HTTP up-link /api/respond) ----

    def respond(self, rpc_id: str, result: RpcResult[Any]) -> RpcResult[dict[str, str]]:
        """Route a client-response back to its waiting asker.

        Returns an ``accepted`` receipt when a waiter was found and woken, or a
        ``not_pending`` error when the rpc_id has no pending asker (stale or
        already answered).
        """
        with self._lock:
            pending = self._pending.get(rpc_id)
        if pending is None:
            return RpcResult.failure(
                RpcErrorCode.NOT_PENDING,
                f"no pending ask for rpc_id {rpc_id!r}",
                rpc_id=rpc_id,
            )
        pending.holder["result"] = result
        pending.event.set()
        return RpcResult.success({"status": "accepted", "rpc_id": rpc_id})
