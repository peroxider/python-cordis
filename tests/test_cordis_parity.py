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

from python_cordis import Context, Fiber, HookRegistry, Loader
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


# ---- 论文 §3.1 可逆效应（Revertible Effects）：卸载撤销全部副作用 ----

def test_effect_teardown_reverts_all_mutations_in_reverse():
    """组件移除时，其全部副作用按逆注册顺序撤销（时间可组合性）。"""
    ctx = Context()
    order: list[str] = []
    ctx.register("a", 1)
    ctx.effect(lambda: (order.append("undo-a"), ctx._services.pop("a", None)))
    ctx.register("b", 2)
    ctx.effect(lambda: (order.append("undo-b"), ctx._services.pop("b", None)))
    ctx.effect(lambda: order.append("undo-c"))

    ctx._teardown()
    assert order == ["undo-c", "undo-b", "undo-a"]  # LIFO 逆序
    assert not hasattr(ctx, "a")
    assert not hasattr(ctx, "b")


def test_fiber_unload_restores_context_to_pre_load_state():
    """UNLOAD：应用累积逆函数后，上下文恢复（论文 §3.1 / §3.3）。"""
    ctx = Context()
    ctx.register("existing", "keep")
    events: list[str] = []

    class Plugin:
        name = "parity-revert"
        inject = ("existing",)

        def apply(self, ctx: Context, config) -> None:
            ctx.register("added", "new")
            ctx.effect(lambda: events.append("reverted"))

    fiber = ctx.use(Plugin())
    assert fiber.active
    assert fiber.ctx.added == "new"

    fiber.dispose()  # 卸载
    assert not fiber.active
    assert fiber.disposed
    assert ctx.existing == "keep"  # 既有服务保留
    assert not hasattr(fiber.ctx, "added")  # 新增副作用被撤销
    assert events == ["reverted"]


# ---- 论文 §3.2 反应式余效应（Reactive Coeffects）：依赖驱动生命周期 ----

def test_reactive_coeffect_dependency_drives_fiber_lifecycle():
    """依赖出现 -> 组件激活；依赖消失 -> 组件停用（空间可组合性）。"""
    ctx = Context()
    events: list[str] = []

    class Consumer:
        name = "parity-consumer"
        inject = ("db",)

        def apply(self, ctx: Context, config) -> None:
            events.append("activate")

    fiber = ctx.use(Consumer())
    assert not fiber.active  # 依赖未出现：不激活

    ctx.register("db", object())  # 依赖出现 -> 自动激活
    assert fiber.active
    assert events == ["activate"]

    ctx._services.pop("db")
    ctx._notify({"db"})  # 依赖消失 -> 自动停用
    assert not fiber.active


def test_proxy_enforces_declared_dependencies():
    """ctx.use 的子上下文只放行 inject 声明键；未声明访问被拒绝。"""
    ctx = Context()
    ctx.register("fs", object())
    ctx.register("hidden", object())

    class Plugin:
        name = "parity-proxy"
        inject = ("fs",)

        def apply(self, ctx: Context, config) -> None:
            self.seen = ctx.fs  # 已声明 -> 可访问
            with pytest.raises(Exception):
                _ = ctx.hidden  # 未声明 -> 拒绝

    plugin = Plugin()
    fiber = ctx.use(plugin)
    assert fiber.active
    assert plugin.seen is ctx.fs


# ---- 论文 §3.3 组件与纤维（Component & Fiber）：use 装配 + 卸载 ----

def test_use_composes_component_with_isolated_context_and_unloads():
    """use 在子上下文装配组件；卸载时子上下文与 fiber 一并回收。"""
    ctx = Context()
    events: list[str] = []

    class Leaf:
        name = "parity-leaf"
        inject = ("root_svc",)

        def apply(self, ctx: Context, config) -> None:
            ctx.register("leaf_svc", "v")
            events.append("leaf-apply")

    ctx.register("root_svc", "r")
    fiber = ctx.use(Leaf())
    assert fiber.active
    assert fiber.ctx.leaf_svc == "v"  # 组件注册在自身上下文
    assert fiber.ctx.root_svc == "r"  # 声明的依赖沿父链解析

    ctx._teardown()  # 宿主卸载 -> 子 fiber 一并回收
    assert fiber.disposed
    assert events == ["leaf-apply"]


# ---- 论文 §4.2 声明式组件加载器（Declarative Loader）：配置协调 + HMR ----

def test_loader_reconciles_config_minimally():
    """reconcile 只做最小破坏性操作：新增启动、删除卸载、变更重载、未动保持。"""
    ctx = Context()
    events: list[str] = []

    class Plugin:
        def __init__(self, name: str) -> None:
            self.name = name

        def apply(self, ctx: Context, config) -> None:
            events.append((self.name, "apply", config))

    loader = Loader(ctx)
    a, b = Plugin("a"), Plugin("b")
    loader.reconcile([{"id": "a", "component": a, "config": {"v": 1}}, {"id": "b", "component": b}])
    assert set(loader.fibers()) == {"a", "b"}

    loader.reconcile([{"id": "a", "component": a, "config": {"v": 2}}, {"id": "b", "component": b}])
    # a 配置变更 -> 重载（apply 再次）；b 未变 -> 保持（不重复 apply）
    assert events.count(("a", "apply", {"v": 1})) == 1
    assert events.count(("a", "apply", {"v": 2})) == 1
    assert events.count(("b", "apply", None)) == 1

    loader.reconcile([{"id": "a", "component": a, "config": {"v": 2}}])
    assert set(loader.fibers()) == {"a"}  # b 被移除卸载


def test_loader_hot_reload_rolls_back_transactionally(tmp_path):
    """HMR：模块代码更新原地生效；坏代码触发回滚，旧版本保持。"""
    import importlib
    import sys

    module_path = tmp_path / "parity_hot.py"
    module_path.write_text(
        "from python_cordis.core.context import Context\n"
        "def apply(ctx: Context, config):\n"
        "    ctx.register('hot_value', 'v1')\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        loader = Loader(Context())
        loader.start([{"id": "hot", "module": "parity_hot"}])
        assert loader.fibers()["hot"].ctx.hot_value == "v1"

        module_path.write_text(
            "from python_cordis.core.context import Context\n"
            "def apply(ctx: Context, config):\n"
            "    ctx.register('hot_value', 'v2')\n",
            encoding="utf-8",
        )
        assert loader.hot_reload("hot") is True
        assert loader.fibers()["hot"].ctx.hot_value == "v2"  # 新代码生效

        module_path.write_text("raise RuntimeError('broken')\n", encoding="utf-8")
        assert loader.hot_reload("hot") is False  # 失败 -> 回滚
        assert loader.fibers()["hot"].ctx.hot_value == "v2"  # 旧版本保持
        assert loader.errors and "broken" in str(loader.errors[-1])
    finally:
        sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()
