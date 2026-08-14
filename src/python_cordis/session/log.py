"""F13.1–F13.3: the append-only session log.

A :class:`Session` is an immutable, append-only event log. Events are frozen
:class:`SessionEvent` records (``type`` / ``seq`` / ``time`` / ``data`` /
``surface_op`` / ``source_seqs``) with ``seq`` contiguous from 0. Only the
three *surface* event types — ``user/message``, ``assistant/message`` and
``tool/result`` — participate in the model-visible message history projected
by :meth:`Session.derive_messages`; every other event is trace data.

Surface events must carry a ``surface_op`` marker; a session can be rebuilt
from an existing event array via :meth:`Session.from_events` (replay), which
must yield the same projected history as the original.
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

__all__ = [
    "SURFACE_USER_MESSAGE",
    "SURFACE_ASSISTANT_MESSAGE",
    "SURFACE_TOOL_RESULT",
    "SURFACE_TYPES",
    "SessionEvent",
    "Session",
    "stringify",
]

SURFACE_USER_MESSAGE = "user/message"
SURFACE_ASSISTANT_MESSAGE = "assistant/message"
SURFACE_TOOL_RESULT = "tool/result"
SURFACE_TYPES = frozenset(
    {SURFACE_USER_MESSAGE, SURFACE_ASSISTANT_MESSAGE, SURFACE_TOOL_RESULT}
)


def stringify(value: Any) -> str:
    """Render an arbitrary value as readable text (for tool results, etc.)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


@dataclass(frozen=True)
class SessionEvent:
    """One immutable record in the session log.

    ``data`` is a JSON-friendly mapping (deep-copied on append). ``surface_op``
    is the operation label required on every surface event. ``source_seqs``
    links this event back to the events that produced it (e.g. a tool result
    to the assistant message that requested the call).
    """

    type: str
    seq: int
    time: float
    data: Mapping[str, Any]
    surface_op: str | None = None
    source_seqs: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict (for persistence)."""
        return {
            "type": self.type,
            "seq": self.seq,
            "time": self.time,
            "data": dict(self.data),
            "surface_op": self.surface_op,
            "source_seqs": list(self.source_seqs),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "SessionEvent":
        """Rebuild an event from the dict produced by :meth:`to_dict`."""
        surface_op = raw.get("surface_op")
        return cls(
            type=str(raw["type"]),
            seq=int(raw["seq"]),
            time=float(raw["time"]),
            data=dict(raw["data"]),
            surface_op=surface_op if isinstance(surface_op, str) else None,
            source_seqs=tuple(int(s) for s in (raw.get("source_seqs") or ())),
        )


class Session:
    """Append-only, immutable event log for one conversation.

    The log has no modify or delete API; events cannot be rewritten after
    append. ``seq`` equals the log length at the moment of append, so it is
    contiguous from 0.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self._events: list[SessionEvent] = []
        self._listeners: list[Callable[[SessionEvent], None]] = []

    @property
    def length(self) -> int:
        """Number of appended events (== next ``seq``)."""
        return len(self._events)

    def subscribe(
        self, listener: Callable[[SessionEvent], None]
    ) -> Callable[[], None]:
        """Notify ``listener`` (with the appended event) on each append.

        This is the notification seam for event sourcing: any plugin may
        subscribe, and the returned disposer removes the listener. Broadcasters
        (e.g. the transport ``EventBus``) hook in here without touching the
        append path.
        """
        self._listeners.append(listener)

        def dispose() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return dispose

    def append(
        self,
        type_: str,
        data: Mapping[str, Any],
        *,
        surface_op: str | None = None,
        source_seqs: Sequence[int] = (),
    ) -> int:
        """Append an event and return its ``seq``.

        A surface event without a ``surface_op`` marker is rejected, because a
        surface event is exactly one whose content becomes model-visible and
        the marker names the operation that made it so.
        """
        if type_ in SURFACE_TYPES and surface_op is None:
            raise ValueError(
                f"surface event {type_!r} requires a surface_op marker"
            )
        seq = len(self._events)
        event = SessionEvent(
            type=type_,
            seq=seq,
            time=time.time(),
            data=dict(copy.deepcopy(dict(data))),
            surface_op=surface_op,
            source_seqs=tuple(source_seqs),
        )
        self._events.append(event)
        for listener in self._listeners:
            listener(event)
        return seq

    def events(self) -> tuple[SessionEvent, ...]:
        """Return a snapshot of the log (immutable view)."""
        return tuple(self._events)

    def get(self, seq: int) -> SessionEvent:
        """Return the event at ``seq`` (indexed by position, 0-based)."""
        return self._events[seq]

    def derive_messages(self) -> list[dict[str, Any]]:
        """Project the model-visible message history from surface events.

        ``user/message`` and ``assistant/message`` contribute their content;
        ``assistant/message`` may also carry ``tool_calls``; ``tool/result``
        becomes a ``tool`` message keyed by the call ``id``. Structural events
        (boundaries, chunks, usage) never appear here.
        """
        messages: list[dict[str, Any]] = []
        for ev in self._events:
            if ev.type == SURFACE_USER_MESSAGE:
                messages.append(
                    {"role": "user", "content": str(ev.data.get("content", ""))}
                )
            elif ev.type == SURFACE_ASSISTANT_MESSAGE:
                msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": str(ev.data.get("content", "")),
                }
                if "tool_calls" in ev.data:
                    msg["tool_calls"] = list(ev.data["tool_calls"])
                messages.append(msg)
            elif ev.type == SURFACE_TOOL_RESULT:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(ev.data.get("id", "")),
                        "content": stringify(ev.data.get("result")),
                    }
                )
        return messages

    @classmethod
    def from_events(
        cls, session_id: str, events: Sequence[SessionEvent]
    ) -> "Session":
        """Rebuild a session from an existing event array (replay).

        The events must already carry contiguous ``seq`` values starting at 0
        (i.e. a single session's log), otherwise the rebuild is rejected.
        """
        if [ev.seq for ev in events] != list(range(len(events))):
            raise ValueError(
                "events must have contiguous seq values starting from 0"
            )
        session = cls(session_id)
        session._events = list(events)
        return session
