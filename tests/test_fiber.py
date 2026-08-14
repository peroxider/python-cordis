"""F3 生命周期：Fiber start/stop、effect 逆序清理。"""

from __future__ import annotations

from python_cordis import Context, Fiber


def test_stop_tears_down_effects_in_reverse_order():
    ctx = Context()
    order = []
    ctx.effect(lambda: order.append("a"))
    ctx.effect(lambda: order.append("b"))
    fiber = Fiber(ctx).start()
    assert fiber.active
    fiber.stop()
    assert order == ["b", "a"]  # 逆注册顺序，后注册先清理
    assert not fiber.active


def test_repeat_start_stop_is_idempotent():
    ctx = Context()
    fiber = Fiber(ctx).start()
    fiber.start()  # 幂等
    fiber.stop()
    fiber.stop()  # 幂等，不报错
    assert not fiber.active


def test_context_manager_syntax():
    ctx = Context()
    order = []
    ctx.effect(lambda: order.append("x"))
    with Fiber(ctx) as fiber:
        assert fiber.active
    assert not fiber.active
    assert order == ["x"]


def test_failing_effect_does_not_block_others():
    ctx = Context()
    order = []

    def boom():
        raise RuntimeError("boom")

    ctx.effect(boom)
    ctx.effect(lambda: order.append("ok"))
    Fiber(ctx).stop()  # 不抛错
    assert order == ["ok"]


def test_register_disposer_runs_at_fiber_stop():
    ctx = Context()
    order = []
    d = ctx.register("s", object())
    ctx.effect(lambda: order.append("effect"))
    d2 = ctx.register("t", object())
    # 全部清理：服务注销 + 副作用
    Fiber(ctx).stop()
    with pytest.raises(AttributeError):
        _ = ctx.s
    with pytest.raises(AttributeError):
        _ = ctx.t
    assert order == ["effect"]


# ---- 论文 §3.2 / §3.3 反应式余效应 + 组件纤维：refresh 目标状态收敛 ----


class _ReactiveComponent:
    name = "reactive"
    inject = ("db",)

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def apply(self, ctx, config):
        self.events.append("apply")
        ctx.register("svc", object())


def test_refresh_activates_when_dependencies_satisfied():
    ctx = Context()
    ctx.register("db", object())
    events: list[str] = []
    fiber = Fiber(ctx, component=_ReactiveComponent(events))
    fiber.refresh()
    assert fiber.active
    assert events == ["apply"]  # apply 恰好一次


def test_refresh_deactivates_when_dependency_disappears():
    ctx = Context()
    ctx.register("db", object())
    events: list[str] = []
    fiber = Fiber(ctx, component=_ReactiveComponent(events))
    fiber.refresh()
    assert fiber.active

    ctx._services.pop("db")
    fiber.refresh()  # 手动 fiber 不订阅宿主通知，显式收敛
    assert not fiber.active
    with pytest.raises(AttributeError):
        _ = fiber.ctx.svc  # 副作用已撤销


def test_refresh_reactivates_when_dependency_returns():
    ctx = Context()
    events: list[str] = []
    fiber = Fiber(ctx, component=_ReactiveComponent(events))
    fiber.refresh()
    assert not fiber.active

    ctx.register("db", object())
    fiber.refresh()  # 依赖出现 -> 显式收敛 -> 激活
    assert fiber.active
    assert events == ["apply"]


def test_refresh_is_reentrant_and_converges_to_quiescence():
    """重入通知折叠进下一轮循环，最终收敛到静止（论文惯性状态机同步版）。"""
    ctx = Context()
    events: list[str] = []

    class ChainComponent:
        name = "chain"
        inject = ("db",)

        def apply(self, ctx, config):
            events.append("apply")
            ctx.register("extra", object())  # 激活期间又产生依赖变化

    ctx.register("db", object())
    fiber = Fiber(ctx, component=ChainComponent())
    fiber.refresh()
    assert fiber.active
    assert fiber.ctx.extra is not None


def test_epoch_bumps_on_each_refresh_pass():
    ctx = Context()
    ctx.register("db", object())
    fiber = Fiber(ctx, component=_ReactiveComponent([]))
    e0 = fiber.epoch
    fiber.refresh()
    assert fiber.epoch > e0  # 每次收敛推进 epoch


def test_disposed_fiber_ignores_refresh():
    ctx = Context()
    ctx.register("db", object())
    fiber = Fiber(ctx, component=_ReactiveComponent([])).start()
    fiber.dispose()
    assert fiber.disposed
    fiber.refresh()  # 已 dispose -> 忽略，不抛错
    assert not fiber.active


def test_manual_start_activates_even_without_dependencies():
    """手动 start 是显式激活：不要求依赖满足（与 refresh 的目标状态区分）。"""
    ctx = Context()
    events: list[str] = []
    fiber = Fiber(ctx, component=_ReactiveComponent(events)).start()
    assert fiber.active
    assert events == ["apply"]
    fiber.stop()
    assert not fiber.active


import pytest  # noqa: E402  (after other imports for readability)


# ---- F8 HMR 热重载：Reloader 失败回滚 + PluginReloader 模块重载 + FileWatcher ----

import importlib.util
import sys
import threading

from python_cordis import FileWatcher, HookRegistry, PluginReloader, Reloader  # noqa: E402
from python_cordis.core.hook import hookspec  # noqa: E402
from python_cordis.core.config import load_file  # noqa: E402


@hookspec
def greeting(name, next=None): ...  # noqa: E704  (HMR 测试用 hookspec)


# ---- Reloader：通用"先停旧、后启新"交换，失败回滚 ----

def test_reloader_swaps_to_new_version():
    state = {"v": 0}
    events = []

    def load():
        return {"v": state["v"]}

    def activate(unit):
        events.append(("activate", unit["v"]))

    def deactivate(unit):
        events.append(("deactivate", unit["v"]))

    reloader = Reloader(load=load, activate=activate, deactivate=deactivate)
    assert reloader.reload() is True
    assert reloader.current == {"v": 0}
    state["v"] = 1  # 模拟新版本就绪
    assert reloader.reload() is True
    assert reloader.current == {"v": 1}
    assert events == [("activate", 0), ("deactivate", 0), ("activate", 1)]  # 先停旧、后启新
    assert reloader.errors == []


def test_reloader_load_failure_keeps_old_running():
    events = []
    fail = {"flag": False}

    def load():
        if fail["flag"]:
            raise RuntimeError("boom")
        return {"v": "new"}

    def activate(unit):
        events.append(("activate", unit["v"]))

    def deactivate(unit):
        events.append(("deactivate", unit["v"]))

    reloader = Reloader(load=load, activate=activate, deactivate=deactivate)
    assert reloader.reload() is True
    fail["flag"] = True  # 注入错误代码
    assert reloader.reload() is False
    assert events == [("activate", "new")]  # 旧版本从未被触碰
    assert reloader.errors and reloader.errors[-1].stage == "load"
    assert "boom" in str(reloader.errors[-1])  # 失败原因被记录


def test_reloader_activate_failure_rolls_back_to_old():
    events = []
    fail = {"flag": False}
    seq = iter(range(10))

    def load():
        return {"v": next(seq)}

    def activate(unit):
        events.append(("activate", unit["v"]))
        if fail["flag"]:
            raise RuntimeError("activate exploded")

    def deactivate(unit):
        events.append(("deactivate", unit["v"]))

    reloader = Reloader(load=load, activate=activate, deactivate=deactivate)
    assert reloader.reload() is True  # v0 运行
    fail["flag"] = True
    assert reloader.reload() is False  # v1 启动失败
    # 回滚：清理未启动完成的 v1，并恢复 v0
    assert ("deactivate", 1) in events
    assert events.count(("activate", 0)) == 2  # 旧版本被恢复
    assert reloader.current == {"v": 0}  # 旧版本仍可用
    assert reloader.errors[-1].stage == "activate"


def test_reloader_on_error_callback_receives_failure():
    seen = []

    def load():
        raise ValueError("bad module")

    reloader = Reloader(
        load=load, activate=lambda u: None, deactivate=lambda u: None, on_error=seen.append
    )
    assert reloader.reload() is False
    assert len(seen) == 1
    assert "bad module" in str(seen[0])


# ---- PluginReloader：模块文件变化 -> 新逻辑生效 / 坏代码 -> 回滚 ----

_PLUG_V1 = """\
from python_cordis.core.hook import hookimpl

@hookimpl
def greeting(name, next=None):
    return f"v1:{name}"
"""

_PLUG_V2 = """\
from python_cordis.core.hook import hookimpl

@hookimpl
def greeting(name, next=None):
    return f"v2:{name}"
"""

_PLUG_BROKEN = "raise RuntimeError('boom')\n"


def _import_plugin(name: str, path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _make_hmr_hooks():
    hooks = HookRegistry()
    hooks.add_spec(sys.modules[__name__])  # 注册本文件中的 greeting hookspec
    return hooks


def test_plugin_reloader_applies_module_change(tmp_path):
    plug = tmp_path / "plug.py"
    plug.write_text(_PLUG_V1, encoding="utf-8")
    module = _import_plugin("hmr_plug_change", plug)
    hooks = _make_hmr_hooks()
    hooks.register(module)
    reloader = PluginReloader(module, hooks)

    assert hooks.emit("greeting", name="world") == ["v1:world"]  # 旧逻辑生效

    plug.write_text(_PLUG_V2, encoding="utf-8")  # 修改插件模块
    assert reloader.reload() is True
    assert hooks.emit("greeting", name="world") == ["v2:world"]  # 新逻辑无需重启即生效
    assert reloader.errors == []


def test_plugin_reloader_rolls_back_on_broken_module(tmp_path):
    plug = tmp_path / "plug.py"
    plug.write_text(_PLUG_V2, encoding="utf-8")
    module = _import_plugin("hmr_plug_broken", plug)
    hooks = _make_hmr_hooks()
    hooks.register(module)
    reloader = PluginReloader(module, hooks)

    assert hooks.emit("greeting", name="x") == ["v2:x"]

    plug.write_text(_PLUG_BROKEN, encoding="utf-8")  # 注入错误代码
    assert reloader.reload() is False
    assert reloader.errors[-1].stage == "load"
    assert "boom" in str(reloader.errors[-1])  # 失败原因被记录
    assert hooks.emit("greeting", name="x") == ["v2:x"]  # 旧插件仍可用


# ---- FileWatcher：配置/文件变化触发回调（F8.1）----

def test_file_watcher_fires_on_config_change(tmp_path):
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("answer: 1", encoding="utf-8")
    holder = {}

    def apply():
        holder["answer"] = load_file(cfg)["answer"]

    apply()
    assert holder["answer"] == 1

    changed = threading.Event()

    def on_change(event):
        apply()
        changed.set()

    watcher = FileWatcher([tmp_path], on_change=on_change)
    watcher.start()
    try:
        cfg.write_text("answer: 2", encoding="utf-8")  # 修改配置文件
        assert changed.wait(timeout=5)
        assert holder["answer"] == 2  # 无需重启即生效
    finally:
        watcher.stop()


def test_file_watcher_context_manager_and_idempotent_ops(tmp_path):
    target = tmp_path / "f.txt"
    target.write_text("1", encoding="utf-8")
    changed = threading.Event()

    with FileWatcher([tmp_path], on_change=lambda e: changed.set()) as watcher:
        watcher.start()  # 重复 start 幂等
        target.write_text("2", encoding="utf-8")
        assert changed.wait(timeout=5)
    watcher.stop()  # 已 stop，再 stop 幂等无副作用


def test_exec_reload_rejects_module_without_source_loader():
    import types

    from python_cordis.core.hmr import _exec_reload

    with pytest.raises(ImportError):
        _exec_reload(types.ModuleType("no_loader"))


# ---- F10.1 结构化日志：Fiber 生命周期事件 + LifecycleLogger 插件 ----

import logging  # noqa: E402

from python_cordis import setup_lifecycle_logging  # noqa: E402
from python_cordis.core.hook import hookimpl  # noqa: E402


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # noqa: N802 (logging API)
        self.records.append(record)


def _capturing_logger() -> tuple[logging.Logger, _Capture]:
    logger = logging.getLogger("python_cordis.lifecycle.test")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    capture = _Capture()
    logger.addHandler(capture)
    return logger, capture


def test_fiber_emits_lifecycle_hooks_when_spec_registered():
    hooks = HookRegistry()
    setup_lifecycle_logging(hooks)  # 注册 hookspecs + LifecycleLogger
    seen = []

    class Probe:
        @hookimpl
        def fiber_started(self, fiber):
            seen.append(("started", fiber))

        @hookimpl
        def fiber_stopped(self, fiber):
            seen.append(("stopped", fiber))

    hooks.register(Probe())
    fiber = Fiber(Context(), hooks=hooks).start()
    fiber.stop()
    assert [kind for kind, _ in seen] == ["started", "stopped"]
    assert seen[0][1] is fiber  # 事件携带同一 Fiber 实例


def test_lifecycle_logger_records_structured_fields():
    hooks = HookRegistry()
    logger, capture = _capturing_logger()
    setup_lifecycle_logging(hooks, logger=logger)
    Fiber(Context(), hooks=hooks).start().stop()
    events = [r.__dict__.get("event") for r in capture.records]
    assert events == ["fiber_started", "fiber_stopped"]
    assert all(r.__dict__.get("fiber") for r in capture.records)


def test_lifecycle_logging_is_reversible():
    hooks = HookRegistry()
    logger, capture = _capturing_logger()
    dispose = setup_lifecycle_logging(hooks, logger=logger)
    Fiber(Context(), hooks=hooks).start().stop()
    assert len(capture.records) == 2
    dispose()  # 卸载日志插件，记录停止
    Fiber(Context(), hooks=hooks).start().stop()
    assert len(capture.records) == 2  # 不再新增


def test_fiber_without_hooks_emits_nothing():
    hooks = HookRegistry()
    setup_lifecycle_logging(hooks)
    # Fiber 未绑定 hooks：生命周期事件应静默（不抛错、不产生记录）
    Fiber(Context()).start().stop()
    assert True
