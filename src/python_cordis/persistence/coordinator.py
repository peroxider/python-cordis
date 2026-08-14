"""F14.4: the write-path coordinator.

``PersistenceCoordinator`` sits between the app layer and a
:class:`SessionPersistence` backend. Appends to the wrapped
:class:`~python_cordis.session.Session` are buffered for a fixed delay window
and flushed together; ``flush()`` is an explicit barrier that guarantees the
store is complete before it returns. Writes for the wrapped session are
serialized by an internal lock, and the backend is swappable without touching
the read/write callers.
"""

from __future__ import annotations

import threading
from typing import Any, Mapping, Sequence

from ..session import Session
from .base import SessionPersistence

__all__ = ["PersistenceCoordinator"]


class PersistenceCoordinator:
    """Batch-persists a session's events through a backend."""

    def __init__(
        self,
        backend: SessionPersistence,
        session: Session,
        *,
        delay: float = 0.05,
    ) -> None:
        self.backend = backend
        self.session = session
        self._delay = delay
        self._pending: list[int] = []
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def append(
        self,
        type_: str,
        data: Mapping[str, Any],
        *,
        surface_op: str | None = None,
        source_seqs: Sequence[int] = (),
    ) -> int:
        """Append to the in-memory session and schedule a delayed flush."""
        seq = self.session.append(
            type_, data, surface_op=surface_op, source_seqs=source_seqs
        )
        with self._lock:
            self._pending.append(seq)
            if self._timer is None:
                self._timer = threading.Timer(self._delay, self.flush)
                self._timer.daemon = True
                self._timer.start()
        return seq

    def flush(self) -> None:
        """Write all buffered events to the backend now.

        Idempotent and thread-safe; safe to call while a delayed flush timer
        is pending. After ``flush()`` returns, ``backend.load`` is complete.
        """
        with self._lock:
            if not self._pending:
                return
            seqs = list(self._pending)
            self._pending = []
            timer = self._timer
            self._timer = None
        if timer is not None:
            timer.cancel()
        self.backend.create(self.session.session_id)
        for seq in seqs:
            self.backend.append(self.session.session_id, self.session.get(seq))

    def close(self) -> None:
        """Flush any remaining events and stop the delayed timer."""
        self.flush()
