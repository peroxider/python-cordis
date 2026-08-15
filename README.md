# python-cordis

A plugin-driven framework kernel for Python, inspired by the cordis framework:
**everything is a plugin**.

This package is a *meta-framework*: it ships only the engine that makes an
application composable from plugins — hooks, a reflective service container,
plugin lifecycle, config assembly, and hot reload. It knows nothing about
agents, LLMs, filesystems, persistence, or transports.

Concrete business modules (agent loop, session logs, persistence backends,
capability seams, web transport) live in the companion package
[`python-cordis-agent`](https://pypi.org/project/python-cordis-agent/) as plain, replaceable
plugins on top of this kernel.

## What the kernel provides

- `HookRegistry` (`python_cordis.core.hook`): plugin registration/discovery and
  the four hook invocation modes (`emit` / `parallel` / `bail` / `waterfall`)
  built on `pluggy`.
- `Context` (`python_cordis.core.context`): a reflective service container
  (`ctx.fs` resolves to a registered service), with `extend()` / `isolate()`
  scopes, reversible `register()` / `set()`, reversible `on()` listeners, and
  `use()` which instantiates a component (declaring `inject` + `apply`) on a
  child context restricted to its declared dependencies (proxy enforcement —
  undeclared access raises `ServiceNotFound`).
- `Fiber` (`python_cordis.core.fiber`): plugin instance lifecycle —
  `start()` / `stop()` with effects torn down in reverse registration order.
  `refresh()` is the reactive reconciliation: it activates when declared
  dependencies appear and deactivates when they disappear, converging to
  quiescence with an `epoch` version guard. When constructed with a
  `HookRegistry` that has the lifecycle specs registered, it emits
  `fiber_started` / `fiber_stopped`.
- `Loader` (`python_cordis.core.loader`): a declarative component loader —
  entry tables (module / component + config) reconciled incrementally
  (`reconcile` applies the minimal destructive ops) and hot-reloaded
  transactionally (`hot_reload` re-executes the module in place and rolls back
  on failure).
- Config assembly (`python_cordis.core.config`): OmegaConf-based loading,
  overlay patching, dumping, and interpolation (no arbitrary code execution).
- HMR (`python_cordis.core.hmr`): hot module reload without restarting.
  `Reloader` swaps a unit ("stop old, then start new") and rolls back on any
  failure; `PluginReloader` re-executes an already-imported plugin module in
  place and re-registers its hooks; `FileWatcher` (optional `watchdog`) fires
  `on_change` on any watched file.
- Lifecycle observability (`python_cordis.observability`):
  `setup_lifecycle_logging` registers the lifecycle hookspecs plus a
  `LifecycleLogger` plugin that writes structured records (`event`, `fiber`)
  via the standard `logging` module. It returns a disposer, so the
  observability is fully reversible.

The kernel declares no entry-point plugins of its own; applications register
their own plugins under the `python_cordis.plugins` group and load them with
`HookRegistry.load_entry_points()`.

## Quick start

```bash
pip install -e .
pytest
```

## Architecture

![Architecture](https://raw.githubusercontent.com/peroxider/python-cordis/master/docs/architecture.svg)

The diagram source (`docs/architecture.mmd`) is editable; re-render to SVG with
any mermaid renderer to update the image above.

Key ideas:

- **Hooks are the seams between kernel and plugins** — the kernel declares what
  can be extended (`@hookspec`), plugins provide it (`@hookimpl`). Nothing in
  the kernel hard-codes a specific plugin.
- **Revertible effects** — every `ctx.effect()`, `register` / `set`, and `on`
  returns an idempotent disposer; teardown runs the inverses in reverse order,
  so removing a component fully undoes its side effects (paper §3.1).
- **Reactive coeffects** — a component declares its dependencies (`inject`);
  `use()` mounts it and `refresh()` reconciles to the target state, activating
  when dependencies appear and deactivating when they disappear (paper §3.2).
- **`Fiber` emits, plugins observe** — the kernel only *emits* lifecycle
  events; logging is a plain, reversible plugin (`LifecycleLogger`).
- **Everything is replaceable** — the kernel owns no concrete provider; every
  business service is registered by an application-layer plugin, so swapping
  implementations needs zero kernel changes.

## Development

```bash
pip install -e ".[dev,hmr]"
python -m mypy        # strict type checking
python -m pytest      # test suite
python -m build       # sdist + wheel
```

The full feature specification (kernel + application layer, with package
ownership per feature) is maintained in the `deepseek-harness` repository at
`docs/python-cordis-feature-spec.md`.
