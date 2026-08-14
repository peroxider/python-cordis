"""F14.3: SQLite persistence provider.

Standard-library ``sqlite3`` implementation: a ``sessions`` table plus an
``events`` table, each batch written inside a transaction, with
``journal_mode=WAL``. Loads and restores the exact same event sequence as the
JSONL provider, so the two backends are interchangeable.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any

from ..session import SessionEvent
from .base import SessionPersistence

__all__ = ["SqliteSessionPersistence"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    time REAL NOT NULL,
    data TEXT NOT NULL,
    surface_op TEXT,
    source_seqs TEXT,
    PRIMARY KEY (session_id, seq)
);
"""


class SqliteSessionPersistence(SessionPersistence):
    """SQLite-backed persistence for session event logs."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self._db = path if path is not None else ":memory:"
        self._conn = sqlite3.connect(self._db)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def create(self, session_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO sessions (id, created_at) VALUES (?, ?)",
            (session_id, time.time()),
        )
        self._conn.commit()

    def append(self, session_id: str, event: SessionEvent) -> None:
        self.create(session_id)
        self._conn.execute(
            "INSERT OR REPLACE INTO events "
            "(session_id, seq, type, time, data, surface_op, source_seqs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                event.seq,
                event.type,
                event.time,
                json.dumps(event.data, ensure_ascii=False),
                event.surface_op,
                json.dumps(list(event.source_seqs)),
            ),
        )
        self._conn.commit()

    def load(self, session_id: str) -> list[SessionEvent]:
        rows = self._conn.execute(
            "SELECT type, seq, time, data, surface_op, source_seqs "
            "FROM events WHERE session_id = ? ORDER BY seq",
            (session_id,),
        ).fetchall()
        return [
            SessionEvent(
                type=row["type"],
                seq=row["seq"],
                time=row["time"],
                data=json.loads(row["data"]),
                surface_op=row["surface_op"],
                source_seqs=tuple(json.loads(row["source_seqs"] or "[]")),
            )
            for row in rows
        ]

    def inspect(self, session_id: str) -> dict[str, Any]:
        events = self.load(session_id)
        return {"session_id": session_id, "count": len(events)}

    def list_sessions(self) -> list[str]:
        rows = self._conn.execute("SELECT id FROM sessions ORDER BY id").fetchall()
        return [row["id"] for row in rows]

    def close(self) -> None:
        """Close the underlying connection (not part of the interface)."""
        self._conn.close()
