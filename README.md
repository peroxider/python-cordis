# python-cordis

[English](README.md) | [中文](README.zh-CN.md)

A plugin-driven framework kernel for Python, inspired by the cordis framework:
**everything is a plugin**.

This package is a *meta-framework*: it ships only the engine that makes an
application composable from plugins — hooks, a reflective service container,
plugin lifecycle, config assembly, hot reload, and a declarative component
loader. It knows nothing about agents, LLMs, filesystems, persistence, or
transports.

Concrete business modules (agent loop, session logs, persistence backends,
capability seams, web transport) live in the companion package
[`python-cordis-agent`](https://pypi.org/project/python-cordis-agent/) as plain,
replaceable plugins on top of this kernel.

## Table of contents

- [Features](#features)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Core concepts](#core-concepts)
- [Architecture](#architecture)
- [Development](#development)
- [Related projects](#related-projects)
- [License](#license)

## Features

| Module | What it provides |
| --- | --- |
| `HookRegistry` ([core/hook.py](src/python_cordis/core/hook.py)) | plugin registration/discovery built on `pluggy`, plus the four cordis hook modes: `emit` / `parallel` / `bail` / `waterfall`. |
| `Context` ([core/context.py](src/python_cordis/core/context.py)) | a reflective service container (`ctx.fs` resolves to a registered service) with `extend()` / `isolate()` scopes, reversible `register()` / `set()` / `on()` / `effect()`, and `use()` which mounts a component on a proxy-enforced child context. |
| `Fiber` ([core/fiber.py](src/python_cordis/core/fiber.py)) | plugin instance lifecycle — `start()` / `stop()` with effects torn down in reverse order; `refresh()` reactively activates when declared dependencies appear and deactivates when they disappear (with an `epoch` version guard). |
| `Loader` ([core/loader.py](src/python_cordis/core/loader.py)) | a declarative component loader — entry tables (module / component + config) reconciled incrementally (`reconcile`) and hot-reloaded transactionally (`hot_reload`). |
| Config ([core/config.py](src/python_cordis/core/config.py)) | OmegaConf-based loading, overlay patching, dumping, and interpolation (no arbitrary code execution). |
| HMR ([core/hmr.py](src/python_cordis/core/hmr.py)) | hot module reload without restarting: `Reloader` (stop old, start new, roll back on failure), `PluginReloader`, and `FileWatcher` (optional `watchdog`). |
| Observability ([observability.py](src/python_cordis/observability.py)) | `setup_lifecycle_logging` registers the lifecycle hookspecs plus a `LifecycleLogger` plugin that writes structured records (`event`, `fiber`) via the standard `logging` module. |

The kernel declares no entry-point plugins of its own; applications register
their own plugins under the `python_cordis.plugins` group and load them with
`HookRegistry.load_entry_points()`.

## Installation

Requires Python >= 3.10.

```bash
pip install python-cordis
```

Optional extras:

```bash
pip install "python-cordis[hmr]"   # file watching (watchdog) for hot reload
pip install "python-cordis[dev]"   # test/lint/build tooling
```

## Quick start

```python
from python_cordis import Context, HookRegistry
from python_cordis.core.hook import hookspec, hookimpl

# 1) Define the seam: the kernel and plugins couple only through hookspecs.
@hookspec
def on_message(text): ...

# 2) A plugin: declares its dependencies (inject) and applies its effects.
class Printer:
    name = "printer"
    inject = ("config",)            # reactive coeffect: activates only when satisfied

    def apply(self, ctx, config):
        @hookimpl
        def on_message(text):       # ctx.on registers the listener reversibly
            print(ctx.config["prefix"], text)  # reflective service resolution
        ctx.on(hooks, "on_message", on_message)
        ctx.effect(lambda: print("printer torn down"))  # revertible side effect

hooks = HookRegistry()
hooks.add_spec(__import__(__name__))  # register the hookspec above

ctx = Context()
ctx.register("config", {"prefix": ">"})

fiber = ctx.use(Printer())          # dependencies satisfied -> activates at once
assert fiber.active

hooks.emit("on_message", text="hello, plugins")

fiber.stop()                        # teardown in reverse order: listener off, effects undone
```

## Core concepts

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
  events (`fiber_started` / `fiber_stopped`); logging is a plain, reversible
  plugin (`LifecycleLogger`).
- **Everything is replaceable** — the kernel owns no concrete provider; every
  business service is registered by an application-layer plugin, so swapping
  implementations needs zero kernel changes.

## Architecture

![Architecture](https://raw.githubusercontent.com/peroxider/python-cordis/master/docs/architecture.svg)

The diagram source ([docs/architecture.mmd](docs/architecture.mmd)) is
editable; re-render it to SVG with any mermaid renderer to update the image
above. It shows how the kernel's five core pieces (hooks, context, fiber,
loader, config) plus the optional enhancements (HMR, lifecycle logging) connect
to the application layer plugins.

## Development

```bash
pip install -e ".[dev,hmr]"
python -m mypy        # strict type checking
python -m pytest      # test suite
python -m build       # sdist + wheel
```

## Related projects

- [`python-cordis-agent`](https://pypi.org/project/python-cordis-agent/) — the
  application layer: agent loop, LLM seam, session logs, persistence backends,
  and web transport, all as replaceable plugins on top of this kernel.

## License

[MIT](LICENSE)
