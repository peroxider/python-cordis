"""F14.1: the persistence Service Definition.

``SessionPersistence`` is the abstract contract for storing session event
logs, independent of the concrete storage (file, sqlite, ...). Providers
implement ``create`` / ``append`` / ``load`` / ``inspect`` / ``list``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..session import SessionEvent

__all__ = ["SessionPersistence"]


class SessionPersistence(ABC):
    """Contract for a durable, append-only session store.

    Events are appended individually but callers may batch (see
    :class:`python_cordis.persistence.PersistenceCoordinator`); ``load``
    returns every persisted event in ``seq`` order for one session.
    """

    @abstractmethod
    def create(self, session_id: str) -> None:
        """Create the storage slot for ``session_id`` (idempotent)."""

    @abstractmethod
    def append(self, session_id: str, event: SessionEvent) -> None:
        """Persist one event for ``session_id`` (append-only)."""

    @abstractmethod
    def load(self, session_id: str) -> list[SessionEvent]:
        """Return all persisted events for ``session_id`` in ``seq`` order."""

    @abstractmethod
    def inspect(self, session_id: str) -> dict[str, Any]:
        """Return metadata about the stored session (count, time bounds)."""

    @abstractmethod
    def list_sessions(self) -> list[str]:
        """Return the ids of all persisted sessions."""
