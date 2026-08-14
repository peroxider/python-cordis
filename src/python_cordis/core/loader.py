"""Declarative component loader (paper §4.2).

A :class:`Loader` binds a config tree of entries to fibers on a context and
implements the paper's three loading capabilities:

- **Declarative config layer** — an entry is a dict (or OmegaConf ``DictConfig``)
  carrying a module reference (or a ready component object), config data, and
  optional isolation/annotation flags.
- **Incremental reconciliation** — ``reconcile`` diffs entries by id and
  applies the minimal destructive operations: start new entries, dispose
  removed ones, reload only those whose config changed.
- **Hot module replacement** — ``hot_reload`` re-executes an entry's module in
  place, destroys the old fiber and instantiates a new one, and rolls back to
  the previous component on any failure (the paper's transactional reload).

Entries are deliberately business-agnostic: they reference components that
declare ``inject`` + ``apply``, so the loader works for any plugin tree.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from .hmr import _exec_reload

if TYPE_CHECKING:
    from .context import Context
    from .fiber import Fiber
    from .hook import HookRegistry

__all__ = ["Loader", "LoaderError"]


class LoaderError(RuntimeError):
    """A loader operation failed (resolution, activation, or reload)."""

    def __init__(self, reason: str, cause: BaseException | None = None) -> None:
        self.cause = cause
        super().__init__(reason if cause is None else f"{reason}: {cause}")


def _entry_id(entry: Mapping[str, Any]) -> str:
    eid = entry.get("id")
    if eid:
        return str(eid)
    module = entry.get("module")
    if module:
        return str(module)
    comp = entry.get("component")
    name = getattr(comp, "name", None)
    if name:
        return str(name)
    return repr(comp)


def _source(entry: Mapping[str, Any]) -> tuple[str, Any]:
    """Identity of an entry's component source: the object or the module path.

    Used by :meth:`Loader.reconcile` to detect when the same entry id now
    refers to a different component (a reload, as opposed to a config change).
    """
    comp = entry.get("component")
    if comp is not None:
        return ("component", comp)
    module = entry.get("module")
    if module:
        return ("module", str(module))
    return ("component", None)


def _resolve_component(entry: Mapping[str, Any]) -> Any:
    """Resolve an entry to a component object (declares ``inject`` + ``apply``).

    An entry carries either a ready ``component`` object or a ``module`` import
    path; a module is a component when it has an ``apply``, or it may export a
    ``plugin`` / ``component`` attribute.
    """
    comp = entry.get("component")
    if comp is not None:
        return comp
    module_path = entry.get("module")
    if not module_path:
        raise LoaderError(f"entry {entry!r} needs a 'module' or 'component'")
    module = importlib.import_module(str(module_path))
    comp = getattr(module, "plugin", None) or getattr(module, "component", None)
    if comp is None and hasattr(module, "apply"):
        comp = module
    if comp is None:
        raise LoaderError(
            f"module {module_path!r} exposes no component "
            "(expected 'plugin'/'component' attribute or an 'apply' function)"
        )
    return comp


class Loader:
    """Instantiates, reconciles, and hot-reloads component entries on a context."""

    def __init__(
        self, ctx: "Context", *, hooks: "HookRegistry | None" = None
    ) -> None:
        self.ctx = ctx
        self.hooks = hooks
        self._entries: dict[str, Mapping[str, Any]] = {}
        self._fibers: dict[str, "Fiber"] = {}
        self._sources: dict[str, tuple[str, Any]] = {}
        self.errors: list[LoaderError] = []  # recorded failure reasons (paper §4.2)

    # ---- lifecycle ----

    def start(self, config: Iterable[Mapping[str, Any]]) -> list["Fiber"]:
        """Instantiate one fiber per entry; returns the fibers in entry order."""
        for entry in config:
            self._instantiate(entry)
        return list(self._fibers.values())

    def stop(self) -> "Loader":
        """Dispose every fiber and clear the entry table. Idempotent."""
        for fiber in list(self._fibers.values()):
            fiber.dispose()
        self._fibers.clear()
        self._entries.clear()
        self._sources.clear()
        return self

    def fibers(self) -> dict[str, "Fiber"]:
        """The live fibers, keyed by entry id (copied)."""
        return dict(self._fibers)

    # ---- instantiation ----

    def _instantiate(self, entry: Mapping[str, Any]) -> "Fiber":
        eid = _entry_id(entry)
        normalized = dict(entry)
        if eid in self._fibers:  # 同 id 重复：按新配置重建
            self._fibers.pop(eid).dispose()
        component = _resolve_component(normalized)
        host = self.ctx.isolate() if normalized.get("isolate") else self.ctx
        fiber = host.use(
            component, config=normalized.get("config"), hooks=self.hooks
        )
        self._entries[eid] = normalized
        self._fibers[eid] = fiber
        self._sources[eid] = _source(normalized)
        return fiber

    # ---- incremental reconciliation (paper §4.2) ----

    def reconcile(self, config: Iterable[Mapping[str, Any]]) -> list["Fiber"]:
        """Diff the entry tree against the running one; minimal operations.

        Removed entries are disposed, new entries are started, and only
        entries whose config or source changed are reloaded — untouched
        entries keep their running state.
        """
        normalized = {_entry_id(e): dict(e) for e in config}
        for eid in list(self._fibers):
            if eid not in normalized:
                self._fibers.pop(eid).dispose()
                self._entries.pop(eid, None)
                self._sources.pop(eid, None)
        for eid, entry in normalized.items():
            fiber = self._fibers.get(eid)
            if fiber is None:
                self._instantiate(entry)
            elif (
                fiber.config != entry.get("config")
                or self._sources.get(eid) != _source(entry)
            ):
                self._fibers.pop(eid).dispose()
                self._instantiate(entry)
        return list(self._fibers.values())

    # ---- hot module replacement (paper §4.2) ----

    def hot_reload(self, entry_id: str) -> bool:
        """Transactionally reload an entry's module; roll back on failure.

        Follows the paper's transactional reload: back up the running version,
        destroy the old fiber, load the fresh module and instantiate the new
        fiber, and — on any load or activation failure — restore the previous
        component. Returns ``False`` (previous version kept) on failure.
        """
        entry = self._entries.get(entry_id)
        if entry is None or entry_id not in self._fibers:
            self._record(LoaderError(f"entry {entry_id!r} is not loaded"))
            return False
        module_path = entry.get("module")
        if not module_path or entry.get("component") is not None:
            self._record(
                LoaderError(f"entry {entry_id!r} has no reloadable module")
            )
            return False

        old_component = self._fibers[entry_id].component
        self._fibers.pop(entry_id).dispose()  # 销毁旧 fiber
        try:
            module = importlib.import_module(str(module_path))
            _exec_reload(module)  # 原地重执行，取得新代码
            self._instantiate(entry)  # 用新组件实例化新 fiber
        except Exception as exc:  # noqa: BLE001  (any failure is recorded)
            try:  # 回滚：恢复旧组件
                self._instantiate({**entry, "component": old_component})
            except Exception as restore_exc:  # noqa: BLE001
                self._record(
                    LoaderError(f"rollback of {entry_id!r} failed", restore_exc)
                )
            self._record(LoaderError(f"hot reload of {entry_id!r} failed", exc))
            return False
        return True

    def _record(self, error: LoaderError) -> None:
        self.errors.append(error)
