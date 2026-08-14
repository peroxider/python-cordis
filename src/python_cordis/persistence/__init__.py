"""F14: session persistence backends.

The write path goes through :class:`PersistenceCoordinator`, which batches
appends on a fixed delay window and exposes an explicit ``flush()`` barrier.
Two storage providers implement the same :class:`SessionPersistence` contract,
so the backend is swappable without touching the read/write callers.
"""

from .base import SessionPersistence
from .coordinator import PersistenceCoordinator
from .jsonl import JsonlSessionPersistence
from .sqlite import SqliteSessionPersistence

__all__ = [
    "SessionPersistence",
    "JsonlSessionPersistence",
    "SqliteSessionPersistence",
    "PersistenceCoordinator",
]
