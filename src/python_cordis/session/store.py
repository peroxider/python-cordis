"""F13.4: the session store (``ctx.sessions`` service).

``SessionStore`` is a plain, replaceable service: it registers as
``ctx.sessions``, manages live sessions via ``create`` / ``append`` / ``get``
/ ``dispose``, and has no privileged dependency on the kernel.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Mapping, Sequence

from .log import Session

__all__ = ["SessionStore", "SessionNotFound"]

_LifecycleListener = Callable[[str, "Session | None"], None]


class SessionNotFound(KeyError):
    """Raised when a session id is not present in the store."""


class SessionStore:
    """Registry of live sessions.

    ``subscribe`` is the creation notification seam: a listener is called with
    ``(session_id, session)`` on create and ``(session_id, None)`` on dispose.
    Broadcasters (e.g. the transport ``EventBus``) use it to follow sessions
    that did not exist when they attached.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._listeners: list[_LifecycleListener] = []

    def subscribe(self, listener: _LifecycleListener) -> Callable[[], None]:
        """Notify ``listener`` on session create / dispose; returns a disposer."""
        self._listeners.append(listener)

        def dispose() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return dispose

    def create(self, session_id: str | None = None) -> Session:
        """Create and register a new session; returns it."""
        sid = session_id or uuid.uuid4().hex
        session = Session(sid)
        self._sessions[sid] = session
        for listener in self._listeners:
            listener(sid, session)
        return session

    def append(
        self,
        session_id: str,
        type_: str,
        data: Mapping[str, Any],
        *,
        surface_op: str | None = None,
        source_seqs: Sequence[int] = (),
    ) -> int:
        """Append an event to an existing session; returns its ``seq``."""
        return self.get(session_id).append(
            type_, data, surface_op=surface_op, source_seqs=source_seqs
        )

    def get(self, session_id: str) -> Session:
        """Return a live session; raises :class:`SessionNotFound` when absent."""
        try:
            return self._sessions[session_id]
        except KeyError:
            raise SessionNotFound(
                f"session {session_id!r} is not in the store"
            ) from None

    def dispose(self, session_id: str) -> None:
        """Remove a session from the store (reversible, idempotent)."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            for listener in self._listeners:
                listener(session_id, None)

    def list(self) -> list[str]:
        """Return the ids of all live sessions, sorted."""
        return sorted(self._sessions)
