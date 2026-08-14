"""F14.2: JSONL persistence provider.

Each session is one ``<dir>/<session_id>.jsonl`` file: a header line followed
by one JSON object per event. Every write goes through a temp file + atomic
``os.replace`` (``_atomic_write``), so a crash can never leave a partially
written file; on read, a trailing partial line (torn tail from a concurrent
writer) is tolerated and skipped.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from ..session import SessionEvent
from .base import SessionPersistence

__all__ = ["JsonlSessionPersistence"]

_HEADER = {"format": "python-cordis-session-v1"}


class JsonlSessionPersistence(SessionPersistence):
    """Append-only per-session JSONL files with atomic publish."""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, session_id: str) -> Path:
        return self.directory / f"{session_id}.jsonl"

    def create(self, session_id: str) -> None:
        path = self._path(session_id)
        if path.exists():
            return
        self._atomic_write(path, [json.dumps(_HEADER)])

    def append(self, session_id: str, event: SessionEvent) -> None:
        with self._lock:
            path = self._path(session_id)
            if not path.exists():
                self.create(session_id)
            lines = self._read_lines(path)
            lines.append(json.dumps(event.to_dict(), ensure_ascii=False))
            self._atomic_write(path, lines)

    def load(self, session_id: str) -> list[SessionEvent]:
        path = self._path(session_id)
        if not path.exists():
            return []
        events: list[SessionEvent] = []
        for line in self._read_lines(path):
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue  # torn tail: skip the partial trailing line
            if not isinstance(raw, dict) or "seq" not in raw:
                continue  # header line
            events.append(SessionEvent.from_dict(raw))
        events.sort(key=lambda e: e.seq)
        return events

    def inspect(self, session_id: str) -> dict[str, Any]:
        events = self.load(session_id)
        if not events:
            return {"session_id": session_id, "count": 0}
        return {
            "session_id": session_id,
            "count": len(events),
            "first": events[0].time,
            "last": events[-1].time,
        }

    def list_sessions(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.jsonl"))

    # ---- internals ----

    def _read_lines(self, path: Path) -> list[str]:
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines()

    def _atomic_write(self, path: Path, lines: list[str]) -> None:
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
