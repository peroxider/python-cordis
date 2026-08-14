"""cordis 对齐集成测试（内核部分）：验证纯内核语义与 cordis 严格一致。

仅依赖内核包 :mod:`python_cordis`（Context / Fiber / HookRegistry / config），
把零散特性串成"一切皆插件"的端到端场景。业务侧的 cordis 对齐场景按模块
归入 ``python-cordis-agent`` 包各自的测试：能力缝 Provider 替换（服务遮蔽）
见其 ``test_context`` 系列，Agent 主循环见 ``test_agent``，事件溯源全链路见
``test_session`` 与 ``test_persistence``。

覆盖：
- hook 执行顺序（后注册先执行）与 parallel 异常传播（cordis parallel 拒绝语义）；
- bail 短路（firstresult）；
- 配置多层叠加链（bundle → profile → home → patch）；
- 插件生命周期集成：apply 注册的服务 / hook / effect 在 stop 时全部清理。
"""

from __future__ import annotations

import sys

import pytest

from python_cordis import Context, Fiber, HookRegistry
from python_cordis.core.hook import hookimpl, hookspec
from python_cordis.core.config import load_str, overlay


# ---- 本文件内的 hookspec（供集成场景使用）----


@hookspec
def parity_event(value, next): ...


@hookspec(firstresult=True)
def parity_bail(value): ...


# ---- F1 语义：执行顺序与 parallel 异常 ----

def test_hook_execution_order_last_registered_first():
    reg = HookRegistry()
    reg.add_spec(sys.modules[__name__])
    order: list[str] = []

    class P1:
        @hookimpl
        def parity_event(self, value, next):
            order.append("p1")
            return next()

    class P2:
        @hookimpl
        def parity_event(self, value, next):
            order.append("p2")
            return next()

    reg.register(P1())
    reg.register(P2())
    reg.emit("parity_event", value=1)
    # pluggy 语义：后注册先执行（与 cordis 一致）
    assert order == ["p2", "p1"]


def test_parallel_propagates_listener_exception():
    reg = HookRegistry()
    reg.add_spec(sys.modules[__name__])

    class Boom:
        @hookimpl
        def parity_event(self, value, next):
            raise RuntimeError("boom")

    class Ok:
        @hookimpl
        def parity_event(self, value, next):
            return next()

    reg.register(Boom())
    reg.register(Ok())
    # cordis parallel：任一监听器失败即整体失败（promise all-settled → reject）
    with pytest.raises(RuntimeError, match="boom"):
        reg.parallel("parity_event", value=1)


def test_bail_returns_first_truthy_regardless_of_plugin():
    reg = HookRegistry()
    reg.add_spec(sys.modules[__name__])

    class NoneThen:
        @hookimpl
        def parity_bail(self, value):
            return None

    class Answer:
        @hookimpl
        def parity_bail(self, value):
            return value * 2

    reg.register(NoneThen())
    reg.register(Answer())
    # 后注册的 Answer 先执行并短路
    assert reg.bail("parity_bail", value=21) == 42


# ---- F4 配置：多层叠加链（bundle → profile → home → patch）----

def test_config_four_layer_overlay_chain():
    bundle = load_str("model: base\nplugins:\n  a: 1\n  b: 1\n")
    profile = load_str("model: profile\nplugins:\n  b: 2\n")
    home = load_str("plugins:\n  c: 3\n")
    patch = load_str("model: patch\n")

    merged = overlay(bundle, profile, home, patch)
    assert merged.model == "patch"  # 顶层 patch 覆盖
    assert merged.plugins.a == 1  # bundle 独有键保留
    assert merged.plugins.b == 2  # profile 覆盖 bundle
    assert merged.plugins.c == 3  # home 新增键
    # 输入未被污染
    assert "c" not in bundle.plugins


# ---- F3 生命周期集成：apply 注册的服务 / hook / effect 全部随 stop 清理 ----

def test_plugin_lifecycle_full_cleanup():
    hooks = HookRegistry()
    hooks.add_spec(sys.modules[__name__])
    ctx = Context()
    events: list[str] = []

    class Plugin:
        name = "parity-plugin"

        def apply(self, ctx: Context, config: dict) -> None:
            self.service = object()
            ctx.register("parity_svc", self.service)
            ctx.effect(lambda: events.append("effect-1"))
            ctx.effect(lambda: events.append("effect-2"))
            hooks.register(self)
            ctx.effect(lambda: hooks.unregister(self))
            events.append("start")

    plugin = Plugin()
    fiber = Fiber(ctx, hooks=hooks)
    plugin.apply(ctx, {})
    fiber.start()

    assert ctx.parity_svc is plugin.service
    assert len(hooks.plugins()) == 1

    fiber.stop()
    # 服务注销 + hook 卸载 + effect 逆序回滚
    assert not hasattr(ctx, "parity_svc")
    assert hooks.plugins() == []
    assert events == ["start", "effect-2", "effect-1"]
