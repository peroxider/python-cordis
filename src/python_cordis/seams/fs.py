"""F5: the filesystem capability seam.

A seam is interface + provider + consumer:
- ``FileSystem`` : the Service Definition (stable contract).
- ``LocalFS``    : a Provider operating on the host filesystem (atomic writes,
                   binary rejection on read).
- ``tool_fs``    : a Consumer exposing the seam as a tool, depending only on
                   the ``FileSystem`` interface.

Swapping the provider (e.g. LocalFS -> a future SandboxFS) leaves every
consumer untouched.
"""

from __future__ import annotations

import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

__all__ = [
    "FileSystem",
    "LocalFS",
    "SandboxFS",
    "NotATextFileError",
    "PathEscapeError",
    "tool_fs",
]


class NotATextFileError(ValueError):
    """Raised when reading a file that is not valid UTF-8 text."""


class PathEscapeError(ValueError):
    """Raised when a path resolves outside a sandbox root."""


class FileSystem(ABC):
    """Contract for a text-oriented filesystem capability.

    All paths are relative to the seam's working directory (``cwd``).
    ``read``/``edit_text`` operate on UTF-8 text; binary content is rejected.
    """

    def __init__(self, cwd: str | os.PathLike[str] = ".") -> None:
        self.cwd = Path(cwd)

    def _resolve(self, path: str | os.PathLike[str]) -> Path:
        p = Path(path)
        return p if p.is_absolute() else self.cwd / p

    @abstractmethod
    def read(self, path: str | os.PathLike[str]) -> str:
        """Return the UTF-8 text content of ``path``."""

    @abstractmethod
    def write(self, path: str | os.PathLike[str], content: str) -> None:
        """Atomically write ``content`` to ``path`` (tmp file + rename)."""

    @abstractmethod
    def edit_text(
        self, path: str | os.PathLike[str], old: str, new: str, count: int = 1
    ) -> bool:
        """Replace ``old`` with ``new``; return True if a replacement happened."""

    @abstractmethod
    def stat(self, path: str | os.PathLike[str]) -> dict[str, Any]:
        """Return size and mtime of ``path``."""

    @abstractmethod
    def list(self, path: str | os.PathLike[str] = ".") -> list[str]:
        """Return the names of entries directly under ``path``."""


class LocalFS(FileSystem):
    """Provider operating directly on the host filesystem."""

    def read(self, path: str | os.PathLike[str]) -> str:
        target = self._resolve(path)
        data = target.read_bytes()
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise NotATextFileError(f"not a UTF-8 text file: {target}") from exc

    def write(self, path: str | os.PathLike[str], content: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=target.name + ".", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    def edit_text(
        self, path: str | os.PathLike[str], old: str, new: str, count: int = 1
    ) -> bool:
        content = self.read(path)
        if count > 0:
            replaced = content.replace(old, new, count)
        else:
            replaced = content.replace(old, new)
        if replaced == content:
            return False
        self.write(path, replaced)
        return True

    def stat(self, path: str | os.PathLike[str]) -> dict[str, Any]:
        st = self._resolve(path).stat()
        return {"size": st.st_size, "mtime": st.st_mtime}

    def list(self, path: str | os.PathLike[str] = ".") -> list[str]:
        return sorted(p.name for p in self._resolve(path).iterdir())


class SandboxFS(FileSystem):
    """Provider confining every operation inside a root directory.

    Delegates the actual work to an inner :class:`LocalFS` rooted at the
    sandbox ``root``, but guards every path first: after normalization it must
    resolve to a location inside ``root``. Out-of-bounds paths (``..``
    traversal, absolute paths elsewhere, symlinks out) raise
    :class:`PathEscapeError`, so the sandbox shares the ``FileSystem`` contract
    while never touching the host outside its root.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root).resolve()
        self._fs = LocalFS(cwd=self.root)

    def _guard(self, path: str | os.PathLike[str]) -> Path:
        """Normalize ``path`` and verify it stays inside the sandbox root."""
        candidate = self._fs._resolve(path).resolve()  # noqa: SLF001  (delegated resolver)
        if not candidate.is_relative_to(self.root):
            raise PathEscapeError(
                f"path {str(path)!r} escapes sandbox root {self.root}"
            )
        return candidate

    def read(self, path: str | os.PathLike[str]) -> str:
        return self._fs.read(self._guard(path))

    def write(self, path: str | os.PathLike[str], content: str) -> None:
        self._fs.write(self._guard(path), content)

    def edit_text(
        self, path: str | os.PathLike[str], old: str, new: str, count: int = 1
    ) -> bool:
        return self._fs.edit_text(self._guard(path), old, new, count)

    def stat(self, path: str | os.PathLike[str]) -> dict[str, Any]:
        return self._fs.stat(self._guard(path))

    def list(self, path: str | os.PathLike[str] = ".") -> list[str]:
        return self._fs.list(self._guard(path))


# ---- Consumer ----

def tool_fs(fs: FileSystem) -> dict[str, Any]:
    """Build the ``tool-fs`` consumer: tools over the ``FileSystem`` interface.

    ``tool_fs`` depends only on the interface, never on a concrete provider,
    so the provider can be swapped without touching consumers.
    """
    return {
        "read_file": lambda path: {"content": fs.read(path)},
        "write_file": lambda path, content: fs.write(path, content),
        "edit_file": lambda path, old, new: {
            "changed": fs.edit_text(path, old, new)
        },
        "list_dir": lambda path=".": {"entries": fs.list(path)},
    }
