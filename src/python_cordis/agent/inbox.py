"""F12.1: the inbox.

An ``Inbox`` holds messages tagged with a *target* that encodes cadence:
``next-step`` means "handle this in the current turn", ``next-turn`` means
"defer to the next turn". ``send``/``claim`` are the only mutations; the
``has_pending`` property drives loop termination.
"""

from __future__ import annotations

from typing import Any, Mapping

__all__ = ["NEXT_STEP", "NEXT_TURN", "Inbox"]

NEXT_STEP = "next-step"
NEXT_TURN = "next-turn"


class Inbox:
    """Two-queue message box distinguishing loop cadence."""

    def __init__(self) -> None:
        self._queues: dict[str, list[dict[str, Any]]] = {
            NEXT_STEP: [],
            NEXT_TURN: [],
        }

    def send(self, message: Mapping[str, Any], target: str = NEXT_STEP) -> None:
        """Enqueue ``message`` (copied) for ``target``."""
        self._queues[target].append(dict(message))

    def claim(self, target: str) -> dict[str, Any] | None:
        """Dequeue the oldest message for ``target``; ``None`` when empty."""
        queue = self._queues[target]
        return queue.pop(0) if queue else None

    @property
    def has_pending(self) -> bool:
        """True when any target still holds messages."""
        return any(self._queues.values())

    def size(self) -> int:
        """Total number of messages across all targets."""
        return sum(len(q) for q in self._queues.values())
