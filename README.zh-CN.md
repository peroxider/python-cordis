# python-cordis

[English](README.md) | [中文](README.zh-CN.md)

**官网 / 文档：** https://peroxider.github.io/python-cordis/

面向 Python 的插件驱动框架内核，灵感来自 cordis 框架：
**万物皆插件（everything is a plugin）**。

本包是一个 *元框架（meta-framework）*：它只提供让应用能够由插件组合而成的引擎——
钩子（hooks）、反射式服务容器、插件生命周期、配置装配、热重载与声明式组件加载器。
它对 agent、LLM、文件系统、持久化或网络传输等业务概念一无所知。

具体业务模块（Agent 主循环、会话日志、持久化后端、能力缝、Web 传输）位于配套包
[`python-cordis-agent`](https://pypi.org/project/python-cordis-agent/)，
作为本内核之上普通且可替换的插件存在。

## 目录

- [功能特性](#功能特性)
- [安装](#安装)
- [快速开始](#快速开始)
- [核心概念](#核心概念)
- [架构](#架构)
- [开发](#开发)
- [相关项目](#相关项目)
- [许可证](#许可证)

> 更完整的讲解 —— 架构图、钩子模式表、逐步示例 —— 请访问渲染站点：
> **[peroxider.github.io/python-cordis](https://peroxider.github.io/python-cordis/)**。

## 功能特性

| 模块 | 提供的能力 |
| --- | --- |
| `HookRegistry`（[core/hook.py](src/python_cordis/core/hook.py)） | 基于 `pluggy` 的插件注册/发现，以及 cordis 的四种钩子调用模式：`emit` / `parallel` / `bail` / `waterfall`。 |
| `Context`（[core/context.py](src/python_cordis/core/context.py)） | 反射式服务容器（`ctx.fs` 解析到已注册服务），支持 `extend()` / `isolate()` 作用域、可逆的 `register()` / `set()` / `on()` / `effect()`，以及 `use()`——在被代理约束的子上下文上装配组件。 |
| `Fiber`（[core/fiber.py](src/python_cordis/core/fiber.py)） | 插件实例生命周期——`start()` / `stop()` 按注册逆序清理副作用；`refresh()` 反应式协调：声明的依赖出现则激活、消失则停用（带 `epoch` 版本守卫）。 |
| `Loader`（[core/loader.py](src/python_cordis/core/loader.py)） | 声明式组件加载器——条目表（模块 / 组件 + 配置）通过 `reconcile` 增量协调、通过 `hot_reload` 事务式热重载。 |
| 配置（[core/config.py](src/python_cordis/core/config.py)） | 基于 OmegaConf 的加载、覆盖合并、转储与插值（不执行任意代码）。 |
| HMR（[core/hmr.py](src/python_cordis/core/hmr.py)） | 免重启热重载：`Reloader`（先停旧后启新，失败回滚）、`PluginReloader` 与 `FileWatcher`（可选依赖 `watchdog`）。 |
| 可观测性（[observability.py](src/python_cordis/observability.py)） | `setup_lifecycle_logging` 注册生命周期 hookspec 与 `LifecycleLogger` 插件，通过标准 `logging` 模块输出结构化记录（`event`、`fiber`）。 |

内核本身不声明任何入口点插件；应用应在 `python_cordis.plugins` 分组下注册自己的插件，
并通过 `HookRegistry.load_entry_points()` 加载。

## 安装

要求 Python >= 3.10。

```bash
pip install python-cordis
```

可选扩展：

```bash
pip install "python-cordis[hmr]"   # 文件监听（watchdog），用于热重载
pip install "python-cordis[dev]"   # 测试 / 静态检查 / 构建工具链
```

## 快速开始

```python
from python_cordis import Context, HookRegistry
from python_cordis.core.hook import hookspec, hookimpl

# 1) 定义接缝：内核与插件之间只通过 hookspec 耦合
@hookspec
def on_message(text): ...

# 2) 插件：声明依赖（inject）+ 应用效果（apply）
class Printer:
    name = "printer"
    inject = ("config",)            # 反应式余效应：依赖齐了才激活

    def apply(self, ctx, config):
        @hookimpl
        def on_message(text):       # ctx.on 可逆地挂上监听
            print(ctx.config["prefix"], text)  # 服务容器反射解析
        ctx.on(hooks, "on_message", on_message)
        ctx.effect(lambda: print("printer torn down"))  # 可逆副作用

hooks = HookRegistry()
hooks.add_spec(__import__(__name__))  # 注册上面的 hookspec

ctx = Context()
ctx.register("config", {"prefix": ">"})

fiber = ctx.use(Printer())          # 依赖已满足 -> 立即激活
assert fiber.active

hooks.emit("on_message", text="hello, plugins")

fiber.stop()                        # 逆序回滚：监听被摘除、副作用被撤销
```

## 核心概念

- **钩子是内核与插件之间的接缝** —— 内核声明可扩展点（`@hookspec`），插件提供实现
  （`@hookimpl`）。内核中没有任何针对具体插件的硬编码。
- **可逆效应（Revertible effects）** —— 每个 `ctx.effect()`、`register` / `set`、
  `on` 都返回一个幂等的 disposer；teardown 按逆序执行逆操作，因此移除组件会完整撤销其
  全部副作用（论文 §3.1）。
- **反应式余效应（Reactive coeffects）** —— 组件声明其依赖（`inject`）；`use()` 装配它，
  `refresh()` 向目标状态收敛：依赖出现则激活、消失则停用（论文 §3.2）。
- **`Fiber` 只发出事件，插件负责观察** —— 内核只 *发出* 生命周期事件
  （`fiber_started` / `fiber_stopped`）；日志是普通且可逆的插件（`LifecycleLogger`）。
- **一切皆可替换** —— 内核不拥有任何具体提供者；所有业务服务由应用层插件注册，
  因此替换实现不需要改动内核。

## 架构

![架构图](https://raw.githubusercontent.com/peroxider/python-cordis/master/docs/architecture.svg)

图表源文件（[docs/architecture.mmd](docs/architecture.mmd)）可编辑；用任意 mermaid
渲染器重新渲染为 SVG 即可更新上图。图中展示了内核五大核心（hooks、context、fiber、
loader、config）与可选增强（HMR、生命周期日志）如何连接到应用层插件。

## 开发

```bash
pip install -e ".[dev,hmr]"
python -m mypy        # 严格类型检查
python -m pytest      # 测试套件
python -m build       # sdist + wheel
```

## 相关项目

- [`python-cordis-agent`](https://pypi.org/project/python-cordis-agent/) —— 应用层：
  Agent 主循环、LLM 能力缝、会话日志、持久化后端与 Web 传输，全部作为本内核之上可替换的插件。

## 许可证

[MIT](LICENSE)
