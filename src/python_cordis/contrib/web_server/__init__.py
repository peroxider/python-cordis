"""F16: the transport layer (four-quadrant RPC over HTTP up + WebSocket down).

``web_server`` ships the transport as a plain, reversible plugin: it registers
``ctx.rpc`` / ``ctx.events`` / ``ctx.web`` and runs two carriers — the
standard-library ``http.server`` for the up-link (client-request →
server-response, plus client-response routing) and ``websockets`` on its own
event-loop thread for the downlink event stream (server-request). The message
model (:mod:`messages`) is decoupled from the carrier: the same four-quadrant
messages flow over both, correlated by the ``rpc_id`` minted by the initiator
and echoed by the responder.
"""

from .events import EventBus
from .messages import (
    ClientRequest,
    ClientResponse,
    RpcErrorCode,
    RpcMessage,
    RpcResult,
    ServerRequest,
    ServerResponse,
    decode_message,
    encode_message,
)
from .plugin import WebServerPlugin, plugin
from .registry import MethodKind, RpcRegistry

__all__ = [
    "EventBus",
    "RpcErrorCode",
    "RpcResult",
    "ClientRequest",
    "ServerResponse",
    "ServerRequest",
    "ClientResponse",
    "RpcMessage",
    "decode_message",
    "encode_message",
    "RpcRegistry",
    "MethodKind",
    "WebServerPlugin",
    "plugin",
]
