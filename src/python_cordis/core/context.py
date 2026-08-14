"""F2: the reflective service container (cordis ``Context`` analog).

A ``Context`` is a repository of services. Attribute access (``ctx.fs``)
resolves through ``__getattr__`` along the parent chain; ``register`` returns
a reversible disposer; ``extend``/``isolate`` create scoped children.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

T = TypeVar("T")

__all__ = ["Context", "inject", "ServiceNotFound"]


class ServiceNotFound(AttributeError):
    """Raised when a service name is not resolvable on the context chain."""


class Context:
    """A service repository with parent-chain lookup and scoped children.

    Services are plain attribute names (e.g. ``ctx.fs``, ``ctx.tools``).
    """

    def __init__(self, parent: "Context | None" = None, *, isolate: bool = False) -> None:
        # Public by design; guarded because __getattr__ is only reached when
        # normal attribute lookup fails, and these names must resolve.
        self._services: dict[str, Any] = {}
        self._parent = parent
        self._isolate = isolate
        self._effects: list[Callable[[], None]] = []

    # ---- reflection ----

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._services:
            return self._services[name]
        if self._parent is not None and not self._isolate:
            try:
                return getattr(self._parent, name)
            except AttributeError:
                pass
        raise ServiceNotFound(
            f"service {name!r} is not registered"
            + (f" (or its parents)" if self._parent is not None else "")
        )

    # ---- registration (reversible) ----

    def register(self, name: str, impl: Any) -> Callable[[], None]:
        """Register ``impl`` under ``name``; returns an idempotent disposer.

        A later registration of the same name shadows an earlier one; the
        disposer restores the previous value (or removes the name).
        """
        previous = self._services.get(name)
        self._services[name] = impl

        def dispose() -> None:
            if self._services.get(name) is impl:
                if previous is not None:
                    self._services[name] = previous
                else:
                    self._services.pop(name, None)

        self._effects.append(dispose)
        return dispose

    # ---- scopes ----

    def extend(self) -> "Context":
        """A child context sharing the parent's services without mutating them.

        Registrations on the child are invisible to the parent.
        """
        return Context(parent=self, isolate=False)

    def isolate(self) -> "Context":
        """A sealed child context: parent services are invisible, and nothing
        registered inside leaks back to the parent (cordis isolate realm)."""
        return Context(parent=self, isolate=True)

    # ---- effects (reversible side effects, cordis ctx.effect) ----

    def effect(self, fn: Callable[[], None]) -> Callable[[], None]:
        """Register a teardown callback, run in reverse order at teardown."""
        self._effects.append(fn)
        return fn

    def _teardown(self) -> None:
        """Run all recorded effects in reverse registration order.

        A failing effect does not block the others. Effects are cleared after
        teardown so a stopped context can be reused.
        """
        while self._effects:
            fn = self._effects.pop()
            try:
                fn()
            except Exception:
                # A single failure must not prevent the remaining teardowns.
                continue

    # ---- dependency injection (lazy) ----

    def get(self, name: str) -> Any:
        """Resolve a service, raising :class:`ServiceNotFound` when absent."""
        return getattr(self, name)


def inject(*names: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Declare lazy service dependencies for a callable.

    The callable receives the resolved services as keyword arguments
    (``**names``) on top of any explicit arguments. Dependencies are resolved
    only when the wrapped callable is invoked, not at decoration time.

        @inject("fs")
        def save(fs, path, content): ...
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        def wrapper(ctx: Context, *args: Any, **kwargs: Any) -> T:
            for name in names:
                try:
                    kwargs[name] = getattr(ctx, name)
                except ServiceNotFound as exc:
                    raise ServiceNotFound(
                        f"dependency {name!r} required by {fn.__name__!r} "
                        f"is not registered"
                    ) from exc
            return fn(*args, **kwargs)

        wrapper.__name__ = fn.__name__
        return wrapper

    return decorator
