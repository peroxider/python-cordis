"""F15: session query engine.

Text is extracted per event: only the surface events contribute searchable
content (``user/message`` / ``assistant/message`` contribute their content,
``tool/result`` contributes its serialized result); structural events
(boundaries, steps, chunks, usage) never produce hits. Queries are matched as
case-insensitive substring searches with the pattern regex-escaped, so special
characters cannot raise a parsing error.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .session import (
    SURFACE_ASSISTANT_MESSAGE,
    SURFACE_TOOL_RESULT,
    SURFACE_USER_MESSAGE,
    SessionEvent,
    SessionStore,
    stringify,
)

__all__ = ["SearchHit", "SessionQueryEngine", "InMemoryQueryEngine", "extract_text"]

_SNIPPET_RADIUS = 40


@dataclass(frozen=True)
class SearchHit:
    """One event-level match: the owning session, the event ``seq``, and a
    snippet window around the match."""

    session_id: str
    seq: int
    snippet: str


def extract_text(event: SessionEvent) -> str | None:
    """Return the searchable text of ``event``, or ``None`` if structural."""
    if event.type in (SURFACE_USER_MESSAGE, SURFACE_ASSISTANT_MESSAGE):
        return str(event.data.get("content", ""))
    if event.type == SURFACE_TOOL_RESULT:
        return stringify(event.data.get("result"))
    return None


class SessionQueryEngine(ABC):
    """Contract for searching sessions (in-session and cross-session)."""

    @abstractmethod
    def search_events(self, query: str, session_id: str) -> list[SearchHit]:
        """Return event-level hits for ``query`` inside ``session_id``."""

    @abstractmethod
    def search_sessions(self, query: str) -> list[str]:
        """Return session ids that contain at least one hit for ``query``."""


class InMemoryQueryEngine(SessionQueryEngine):
    """In-memory engine over a :class:`SessionStore`."""

    def __init__(self, sessions: SessionStore) -> None:
        self._sessions = sessions

    def search_events(self, query: str, session_id: str) -> list[SearchHit]:
        session = self._sessions.get(session_id)
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        hits: list[SearchHit] = []
        for ev in session.events():
            text = extract_text(ev)
            if text is None:
                continue
            match = pattern.search(text)
            if match is not None:
                hits.append(
                    SearchHit(
                        session_id=session_id,
                        seq=ev.seq,
                        snippet=_snippet(text, match.start()),
                    )
                )
        return hits

    def search_sessions(self, query: str) -> list[str]:
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        found: list[str] = []
        for sid in self._sessions.list():
            for ev in self._sessions.get(sid).events():
                text = extract_text(ev)
                if text is not None and pattern.search(text) is not None:
                    found.append(sid)
                    break
        return found


def _snippet(text: str, start: int, radius: int = _SNIPPET_RADIUS) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), start + radius)
    return (
        ("…" if lo > 0 else "")
        + text[lo:hi]
        + ("…" if hi < len(text) else "")
    )
