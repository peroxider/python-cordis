"""F2 Context 容器：反射代理、可逆注册、作用域、inject 懒解析。"""

from __future__ import annotations

import pytest

from python_cordis import Context, inject
from python_cordis.core.context import ServiceNotFound


def test_reflection_resolves_registered_service():
    ctx = Context()
    svc = object()
    ctx.register("fs", svc)
    assert ctx.fs is svc


def test_missing_service_raises_with_name():
    ctx = Context()
    with pytest.raises(AttributeError):
        _ = ctx.does_not_exist


def test_register_returns_reversible_disposer_restoring_previous():
    ctx = Context()
    first, second = object(), object()
    dispose_first = ctx.register("s", first)
    dispose_second = ctx.register("s", second)
    assert ctx.s is second
    dispose_second()
    assert ctx.s is first  # 恢复旧值
    dispose_first()
    with pytest.raises(AttributeError):
        _ = ctx.s


def test_extend_child_sees_parent_but_does_not_mutate_it():
    ctx = Context()
    ctx.register("shared", 1)
    child = ctx.extend()
    assert child.shared == 1
    child.register("local", 2)
    assert child.local == 2
    with pytest.raises(AttributeError):
        _ = ctx.local  # 父级看不到子级注册


def test_isolate_seals_parent_and_leaks_nothing_back():
    ctx = Context()
    ctx.register("shared", 1)
    sealed = ctx.isolate()
    with pytest.raises(AttributeError):
        _ = sealed.shared  # isolate 内不可见父级
    sealed.register("inner", 2)
    assert sealed.inner == 2
    with pytest.raises(AttributeError):
        _ = ctx.inner  # 不回流父级


def test_inject_resolves_lazily():
    ctx = Context()
    ctx.register("fs", "FILESYSTEM")
    seen = []

    @inject("fs")
    def consume(fs, path):
        seen.append((fs, path))
        return "done"

    assert consume(ctx, path="x") == "done"
    assert seen == [("FILESYSTEM", "x")]


def test_inject_missing_dependency_names_both_sides():
    ctx = Context()

    @inject("nope")
    def consume(nope):
        return nope

    with pytest.raises(ServiceNotFound) as excinfo:
        consume(ctx)
    assert "nope" in str(excinfo.value)
    assert "consume" in str(excinfo.value)


# ---- 论文 §3.1 可逆效应：effect 幂等守卫 / set 可逆 + notify / on 可逆监听 ----


def test_effect_disposer_is_idempotent_armed_guard():
    """论文 Algorithm 1：disposer 只执行一次，后续调用与 teardown 都跳过。"""
    ctx = Context()
    order: list[str] = []

    def cleanup():
        order.append("cleanup")

    dispose = ctx.effect(cleanup)
    dispose()  # 首次：执行
    dispose()  # 再次：armed guard 跳过
    ctx._teardown()  # teardown 也跳过已 disarm 的条目
    assert order == ["cleanup"]


def test_set_is_reversible_and_restores_previous():
    ctx = Context()
    first, second = object(), object()
    dispose = ctx.set("s", first)
    dispose_second = ctx.set("s", second)
    assert ctx.s is second
    dispose_second()
    assert ctx.s is first  # 恢复旧值（可逆）
    dispose()
    with pytest.raises(AttributeError):
        _ = ctx.s


def test_register_shadowing_restores_previous_on_dispose():
    ctx = Context()
    first, second = object(), object()
    d1 = ctx.register("s", first)
    d2 = ctx.register("s", second)
    assert ctx.s is second
    d2()
    assert ctx.s is first
    d1()
    with pytest.raises(AttributeError):
        _ = ctx.s


# ---- 论文 §3.2 反应式余效应：ctx.on 可逆监听 ----

import sys  # noqa: E402

from python_cordis import HookRegistry  # noqa: E402
from python_cordis.core.hook import hookspec  # noqa: E402


@hookspec
def react_event(payload, next): ...  # noqa: E704  (ctx.on 测试用 hookspec)


def test_on_registers_hook_listener_as_reversible_effect():
    reg = HookRegistry()
    reg.add_spec(sys.modules[__name__])
    ctx = Context()
    seen: list[str] = []

    def listener(payload, next):
        seen.append(payload)
        return next()

    dispose = ctx.on(reg, "react_event", listener)
    reg.emit("react_event", payload="x")
    assert seen == ["x"]

    dispose()  # 可逆：注销监听器
    reg.emit("react_event", payload="y")
    assert seen == ["x"]  # 不再触发


def test_on_listener_removed_when_context_tears_down():
    reg = HookRegistry()
    reg.add_spec(sys.modules[__name__])
    ctx = Context()
    seen: list[str] = []
    ctx.on(reg, "react_event", lambda payload, next: (seen.append(payload), next()))
    reg.emit("react_event", payload="a")
    assert seen == ["a"]
    ctx._teardown()  # 逆序清理：监听器随之注销
    reg.emit("react_event", payload="b")
    assert seen == ["a"]


# ---- 论文 §3.3 / §3.4 统一上下文 + 组件纤维：ctx.use 依赖驱动 + 代理约束 ----


class _DepComponent:
    name = "dep-component"
    inject = ("fs", "tools")

    def apply(self, ctx, config):
        ctx.register("ready", True)


def test_use_activates_when_dependencies_satisfied():
    ctx = Context()
    ctx.register("fs", object())
    ctx.register("tools", object())
    fiber = ctx.use(_DepComponent())
    assert fiber.active
    assert fiber.ctx.ready is True


def test_use_stays_inactive_until_dependencies_appear_then_activates():
    ctx = Context()
    fiber = ctx.use(_DepComponent())
    assert not fiber.active  # 依赖缺失 -> 不激活
    ctx.register("fs", object())  # 依赖出现 -> 通知 -> 激活
    assert not fiber.active  # tools 仍缺失
    ctx.register("tools", object())
    assert fiber.active  # 全部满足 -> 激活


def test_dependency_removal_deactivates_fiber_and_tears_down():
    ctx = Context()
    ctx.register("fs", object())
    ctx.register("tools", object())
    fiber = ctx.use(_DepComponent())
    assert fiber.active

    ctx._services.pop("tools")  # 直接移除（模拟提供方卸载）
    ctx._notify({"tools"})
    assert not fiber.active  # 依赖消失 -> 停用 + teardown
    with pytest.raises(AttributeError):
        _ = fiber.ctx.ready


def test_use_proxy_restricts_undeclared_access():
    """论文代理强制：组件只能访问 inject 声明的依赖，未声明访问抛错。"""
    ctx = Context()
    ctx.register("fs", object())
    ctx.register("secret", object())
    fiber = ctx.use(_DepComponent())
    assert fiber.ctx.fs is not None  # 已声明且已注册 -> 可访问
    with pytest.raises(ServiceNotFound):
        _ = fiber.ctx.tools  # 已声明但未注册 -> 解析失败
    with pytest.raises(ServiceNotFound):
        _ = fiber.ctx.secret  # 未声明 -> 代理拒绝


def test_use_unloads_fiber_when_host_tears_down():
    ctx = Context()
    ctx.register("fs", object())
    ctx.register("tools", object())
    fiber = ctx.use(_DepComponent())
    assert fiber.active
    ctx._teardown()  # 宿主清理 -> 子 fiber 随之卸载
    assert fiber.disposed
