"""F8: hot module reload (HMR).

Two pieces compose to reload a running plugin without restarting the app:

- :class:`Reloader` — the core swap with rollback. A reload loads a fresh
  version of a unit, stops the running one, and starts the new one. Any
  failure (load *or* start) keeps the previous version alive and records the
  reason in ``errors``, so a bad edit never takes the app down (F8.2).
- :class:`FileWatcher` — a ``watchdog``-based file watcher. Any change on the
  watched paths triggers the ``on_change`` callback, e.g. re-loading a config
  file or calling ``reloader.reload()`` (F8.1). watchdog is an optional
  dependency; the module imports without it (the watcher then refuses to
  start).

:class:`PluginReloader` binds the two ideas for the common case: a plugin is
an already-imported Python module, ``load`` re-executes it in place, and
activate/deactivate register/unregister its hooks.
"""

from __future__ import annotations

from typing import Any, Callable

try:  # watchdog is an optional extra (`pip install python-cordis[hmr]`)
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
    _WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover  (imported only when optional dep missing)
    FileSystemEventHandler = None  # type: ignore[assignment, misc]
    Observer = None  # type: ignore[assignment]
    _WATCHDOG_AVAILABLE = False

__all__ = ["Reloader", "PluginReloader", "FileWatcher", "ReloadError"]


class ReloadError(RuntimeError):
    """A reload attempt failed. ``reason`` carries the recorded cause."""

    def __init__(self, stage: str, exc: BaseException) -> None:
        self.stage = stage  # "load" / "activate" / "rollback-cleanup" / "rollback-restore"
        self.cause = exc
        super().__init__(f"reload failed at {stage}: {exc}")


class Reloader:
    """Swap a running unit for a fresh one, keeping the old version on failure.

    The unit is described by three callables:

    - ``load``: return a freshly loaded version (may raise).
    - ``activate(unit)``: bring a unit into service (may raise).
    - ``deactivate(unit)``: take a unit out of service.

    ``reload()`` follows "stop old, then start new" (cordis HMR semantics):
    it deactivates the running unit before activating the replacement. If the
    new version fails to load, the old one is left untouched; if it fails to
    start, the partial unit is cleaned up and the old one is restarted.
    """

    def __init__(
        self,
        *,
        load: Callable[[], Any],
        activate: Callable[[Any], Any],
        deactivate: Callable[[Any], None],
        on_error: Callable[[ReloadError], None] | None = None,
    ) -> None:
        self._load = load
        self._activate = activate
        self._deactivate = deactivate
        self._on_error = on_error
        self.errors: list[ReloadError] = []  # recorded failure reasons (F8.2)
        self._current: Any = None
        self._has_current = False

    @property
    def current(self) -> Any:
        """The unit currently in service (``None`` until the first reload)."""
        return self._current

    def reload(self) -> bool:
        """Reload the unit; return False (keeping the old version) on failure."""
        try:
            new = self._load()
        except Exception as exc:  # noqa: BLE001  (any failure is recorded)
            self._record(ReloadError("load", exc))
            return False

        if self._has_current:
            self._deactivate(self._current)  # 先停旧
        try:
            self._activate(new)  # 后启新
        except Exception as exc:  # noqa: BLE001
            # rollback: clean up the partial unit, restore the previous version
            try:
                self._deactivate(new)
            except Exception as cleanup_exc:  # noqa: BLE001
                self._record(ReloadError("rollback-cleanup", cleanup_exc))
            if self._has_current:
                try:
                    self._activate(self._current)
                except Exception as restore_exc:  # noqa: BLE001
                    self._record(ReloadError("rollback-restore", restore_exc))
            self._record(ReloadError("activate", exc))
            return False

        self._current = new
        self._has_current = True
        return True

    def _record(self, error: ReloadError) -> None:
        self.errors.append(error)
        if self._on_error is not None:
            self._on_error(error)


class PluginReloader(Reloader):
    """A :class:`Reloader` whose unit is an already-imported Python plugin module.

    ``load`` re-executes the module in place via :func:`_exec_reload` (so the
    same module object carries the new code); ``activate``/``deactivate``
    register/unregister the module's hooks on the given :class:`HookRegistry`.
    The module must already be imported (and typically registered) before the
    reloader is created; it becomes the initial running version.
    """

    def __init__(
        self,
        module: Any,
        hooks: Any,
        on_error: Callable[[ReloadError], None] | None = None,
    ) -> None:
        self._module = module
        self._hooks = hooks
        super().__init__(
            load=lambda: _exec_reload(self._module),
            activate=lambda unit: self._hooks.register(unit),
            deactivate=lambda unit: self._hooks.unregister(unit),
            on_error=on_error,
        )
        self._current = module
        self._has_current = True


def _exec_reload(module: Any) -> Any:
    """Re-execute a module's source file in place and return the module.

    Two things make ``importlib.reload`` unsuitable here: it re-discovers the
    module through the import system (which cannot find modules loaded via
    ``spec_from_file_location``), and it trusts the ``__pycache__`` bytecode
    cache, whose timestamp/size validation can serve stale code when a quick
    edit keeps the same size and mtime — exactly the HMR case. Instead, read
    the source file directly and exec it against the existing namespace.
    """
    spec = getattr(module, "__spec__", None)
    loader = getattr(spec, "loader", None) if spec is not None else None
    if loader is None or not hasattr(loader, "get_filename") or not hasattr(
        loader, "source_to_code"
    ):
        name = getattr(module, "__name__", "?")
        raise ImportError(f"module {name!r} has no reloadable source loader")
    path = loader.get_filename(module.__name__)
    with open(path, "rb") as fh:
        source = fh.read()
    code = loader.source_to_code(source, path)
    exec(code, module.__dict__)
    return module


class FileWatcher:
    """Watch a set of paths and invoke ``on_change`` for every file event.

    Uses ``watchdog`` (optional extra). ``start()``/``stop()`` manage the
    observer thread; the class also supports context-manager usage. If watchdog
    is not installed, ``start()`` raises a clear error.
    """

    def __init__(
        self,
        paths: list[str],
        on_change: Callable[[Any], None],
        *,
        recursive: bool = True,
    ) -> None:
        self.paths = list(paths)
        self.on_change = on_change
        self.recursive = recursive
        self._observer: Any = None

    def start(self) -> "FileWatcher":
        if not _WATCHDOG_AVAILABLE:
            raise ImportError(
                "FileWatcher requires the optional 'watchdog' dependency; "
                "install it with `pip install python-cordis[hmr]`"
            )
        if self._observer is not None:
            return self  # idempotent
        self._observer = Observer()

        class _Handler(FileSystemEventHandler):
            def __init__(self, owner: FileWatcher) -> None:
                self._owner = owner

            def on_any_event(self, event: Any) -> None:
                if not event.is_directory:
                    self._owner.on_change(event)

        for path in self.paths:
            self._observer.schedule(_Handler(self), path, recursive=self.recursive)
        self._observer.start()
        return self

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join()
        self._observer = None

    def __enter__(self) -> "FileWatcher":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
