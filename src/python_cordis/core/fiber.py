"""F3: plugin instance lifecycle (cordis ``Fiber`` analog).

A ``Fiber`` wraps a ``Context`` and owns its lifecycle: ``start()`` marks the
plugin active, ``stop()`` tears down every effect recorded on the context in
reverse registration order. Repeating ``start``/``stop`` is idempotent.

When constructed with a ``HookRegistry`` that has the lifecycle specs
registered (see :mod:`python_cordis.observability`), ``start``/``stop`` also
emit the ``fiber_started`` / ``fiber_stopped`` hooks so observability can be
added as a plain, reversible plugin — never a privileged core requirement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import Context
    from .hook import HookRegistry

__all__ = ["Fiber"]


class Fiber:
    """Lifecycle handle for one plugin instance bound to a context."""

    def __init__(
        self, ctx: "Context", *, hooks: "HookRegistry | None" = None
    ) -> None:
        self.ctx = ctx
        self._hooks = hooks
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def start(self) -> "Fiber":
        """Mark the plugin active. Idempotent."""
        self._active = True
        self._try_emit("fiber_started")
        return self

    def stop(self) -> "Fiber":
        """Tear down all recorded effects in reverse order. Idempotent.

        Teardown runs whether or not ``start()`` was called; a second ``stop``
        is a no-op because ``_teardown`` drains the recorded effects once.
        """
        self.ctx._teardown()  # noqa: SLF001  (owned lifecycle boundary)
        self._active = False
        self._try_emit("fiber_stopped")
        return self

    def _try_emit(self, name: str) -> None:
        """Emit a lifecycle hook only if the registry is attached *and* the
        corresponding spec is registered. Otherwise stay silent — lifecycle
        events are opt-in, never a required part of the kernel."""
        if self._hooks is None or not hasattr(self._hooks.pm.hook, name):
            return
        self._hooks.emit(name, fiber=self)

    def __enter__(self) -> "Fiber":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
