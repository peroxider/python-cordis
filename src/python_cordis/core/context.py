"""F2: the reflective service container (cordis ``Context`` analog).

A ``Context`` is a repository of services and a boundary for effects. It
implements the paper's *context paradigm* (§3.4): every mutation is tracked and
reversible, and every dependency change is broadcast to the fibers that declare
it (reactive coeffects, §3.2).

- Attribute access (``ctx.fs``) resolves through ``__getattr__`` along the
  parent chain.
- ``register``/``set`` bind a service and return a reversible, notifying
  disposer; a later registration of the same name shadows an earlier one.
- ``effect`` records a reversible side effect and returns an idempotent
  disposer (paper Algorithm 1's armed guard).
- ``on`` registers a hook listener as a reversible effect (paper ``ctx.on``).
- ``extend``/``isolate`` create scoped children; ``isolate`` is the paper's
  isolation realm.
- ``use`` instantiates a :class:`~python_cordis.Fiber` from a component on a
  child context whose access is restricted to the component's ``inject``
  declaration (the paper's proxy-mediated enforcement: undeclared access
  raises :class:`ServiceNotFound`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AbstractSet, Any, Callable, TypeVar

if TYPE_CHECKING:
    from .fiber import Fiber
    from .hook import HookRegistry

T = TypeVar("T")

__all__ = ["Context", "inject", "ServiceNotFound"]


class ServiceNotFound(AttributeError):
    """Raised when a service name is not resolvable on the context chain."""


class _Effect:
    """One recorded reversible side effect, with its armed/idempotency guard.

    A disposer disarms the entry before running it (paper Algorithm 1: the
    inverse runs at most once); teardown skips already-disarmed entries.
    """

    __slots__ = ("fn", "armed")

    def __init__(self, fn: Callable[[], None]) -> None:
        self.fn = fn
        self.armed = True


class _HookListener:
    """Wrap a function as a pluggy hookimpl under a hook name, for ``ctx.on``.

    pluggy discovers hook implementations by scanning a plugin's attributes
    (``dir(plugin)``) and matching their names to hooks, so the listener must
    be an object carrying an attribute named after the hook.
    """

    def __init__(self, name: str, fn: Callable[..., Any]) -> None:
        from .hook import hookimpl

        self.__dict__[name] = hookimpl(fn)


class Context:
    """A service repository with parent-chain lookup and scoped children.

    Services are plain attribute names (e.g. ``ctx.fs``, ``ctx.tools``).
    A context whose ``declared`` set is not ``None`` restricts environment
    access to those names (a fiber's own view); ``None`` means unrestricted
    (the root or an application context).
    """

    def __init__(
        self,
        parent: "Context | None" = None,
        *,
        isolate: bool = False,
        declared: set[str] | frozenset[str] | None = None,
    ) -> None:
        # Public by design; guarded because __getattr__ is only reached when
        # normal attribute lookup fails, and these names must resolve.
        self._services: dict[str, Any] = {}
        self._parent = parent
        self._isolate = isolate
        self._declared = frozenset(declared) if declared is not None else None
        self._effects: list[_Effect] = []
        self._fibers: list["Fiber"] = []
        self._children: list["Context"] = []
        if parent is not None:
            parent._children.append(self)

    # ---- reflection ----

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._services:
            return self._services[name]
        if self._declared is not None and name not in self._declared:
            raise ServiceNotFound(
                f"dependency {name!r} is not declared in this component's inject spec"
            )
        if self._parent is not None and not self._isolate:
            try:
                return getattr(self._parent, name)
            except AttributeError:
                pass
        raise ServiceNotFound(
            f"service {name!r} is not registered"
            + (f" (or its parents)" if self._parent is not None else "")
        )

    def _has_service(self, name: str) -> bool:
        """Whether ``name`` resolves on this context's chain (dependency check).

        Unlike :meth:`__getattr__`, this ignores the ``declared`` restriction:
        it measures the environment's actual availability for a fiber's
        coeffect satisfaction test, not what the fiber may access.
        """
        if name in self._services:
            return True
        if self._parent is not None and not self._isolate:
            return self._parent._has_service(name)
        return False

    # ---- registration (reversible + notifying) ----

    def register(self, name: str, impl: Any) -> Callable[[], None]:
        """Register ``impl`` under ``name``; returns an idempotent disposer.

        A later registration of the same name shadows an earlier one; the
        disposer restores the previous value (or removes the name). Both the
        binding and the disposal notify dependent fibers, driving the reactive
        coeffect lifecycle (paper §3.2).
        """
        previous = self._services.get(name)
        self._services[name] = impl
        self._notify({name})

        def dispose() -> None:
            if self._services.get(name) is impl:
                if previous is not None:
                    self._services[name] = previous
                else:
                    self._services.pop(name, None)
                self._notify({name})

        self._effects.append(_Effect(dispose))
        return dispose

    def set(self, name: str, value: Any) -> Callable[[], None]:
        """cordis ``ctx.set``: bind ``value`` as a reversible, notifying effect.

        Implemented as :meth:`register` — the mutation is tracked, and the
        disposer restores the previous binding while re-notifying dependents.
        """
        return self.register(name, value)

    # ---- event listening (reversible) ----

    def on(self, hooks: "HookRegistry", name: str, fn: Callable[..., Any]) -> Callable[[], None]:
        """Listen to hook ``name`` on ``hooks``; a reversible effect.

        Registers ``fn`` as a hook implementation and records the unregister
        as a context effect, so the listener stops firing when the owning
        context is torn down (paper ``ctx.on``).
        """
        disposer = hooks.register(_HookListener(name, fn))
        self.effect(disposer)
        return disposer

    # ---- scopes ----

    def extend(self) -> "Context":
        """A child context sharing the parent's services without mutating them.

        Registrations on the child are invisible to the parent.
        """
        return Context(parent=self, isolate=False)

    def isolate(self) -> "Context":
        """A sealed child context: parent services are invisible, and nothing
        registered inside leaks back to the parent (paper isolation realm)."""
        return Context(parent=self, isolate=True)

    # ---- component instantiation (reactive) ----

    def use(self, component: Any, config: Any = None, *, hooks: "HookRegistry | None" = None) -> "Fiber":
        """Instantiate a :class:`~python_cordis.Fiber` from ``component``.

        The component declares ``inject`` (its coeffect spec) and ``apply``
        (its effect function). The fiber gets a child context whose environment
        access is restricted to the declared dependencies, and its activation
        is driven reactively: it activates when every dependency resolves and
        deactivates when one is removed. The fiber is unloaded when this
        context is torn down (paper Algorithm 4).
        """
        from .fiber import Fiber

        declared = getattr(component, "inject", None) or ()
        child = Context(parent=self, isolate=False, declared=set(declared))
        fiber = Fiber(child, component=component, config=config, hooks=hooks)
        self._fibers.append(fiber)

        def dispose_fiber() -> None:
            if fiber in self._fibers:
                self._fibers.remove(fiber)
                fiber.dispose()

        self._effects.append(_Effect(dispose_fiber))
        fiber.refresh()  # 依赖已满足则立即激活，否则等待通知
        return fiber

    # ---- effects (reversible side effects, paper ctx.effect) ----

    def effect(self, fn: Callable[[], None]) -> Callable[[], None]:
        """Register a teardown callback; returns an idempotent disposer.

        Following paper Algorithm 1, the returned disposer is armed: it runs
        the inverse at most once, and a later teardown skips it.
        """
        entry = _Effect(fn)
        self._effects.append(entry)

        def dispose() -> None:
            if not entry.armed:
                return
            entry.armed = False
            if entry in self._effects:
                self._effects.remove(entry)
            fn()

        return dispose

    def _teardown(self) -> None:
        """Run all recorded effects in reverse registration order.

        A failing effect does not block the others. Effects are cleared after
        teardown so a stopped context can be reused.
        """
        while self._effects:
            entry = self._effects.pop()
            if not entry.armed:
                continue
            entry.armed = False
            try:
                entry.fn()
            except Exception:
                # A single failure must not prevent the remaining teardowns.
                continue

    # ---- reactive notification (paper Algorithm 3) ----

    def _notify(self, keys: AbstractSet[str]) -> None:
        """Broadcast a dependency change to every dependent fiber.

        A fiber is notified when one of its declared ``inject`` names changed
        on this context; the change also propagates down to non-isolated child
        contexts (their fibers may resolve the name through this chain).
        """
        for fiber in list(self._fibers):
            if fiber.inject.intersection(keys):
                fiber.refresh()
        for child in list(self._children):
            if not child._isolate:
                child._notify(keys)

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
