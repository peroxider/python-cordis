"""F7: the tool execution pipeline.

A tool call passes three waterfalls in order:

1. ``tools_pre_execute``  — approval/interception; a listener returning the
   ``REJECT`` sentinel (or otherwise not delegating) blocks execution.
2. ``tools_execute``      — the actual execution, with the registered tool body
   as the final tail of the chain (listeners may wrap/observe or take over).
3. ``tools_post_execute`` — result processing; listeners may rewrite the result.

The tool registry depends only on the ``HookRegistry``, never on any concrete
tool body, so middlewares (e.g. the approval example) are plain plugins.
"""

from __future__ import annotations

from typing import Any, Callable

from ..core.hook import HookRegistry, hookspec

__all__ = ["ToolRegistry", "REJECT", "tools_pre_execute", "tools_execute", "tools_post_execute"]


@hookspec
def tools_pre_execute(tool: str, request: dict[str, Any], next: Callable[[], Any]) -> Any:
    """Approval/interception hook. Return ``REJECT`` (or skip ``next()``) to block."""


@hookspec
def tools_execute(tool: str, request: dict[str, Any], next: Callable[[], Any]) -> Any:
    """Execution hook; the tool body is the chain tail. Return ``next()`` to delegate."""


@hookspec
def tools_post_execute(
    tool: str, request: dict[str, Any], result: Any, next: Callable[[], Any]
) -> Any:
    """Result processing hook. Return a value to rewrite ``result``."""


# Sentinel meaning "this pre_execute listener vetoes the tool call".
REJECT = object()


class ToolRegistry:
    """Registered tools, dispatched through the three-hook pipeline."""

    def __init__(self, hooks: HookRegistry) -> None:
        self._hooks = hooks
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> Callable[[], None]:
        """Register a tool body; returns an idempotent disposer."""
        self._tools[name] = fn

        def dispose() -> None:
            self._tools.pop(name, None)

        return dispose

    def list(self) -> list[str]:
        return sorted(self._tools)

    def run(self, name: str, **args: Any) -> dict[str, Any]:
        """Dispatch a tool call through pre → execute → post waterfalls."""
        fn = self._tools.get(name)
        if fn is None:
            return {"ok": False, "error": f"unknown tool: {name!r}"}

        request = dict(args)

        decision = self._hooks.waterfall(
            "tools_pre_execute", tool=name, request=request
        )
        if decision is REJECT:
            return {
                "ok": False,
                "error": f"tool {name!r} rejected by pre_execute",
                "reason": "REJECT",
            }

        result = self._hooks.waterfall(
            "tools_execute", tool=name, request=request, _tail=lambda: fn(**request)
        )
        result = self._hooks.waterfall(
            "tools_post_execute",
            tool=name,
            request=request,
            result=result,
            _initial=result,
        )
        return {"ok": True, "result": result}
