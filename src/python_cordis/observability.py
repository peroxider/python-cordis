"""F10.1: structured lifecycle logging, provided as a reversible plugin.

The kernel does not hard-code logging. ``Fiber`` only *emits* two lifecycle
hooks — ``fiber_started`` / ``fiber_stopped`` — when it is constructed with a
:class:`~python_cordis.HookRegistry` whose registry has these specs registered.
How those events are consumed is entirely up to plugins: :class:`LifecycleLogger`
turns them into structured records through the standard :mod:`logging` module.

Because it is a plain plugin, the capability is fully reversible:
``setup_lifecycle_logging`` returns a disposer; call it and the records stop.
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Callable

from .core.hook import HookRegistry, hookimpl, hookspec

__all__ = [
    "fiber_started",
    "fiber_stopped",
    "LifecycleLogger",
    "setup_lifecycle_logging",
    "LOGGER_NAME",
]

LOGGER_NAME = "python_cordis.lifecycle"


@hookspec
def fiber_started(fiber: Any) -> None:
    """Emitted when a Fiber becomes active."""


@hookspec
def fiber_stopped(fiber: Any) -> None:
    """Emitted when a Fiber is stopped."""


class LifecycleLogger:
    """A plugin that records Fiber lifecycle events as structured log records.

    ``extra`` carries the structured fields (``event``, ``fiber``), which a
    key=value or JSON formatter can render for machine consumption.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(LOGGER_NAME)

    @hookimpl
    def fiber_started(self, fiber: Any) -> None:
        self.logger.info(
            "fiber lifecycle", extra={"event": "fiber_started", "fiber": id(fiber)}
        )

    @hookimpl
    def fiber_stopped(self, fiber: Any) -> None:
        self.logger.info(
            "fiber lifecycle", extra={"event": "fiber_stopped", "fiber": id(fiber)}
        )


def setup_lifecycle_logging(
    hooks: HookRegistry, logger: logging.Logger | None = None
) -> Callable[[], None]:
    """Register the lifecycle hookspecs plus a :class:`LifecycleLogger`.

    Returns an idempotent disposer: call it to stop the logging (unregister).
    """
    hooks.add_spec(sys.modules[__name__])
    return hooks.register(LifecycleLogger(logger))
