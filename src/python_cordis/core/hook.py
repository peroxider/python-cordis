"""F1: thin wrapper over pluggy providing the four cordis-style hook modes.

- ``emit``:      every listener is invoked, all results are returned.
- ``parallel``:  every listener is invoked concurrently (thread pool).
- ``bail``:      the first non-``None`` listener result short-circuits
                 (requires the hookspec to declare ``firstresult=True``).
- ``waterfall``: chain-of-command delegation. Each listener receives a
                 ``next`` callable; not calling ``next`` vetoes the chain.

The marker objects are re-exported so plugins write:

    from python_cordis.core.hook import hookspec, hookimpl

    @hookspec
    def on_event(name, next): ...

    @hookimpl
    def on_event(name, next):
        return next()
"""

from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from pluggy import HookimplMarker, HookspecMarker, PluginManager

hookspec = HookspecMarker("python_cordis")
hookimpl = HookimplMarker("python_cordis")

__all__ = ["HookRegistry", "hookspec", "hookimpl", "HookError"]


class HookError(RuntimeError):
    """Raised when a hook call cannot be performed."""


def _filter_kwargs(fn: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Keep only the keyword arguments the target function accepts."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return kwargs
    return {k: v for k, v in kwargs.items() if k in params}


class HookRegistry:
    """A pluggy ``PluginManager`` with the four cordis hook invocation modes.

    The hook name used in ``emit`` / ``parallel`` / ``bail`` / ``waterfall``
    must match a registered ``@hookspec`` hook (pluggy names hooks by their
    function name, so use ``snake_case`` names like ``tools_pre_execute``).
    """

    def __init__(self, project_name: str = "python_cordis") -> None:
        self.pm = PluginManager(project_name)
        self._plugins: list[Any] = []

    # ---- registration & discovery ----

    def add_spec(self, specmodule: Any) -> None:
        """Register all ``@hookspec`` hooks declared on ``specmodule``.

        Re-registering a spec module whose hooks are already registered is a
        no-op, matching :meth:`register`'s idempotency.
        """
        names = [
            name
            for name, obj in vars(specmodule).items()
            if callable(obj) and hasattr(obj, "python_cordis_spec")
        ]
        if names and all(hasattr(self.pm.hook, n) for n in names):
            return
        self.pm.add_hookspecs(specmodule)

    def register(self, plugin: Any) -> Callable[[], None]:
        """Register a plugin (module or object); returns an idempotent disposer.

        Re-registering the same plugin is a no-op (no duplicate hooks).
        """
        if plugin in self._plugins:
            return lambda: None
        self.pm.register(plugin)
        self._plugins.append(plugin)

        def dispose() -> None:
            if plugin in self._plugins:
                self._plugins.remove(plugin)
                self.pm.unregister(plugin)

        return dispose

    def unregister(self, plugin: Any) -> None:
        """Unregister a plugin; its hooks stop firing immediately."""
        if plugin in self._plugins:
            self._plugins.remove(plugin)
            self.pm.unregister(plugin)

    def load_entry_points(self, group: str = "python_cordis.plugins") -> int:
        """Discover plugins via setuptools entry points; returns how many loaded.

        Implemented on ``importlib.metadata`` rather than pluggy's built-in
        helper so every discovered plugin goes through :meth:`register` — the
        plugin list stays accurate and the loaded plugins stay removable.
        """
        from importlib.metadata import entry_points

        count = 0
        for ep in entry_points(group=group):
            self.register(ep.load())
            count += 1
        return count

    def plugins(self) -> list[Any]:
        return list(self._plugins)

    # ---- hook invocation modes ----

    def _ordered(self, caller: Any) -> list[Callable[..., Any]]:
        """Listener functions in execution order (last registered runs first)."""
        return [impl.function for impl in reversed(caller.get_hookimpls())]

    def emit(self, hook: str, **kwargs: Any) -> list[Any]:
        """Invoke every listener; return all results in execution order.

        Broadcast semantics: every listener always runs. A listener that
        accepts a ``next`` argument receives a no-op returning ``None``.
        """
        caller = getattr(self.pm.hook, hook)
        noop = lambda: None  # noqa: E731
        return [fn(**_filter_kwargs(fn, {**kwargs, "next": noop})) for fn in self._ordered(caller)]

    def parallel(self, hook: str, **kwargs: Any) -> list[Any]:
        """Invoke every listener concurrently; return results in execution order."""
        caller = getattr(self.pm.hook, hook)
        funcs = self._ordered(caller)
        noop = lambda: None  # noqa: E731
        with ThreadPoolExecutor(max_workers=max(1, len(funcs))) as pool:
            futures = [
                pool.submit(fn, **_filter_kwargs(fn, {**kwargs, "next": noop}))
                for fn in funcs
            ]
            return [f.result() for f in futures]

    def bail(self, hook: str, **kwargs: Any) -> Any:
        """First non-``None`` listener result wins (needs ``firstresult=True``)."""
        caller = getattr(self.pm.hook, hook)
        spec = getattr(caller, "spec", None)
        if spec is None or not spec.opts.get("firstresult"):
            raise HookError(
                f"hook {hook!r} is not declared with firstresult=True; "
                "add it to the @hookspec to enable bail mode"
            )
        return caller(**kwargs)

    def waterfall(
        self,
        hook: str,
        *,
        _tail: Callable[[], Any] | None = None,
        _initial: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Chain-of-command delegation over the registered listeners.

        Each listener receives a ``next`` callable (plus the keyword args it
        accepts). Calling ``next()`` delegates to the following listener and
        finally to ``_tail`` (if given); returning without calling ``next``
        vetoes the chain and becomes the result.
        """
        caller = getattr(self.pm.hook, hook)
        funcs = self._ordered(caller)

        def chain(idx: int, value: Any) -> Any:
            if idx >= len(funcs):
                return _tail() if _tail is not None else value
            fn = funcs[idx]
            local = dict(kwargs)
            local["value"] = value
            local["next"] = lambda: chain(idx + 1, value)
            return fn(**_filter_kwargs(fn, local))

        return chain(0, _initial)
