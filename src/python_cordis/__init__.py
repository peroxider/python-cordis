"""python-cordis: a plugin-driven framework kernel for Python.

Everything is a plugin. This package provides the pure engine that makes an
application composable from plugins: hooks (on pluggy), a reflective service
container, plugin lifecycle, config assembly, hot-reload, and a declarative
component loader.

The kernel implements cordis's core semantics from the paper
*"A Programming Paradigm for Spatiotemporal Composability"*:

- **Revertible effects** — every ``ctx.effect()`` / ``register`` / ``set`` /
  ``on`` returns an idempotent disposer; teardown runs the inverses in reverse
  order, so removing a component fully undoes its side effects (§3.1).
- **Reactive coeffects** — a component declares its dependencies (``inject``);
  ``ctx.use()`` mounts it and ``Fiber.refresh()`` reconciles to the target
  state, activating when dependencies appear and deactivating when they
  disappear (§3.2).
- **Component & fiber** — a component is an ``inject`` spec plus an ``apply``
  function; a fiber is its runtime instance with a reconciled lifecycle (§3.3).
- **Declarative loader** — ``Loader`` reconciles an entry tree minimally and
  hot-reloads modules transactionally (§4.2).

It is a *meta-framework*: it knows nothing about agents, LLMs, filesystems,
persistence, or transports. Concrete business modules (agent loop, LLM seam,
session logs, persistence backends, web transport) live in the companion
``python-cordis-agent`` package and are plain, replaceable plugins on top of
this kernel.
"""

from .core.config import dump, load, overlay, resolve
from .core.context import Context, inject
from .core.fiber import Fiber
from .core.hmr import FileWatcher, PluginReloader, Reloader
from .core.hook import HookRegistry, hookimpl, hookspec
from .core.loader import Loader, LoaderError
from .observability import (
    LOGGER_NAME,
    LifecycleLogger,
    fiber_started,
    fiber_stopped,
    setup_lifecycle_logging,
)

__version__ = "0.1.4"

__all__ = [
    "Context",
    "inject",
    "Fiber",
    "HookRegistry",
    "hookimpl",
    "hookspec",
    "dump",
    "load",
    "overlay",
    "resolve",
    "Reloader",
    "PluginReloader",
    "FileWatcher",
    "Loader",
    "LoaderError",
    "fiber_started",
    "fiber_stopped",
    "LifecycleLogger",
    "setup_lifecycle_logging",
    "LOGGER_NAME",
    "__version__",
]
