"""F16.1: the transport message model (four-quadrant RPC).

Logical messages are decoupled from the physical carrier: the same four
:class:`RpcMessage` variants flow over both HTTP and WebSocket, and the
``rpc_id`` is minted by the initiator and echoed back by the responder so the
two sides correlate a request with its answer across carriers.

The four quadrants:

- ``client-request``:  the client asks the server (HTTP up-link).
- ``server-response``: the server's synchronous answer (HTTP down-link).
- ``server-request``:  the server asks or pushes to the client (WS down-link).
  Whether a response is expected is decided *statically* by the method table
  (``ask`` vs ``push``), never by the message content — there is strictly no
  third mode.
- ``client-response``: the client's answer to a ``server-request`` ask
  (HTTP up-link, routed back to the waiting asker by ``rpc_id``).

Every business method returns through the :class:`RpcResult` envelope; an
unknown failure is folded into ``internal`` so no bare exception crosses the
wire.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, Literal, Mapping, TypeVar, Union

__all__ = [
    "RpcErrorCode",
    "RpcResult",
    "ClientRequest",
    "ServerResponse",
    "ServerRequest",
    "ClientResponse",
    "RpcMessage",
    "decode_message",
    "encode_message",
]

T = TypeVar("T")


class RpcErrorCode(str, Enum):
    """The closed set of wire error codes; nothing else crosses the boundary."""

    INVALID_REQUEST = "invalid_request"  # malformed message / unknown kind
    INVALID_METHOD = "invalid_method"  # method exists but wrong quadrant
    METHOD_NOT_FOUND = "method_not_found"  # no such method
    INTERNAL_ERROR = "internal_error"  # handler raised (details carry the cause)
    NOT_PENDING = "not_pending"  # a client-response with no waiting asker
    TIMEOUT = "timeout"  # an ask gave up waiting for the client-response


@dataclass(frozen=True)
class RpcResult(Generic[T]):
    """The uniform envelope: success carries ``result``, failure carries
    ``error`` (a mapping whose ``code`` is an :class:`RpcErrorCode` value)."""

    ok: bool
    result: T | None = None
    error: dict[str, Any] | None = None

    @classmethod
    def success(cls, result: T | None = None) -> "RpcResult[T]":
        """A success envelope carrying ``result``."""
        return cls(True, result)

    @classmethod
    def failure(
        cls, code: RpcErrorCode, message: str, **details: Any
    ) -> "RpcResult[Any]":
        """A failure envelope with the closed code and a human-readable message."""
        return cls(False, None, {"code": code.value, "message": message, **details})

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "RpcResult[Any]":
        """Rebuild an envelope from its wire dict."""
        return cls(bool(raw.get("ok")), raw.get("result"), raw.get("error"))

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        return {"ok": self.ok, "result": self.result, "error": self.error}


@dataclass(frozen=True)
class ClientRequest:
    """client → server: invoke a server-side method (HTTP up-link)."""

    kind: Literal["client-request"]
    rpc_id: str
    method: str
    params: Mapping[str, Any]


@dataclass(frozen=True)
class ServerResponse:
    """server → client: the synchronous answer to a :class:`ClientRequest`."""

    kind: Literal["server-response"]
    rpc_id: str
    result: RpcResult[Any]


@dataclass(frozen=True)
class ServerRequest:
    """server → client: an ask or a push (WS down-link)."""

    kind: Literal["server-request"]
    rpc_id: str
    method: str
    params: Mapping[str, Any]


@dataclass(frozen=True)
class ClientResponse:
    """client → server: the answer to a :class:`ServerRequest` ask."""

    kind: Literal["client-response"]
    rpc_id: str
    result: RpcResult[Any]


RpcMessage = Union[ClientRequest, ServerResponse, ServerRequest, ClientResponse]


def encode_message(msg: RpcMessage) -> dict[str, Any]:
    """Serialize a message to a JSON-friendly dict tagged by ``kind``.

    ``params`` / ``result`` are deep-copied so the wire dict is independent of
    the in-memory message.
    """
    import copy as _copy

    if isinstance(msg, ClientRequest):
        return {
            "kind": "client-request",
            "rpc_id": msg.rpc_id,
            "method": msg.method,
            "params": _copy.deepcopy(dict(msg.params)),
        }
    if isinstance(msg, ServerResponse):
        return {
            "kind": "server-response",
            "rpc_id": msg.rpc_id,
            "result": msg.result.to_dict(),
        }
    if isinstance(msg, ServerRequest):
        return {
            "kind": "server-request",
            "rpc_id": msg.rpc_id,
            "method": msg.method,
            "params": _copy.deepcopy(dict(msg.params)),
        }
    if isinstance(msg, ClientResponse):
        return {
            "kind": "client-response",
            "rpc_id": msg.rpc_id,
            "result": msg.result.to_dict(),
        }
    raise TypeError(f"unreachable: unknown message {type(msg).__name__}")  # closed union


def decode_message(payload: Mapping[str, Any]) -> RpcMessage:
    """Decode a wire dict into the matching variant; raises :class:`ValueError`
    for a malformed message or an unknown ``kind`` (callers fold it into an
    ``invalid_request`` envelope)."""
    kind = payload.get("kind")
    rpc_id = payload.get("rpc_id")
    if not isinstance(rpc_id, str) or not rpc_id:
        raise ValueError("message must carry a non-empty string rpc_id")
    if kind == "client-request":
        return ClientRequest(
            "client-request", rpc_id, _require_method(payload), _params(payload)
        )
    if kind == "server-request":
        return ServerRequest(
            "server-request", rpc_id, _require_method(payload), _params(payload)
        )
    if kind == "server-response":
        return ServerResponse(
            "server-response", rpc_id, _require_result(payload)
        )
    if kind == "client-response":
        return ClientResponse(
            "client-response", rpc_id, _require_result(payload)
        )
    raise ValueError(f"unknown message kind {kind!r}")


def _require_method(payload: Mapping[str, Any]) -> str:
    method = payload.get("method")
    if not isinstance(method, str) or not method:
        raise ValueError("message must carry a non-empty string method")
    return method


def _params(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = payload.get("params")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _require_result(payload: Mapping[str, Any]) -> RpcResult[Any]:
    raw = payload.get("result")
    if not isinstance(raw, Mapping):
        raise ValueError("message must carry a mapping result")
    return RpcResult.from_dict(raw)
