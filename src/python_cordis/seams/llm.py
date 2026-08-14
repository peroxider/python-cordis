"""F6: the LLM capability seam.

A capability seam is interface + provider + consumer:

- ``LlmAdapter`` : the Service Definition. One method, ``stream``, which yields
  a sequence of normalized :class:`LlmEvent` objects.
- ``MockProvider`` : a deterministic, offline Provider that echoes the last
  user message (no API key, no network) for tests and examples.
- ``LlmStream`` : the Consumer. It routes the request through the
  ``llm_request`` waterfall (plugins may rewrite it), streams the adapter's
  events through the ``llm_event`` waterfall (plugins may observe, rewrite or
  drop events), and normalizes any adapter exception into a single ``failure``
  event so downstream never sees a bare exception.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator

from ..core.hook import HookRegistry, hookspec

__all__ = [
    "LlmEvent",
    "LlmAdapter",
    "MockProvider",
    "LlmStream",
    "llm_request",
    "llm_event",
    "KIND_START",
    "KIND_TEXT",
    "KIND_USAGE",
    "KIND_FINISH",
    "KIND_FAILURE",
    "KIND_TOOL_CALL",
]

KIND_START = "start"
KIND_TEXT = "text"
KIND_USAGE = "usage"
KIND_FINISH = "finish"
KIND_FAILURE = "failure"
KIND_TOOL_CALL = "tool_call"


@dataclass
class LlmEvent:
    """A normalized incremental stream event.

    ``kind`` is one of the ``KIND_*`` constants. ``data`` carries per-kind
    payloads, e.g. ``{"id": ...}`` for start, the text chunk for text,
    ``{"prompt_tokens": ..., "completion_tokens": ...}`` for usage,
    ``{"id", "tool", "args"}`` for tool_call, and
    ``{"error": ..., "type": ...}`` for failure.
    """

    kind: str
    data: Any = None


@hookspec
def llm_request(request: dict[str, Any], next: Any) -> None:
    """Rewrite the request in place (``request["messages"]`` / ``request["params"]``).

    ``request`` is the same mutable dict threaded through every listener, so
    mutations propagate downstream; return ``next()`` to delegate.
    """


@hookspec
def llm_event(event: LlmEvent, next: Any) -> LlmEvent | None:
    """Observe or rewrite each streamed event. Return ``None`` to drop it."""


class LlmAdapter(ABC):
    """Contract for a chat-completion provider.

    ``stream`` must return an iterator of :class:`LlmEvent` (start/text/usage/
    finish). Implementations may raise; the exception is normalized into a
    ``failure`` event by :class:`LlmStream`.
    """

    @abstractmethod
    def stream(
        self, messages: list[dict[str, Any]], **params: Any
    ) -> Iterator[LlmEvent]:
        """Yield the incremental events for ``messages``."""


class MockProvider(LlmAdapter):
    """Deterministic, offline adapter: echoes the last user message.

    Emits ``start`` -> one ``text`` event per word -> ``usage`` -> ``finish``.
    The output is a pure function of the input, so it is fully predictable.
    """

    name = "mock"

    def stream(
        self, messages: list[dict[str, Any]], **params: Any
    ) -> Iterator[LlmEvent]:
        text = next(
            (
                str(m.get("content", ""))
                for m in reversed(messages)
                if m.get("role") == "user"
            ),
            "",
        )
        words = text.split()
        yield LlmEvent(KIND_START, {"id": "mock-1", "provider": self.name})
        for word in words:
            yield LlmEvent(KIND_TEXT, word)
        yield LlmEvent(
            KIND_USAGE,
            {"prompt_tokens": len(text), "completion_tokens": len(words)},
        )
        yield LlmEvent(KIND_FINISH, {"stop_reason": "stop"})


class LlmStream:
    """Consumer that drives one adapter call through both waterfalls.

    Usage::

        stream = LlmStream(adapter, hooks, messages, **params)
        for event in stream.run():
            ...
    """

    def __init__(
        self,
        adapter: LlmAdapter,
        hooks: HookRegistry,
        messages: list[dict[str, Any]],
        **params: Any,
    ) -> None:
        self._adapter = adapter
        self._hooks = hooks
        self.messages = messages
        self.params = dict(params)

    def run(self) -> Iterator[LlmEvent]:
        """Run request rewrite -> adapter stream -> per-event waterfall.

        Request middlewares mutate the shared ``request`` dict (rewrites
        propagate through every listener); event middlewares observe, rewrite,
        or drop individual events.
        """
        request: dict[str, Any] = {"messages": self.messages, "params": self.params}
        self._hooks.waterfall("llm_request", request=request)
        messages = request["messages"]
        params = request["params"]

        for event in self._safe_stream(messages, params):
            # _initial=event: 监听器都委托时保持事件原样（而非回退到 None）
            out = self._hooks.waterfall("llm_event", event=event, _initial=event)
            if out is None:
                continue  # middleware dropped the event
            yield out

    def _safe_stream(
        self, messages: list[dict[str, Any]], params: dict[str, Any]
    ) -> Iterator[LlmEvent]:
        """Iterate the adapter, normalizing any exception into one failure event."""
        try:
            for event in self._adapter.stream(messages, **params):
                yield event
        except Exception as exc:  # noqa: BLE001  (normalized for downstream)
            yield LlmEvent(
                KIND_FAILURE,
                {"error": str(exc), "type": type(exc).__name__},
            )
