"""F17: human-in-the-loop tool approval over the ask/respond quadrant.

A plain plugin that mounts a ``tools_pre_execute`` hookimpl: when a tool call
requires approval, it issues an ``RpcRegistry.ask("tool.approve", ...)`` and
maps the human decision to ``next()`` (approved) or ``REJECT`` (denied or
timeout). The ASK blocks the calling thread until the frontend answers over the
HTTP up-link (``POST /api/respond``), so the tool pipeline pauses at the
approval gate — "model requests a tool → human approves → the tool runs".

Safe by default: an ASK with no reachable downlink, or one that times out,
denies the tool (a blocked tool beats an unapproved side effect).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from ..core.hook import hookimpl
from ..seams.pipeline import REJECT
from .web_server import MethodKind, RpcRegistry

if TYPE_CHECKING:
    from ..core.context import Context

__all__ = ["APPROVE_METHOD", "ApprovalPlugin", "plugin"]

#: The ASK method name: the server asks the frontend to approve a tool call.
APPROVE_METHOD = "tool.approve"


class ApprovalPlugin:
    """Gate tool execution on a human decision over the transport.

    ``start(ctx, hooks)`` binds the RPC registry from ``ctx.rpc``, registers
    ``tool.approve`` as an ASK method, and registers this instance on the
    ``hooks`` registry so its ``tools_pre_execute`` hookimpl fires. Both
    registrations are recorded as reversible context effects.

    A :data:`require` predicate decides which tool calls need approval; it
    defaults to every tool. The predicate sees the tool name and its request
    params, so a deployment can approve only, say, ``write_file``.
    """

    name = "approval"

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        require: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        self._rpc: RpcRegistry | None = None
        self._timeout = timeout
        self._require = require if require is not None else (lambda tool, request: True)

    @property
    def rpc(self) -> RpcRegistry | None:
        """The bound registry, or ``None`` before :meth:`start`."""
        return self._rpc

    def start(
        self, ctx: "Context", hooks: Any | None = None
    ) -> "ApprovalPlugin":
        """Bind the registry and register the ASK method and the hookimpl
        (idempotent). Requires ``ctx.rpc`` (the transport plugin) to be
        registered first; ``hooks`` must be the ``HookRegistry`` that owns the
        ``tools_pre_execute`` spec.
        """
        if self._rpc is not None:
            return self
        rpc: RpcRegistry = ctx.rpc
        dispose_method = rpc.register(APPROVE_METHOD, MethodKind.ASK)
        ctx.effect(dispose_method)
        if hooks is not None:
            hooks.register(self)
            ctx.effect(lambda: hooks.unregister(self))
        self._rpc = rpc
        return self

    @hookimpl
    def tools_pre_execute(
        self, tool: str, request: dict[str, Any], next: Callable[[], Any]
    ) -> Any:
        """Gate ``tool`` on a human decision; denies when no decision arrives.

        The ASK is issued only when bound and when :data:`require` says so;
        otherwise the call is delegated straight through.
        """
        rpc = self._rpc
        if rpc is None or not self._require(tool, request):
            return next()
        result = rpc.ask(
            APPROVE_METHOD,
            {"tool": tool, "request": request},
            timeout=self._timeout,
        )
        if result.ok and isinstance(result.result, dict) and result.result.get("approved"):
            return next()
        return REJECT


#: The entry-point instance discovered via ``python_cordis.plugins``. It stays
#: inert (delegates every call) until an application calls :meth:`start`.
plugin = ApprovalPlugin()
