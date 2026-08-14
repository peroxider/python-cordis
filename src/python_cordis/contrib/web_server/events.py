"""F16.3: the thread-safe event bus.

The kernel is synchronous; the WebSocket downlink is async on its own event
loop thread. ``EventBus`` is the bridge: subscribers run on whatever thread
publishes, and the WS service wraps the callback to marshal events onto the
async loop. All state is guarded by a re-entrant lock so a publisher on any
thread may ``publish`` concurrently.

Subscription granularity (Q9) is dual-mode: subscribe to one session by id, or
to the global stream (``None``) to see every session's appends. ``attach`` /
``attach_store`` wire the bus to sessions so appends flow from the kernel into
the bus without the kernel knowing a bus exists.
"""

from __future__ import annotations

import threading
from typing import Callable

from ...session import Session, SessionEvent, SessionStore

__all__ = ["EventBus", "EventListener"]

EventListener = Callable[[str, SessionEvent], None]


class EventBus:
    """Thread-safe broadcaster of :class:`SessionEvent` records."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscriptions: list[tuple[str | None, EventListener]] = []
        self._attached: dict[str, Callable[[], None]] = {}

    # ---- attachment (kernel → bus wiring) ----

    def attach(self, session: Session) -> None:
        """Broadcast ``session``'s appends (idempotent per session).

        Subscribes to the session's own listener list so every append —
        including those written directly on the :class:`Session` object, not
        through the store — reaches the bus.
        """
        sid = session.session_id
        with self._lock:
            if sid in self._attached:
                return

            def _relay(ev: SessionEvent) -> None:
                self.publish(sid, ev)

            disposer = session.subscribe(_relay)
            self._attached[sid] = disposer

    def detach(self, session_id: str) -> None:
        """Stop broadcasting one session's appends (idempotent)."""
        with self._lock:
            disposer = self._attached.pop(session_id, None)
        if disposer is not None:
            disposer()

    def attach_store(self, store: SessionStore) -> Callable[[], None]:
        """Attach every live session and follow future create / dispose.

        Returns a disposer that unsubscribes the store and detaches every
        attached session (used as a reversible effect by the transport plugin).
        """
        for sid in store.list():
            self.attach(store.get(sid))
        store_disposer = store.subscribe(self._on_store_lifecycle)

        def dispose() -> None:
            store_disposer()
            with self._lock:
                attached = list(self._attached)
            for sid in attached:
                self.detach(sid)

        return dispose

    def _on_store_lifecycle(self, session_id: str, session: "Session | None") -> None:
        if session is None:
            self.detach(session_id)
        else:
            self.attach(session)

    # ---- subscription ----

    def subscribe(self, session_id: str | None, listener: EventListener) -> Callable[[], None]:
        """Register ``listener`` for one session, or the global stream (``None``).

        Returns a disposer that removes the listener (idempotent).
        """
        with self._lock:
            self._subscriptions.append((session_id, listener))

        def dispose() -> None:
            with self._lock:
                if (session_id, listener) in self._subscriptions:
                    self._subscriptions.remove((session_id, listener))

        return dispose

    def publish(self, session_id: str, event: SessionEvent) -> None:
        """Deliver ``event`` to the global stream and the session's subscribers."""
        with self._lock:
            targets = [
                (sid, cb)
                for (sid, cb) in self._subscriptions
                if sid is None or sid == session_id
            ]
        for _, cb in targets:
            cb(session_id, event)

    # ---- introspection (for tests / diagnostics) ----

    def subscriber_count(self) -> int:
        """Number of active subscriptions."""
        with self._lock:
            return len(self._subscriptions)

    def attached_count(self) -> int:
        """Number of attached sessions."""
        with self._lock:
            return len(self._attached)
