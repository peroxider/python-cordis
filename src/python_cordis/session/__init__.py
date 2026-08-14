"""F13: event-sourced session log.

A ``Session`` is an append-only, immutable event log from which the
model-visible message history is projected. Only *surface* events
(``user/message``, ``assistant/message``, ``tool/result``) contribute to the
projection; every other event is trace data. ``SessionStore`` is the live
registry exposed as the ``ctx.sessions`` service.
"""

from .log import (
    SURFACE_ASSISTANT_MESSAGE,
    SURFACE_TOOL_RESULT,
    SURFACE_USER_MESSAGE,
    Session,
    SessionEvent,
    stringify,
)
from .store import SessionNotFound, SessionStore

__all__ = [
    "SURFACE_USER_MESSAGE",
    "SURFACE_ASSISTANT_MESSAGE",
    "SURFACE_TOOL_RESULT",
    "Session",
    "SessionEvent",
    "SessionStore",
    "SessionNotFound",
    "stringify",
]
