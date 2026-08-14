"""F3: plugin instance lifecycle (cordis ``Fiber`` analog).

A ``Fiber`` wraps a ``Context`` and owns its lifecycle. It implements the
paper's *component lifecycle* (§3.3): a component is a pair of a coeffect spec
(``inject``) and an effect function (``apply``), and the fiber reconciles
toward a target state — ACTIVE exactly when the effects are applied and every
declared dependency is satisfied, INACTIVE otherwise.

- ``start()``/``stop()`` are the manual, idempotent lifecycle handles.
- ``refresh()`` is the reactive transition (paper's RELOAD/UNLOAD driven by
  dependency changes): it activates when dependencies appear and deactivates
  when they disappear, converging to quiescence. Re-entrant notifications
  during a transition are folded into the next loop pass (the synchronous
  counterpart of the paper's inertial states), and each pass bumps ``epoch`` so
  stale notifications are detectable.
- ``dispose()`` permanently unloads the fiber (paper's UNLOAD + recovery).

When constructed with a ``HookRegistry`` that has the lifecycle specs
registered (see :mod:`python_cordis.observability`), ``start``/``stop`` also
emit the ``fiber_started`` / ``fiber_stopped`` hooks so observability can be
added as a plain, reversible plugin — never a privileged core requirement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context import Context
    from .hook import HookRegistry

__all__ = ["Fiber"]


class Fiber:
    """Lifecycle handle for one component instance bound to a context."""

    def __init__(
        self,
        ctx: "Context",
        *,
        component: Any = None,
        config: Any = None,
        hooks: "HookRegistry | None" = None,
    ) -> None:
        self.ctx = ctx
        self.component = component
        self.config = config
        self.inject = frozenset(
            getattr(component, "inject", ()) if component is not None else ()
        )
        self._hooks = hooks
        self._active = False
        self._applied = False
        self._applying = False
        self._refreshing = False
        self._dirty = False
        self._disposed = False
        self._epoch = 0

    @property
    def active(self) -> bool:
        return self._active

    @property
    def disposed(self) -> bool:
        return self._disposed

    @property
    def epoch(self) -> int:
        """Version counter, bumped on every refresh pass.

        A transition that started with an older epoch is stale (paper §3.3):
        the reactive machinery uses it to drop notifications superseded by a
        newer dependency change.
        """
        return self._epoch

    # ---- manual lifecycle ----

    def start(self) -> "Fiber":
        """Manually activate. Idempotent; applies the component once when
        present. ``refresh()`` may also activate a dependency-satisfied fiber.
        """
        if self._active or self._disposed:
            return self
        self._apply_once()
        self._active = True
        self._try_emit("fiber_started")
        return self

    def stop(self) -> "Fiber":
        """Tear down all recorded effects in reverse order. Idempotent.

        Teardown runs whether or not ``start()`` was called; a second ``stop``
        is a no-op because teardown drains the recorded effects once.
        """
        if self._disposed:
            return self
        self._active = False
        self._applied = False
        self.ctx._teardown()  # noqa: SLF001  (owned lifecycle boundary)
        self._try_emit("fiber_stopped")
        return self

    def dispose(self) -> "Fiber":
        """Permanently unload the fiber: teardown, then mark it dead.

        A disposed fiber can no longer be restarted or refreshed (paper's
        UNLOAD applies the accumulated inverse functions and recovers the
        context). Idempotent.
        """
        if self._disposed:
            return self
        self.stop()
        self._disposed = True
        return self

    # ---- reactive lifecycle (paper §3.2 / §3.3) ----

    def refresh(self) -> None:
        """Reconcile toward the target state; converge to quiescence.

        The target is ACTIVE iff every declared dependency resolves. When a
        transition (apply/teardown) itself changes dependencies, the pass is
        re-run until a fixpoint is reached — the synchronous counterpart of
        the paper's inertial state machine, with each pass bumping ``epoch``.
        """
        if self._disposed:
            return
        if self._refreshing:
            self._dirty = True
            return
        self._refreshing = True
        try:
            while True:
                self._dirty = False
                self._epoch += 1
                epoch = self._epoch
                satisfied = self._deps_satisfied()
                if satisfied and not self._active:
                    self._apply_once()
                    if epoch != self._epoch:  # 转换期间依赖又变化：交下一轮收敛
                        continue
                    self._active = True
                    self._try_emit("fiber_started")
                elif not satisfied and self._active:
                    self._active = False
                    self._applied = False
                    self.ctx._teardown()  # noqa: SLF001
                    self._try_emit("fiber_stopped")
                if not self._dirty:
                    break
        finally:
            self._refreshing = False

    def _deps_satisfied(self) -> bool:
        """Whether every declared dependency currently resolves (coeffect
        satisfaction predicate, paper §3.2)."""
        return all(self.ctx._has_service(name) for name in self.inject)

    def _apply_once(self) -> None:
        """Run the component's ``apply(ctx, config)`` exactly once per load.

        Re-entrant activation of the same fiber during ``apply`` is ignored
        (the ``_applying`` guard); a later ``refresh`` converges the state.
        """
        if self._applied or self._applying:
            return
        if self.component is None:
            self._applied = True  # 手动 fiber：无组件可应用
            return
        self._applying = True
        try:
            self.component.apply(self.ctx, self.config)
        finally:
            self._applying = False
            self._applied = True

    # ---- lifecycle events ----

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
