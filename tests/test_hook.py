"""F1 插件系统：注册/卸载、四种调用模式。"""

from __future__ import annotations

import pytest

from python_cordis.core.hook import HookError, HookRegistry, hookimpl, hookspec


@hookspec
def on_emit(name, next): ...


@hookspec
def on_parallel(x): ...


@hookspec(firstresult=True)
def on_bail(x): ...


@hookspec
def on_waterfall(value, next): ...


def new_registry() -> HookRegistry:
    reg = HookRegistry()
    reg.add_spec(__import__(__name__, fromlist=["x"]))
    return reg


# ---- F1.1 注册与发现 ----

def test_register_fires_immediately():
    reg = new_registry()
    calls = []

    class P:
        @hookimpl
        def on_emit(self, name, next):
            calls.append(name)
            return next()

    reg.register(P())
    reg.emit("on_emit", name="hello")
    assert calls == ["hello"]


def test_register_returns_idempotent_disposer():
    reg = new_registry()
    calls = []

    class P:
        @hookimpl
        def on_emit(self, name, next):
            calls.append(name)
            return next()

    dispose = reg.register(P())
    reg.emit("on_emit", name="a")
    dispose()
    dispose()  # 幂等，无副作用
    reg.emit("on_emit", name="b")
    assert calls == ["a"]


def test_duplicate_register_is_noop():
    reg = new_registry()
    calls = []

    class P:
        @hookimpl
        def on_emit(self, name, next):
            calls.append(name)
            return next()

    p = P()
    reg.register(p)
    reg.register(p)  # 重复注册不产生双份
    reg.emit("on_emit", name="x")
    assert len(calls) == 1


def test_unregister_stops_hooks():
    reg = new_registry()
    calls = []

    class P:
        @hookimpl
        def on_emit(self, name, next):
            calls.append(name)
            return next()

    reg.register(P())
    reg.emit("on_emit", name="before")
    for plugin in reg.plugins():
        reg.unregister(plugin)
    reg.emit("on_emit", name="after")
    assert calls == ["before"]


# ---- F1.2 四种调用模式 ----

def test_emit_returns_all_results():
    reg = new_registry()

    class A:
        @hookimpl
        def on_parallel(self, x):
            return x + 1

    class B:
        @hookimpl
        def on_parallel(self, x):
            return x + 2

    reg.register(A())
    reg.register(B())
    results = reg.parallel("on_parallel", x=1)
    assert sorted(results) == [2, 3]


def test_bail_stops_at_first_non_none():
    reg = new_registry()

    class A:
        @hookimpl
        def on_bail(self, x):
            return None

    class B:
        @hookimpl
        def on_bail(self, x):
            return x * 2

    reg.register(A())
    reg.register(B())
    assert reg.bail("on_bail", x=3) == 6


def test_bail_requires_firstresult_spec():
    reg = new_registry()
    with pytest.raises(HookError):
        reg.bail("on_emit", name="x")


def test_waterfall_veto_without_next():
    reg = new_registry()
    calls = []

    class A:
        @hookimpl
        def on_waterfall(self, value, next):
            calls.append("a")
            return "VETOED"  # 不调 next，否决整条链

    class B:
        @hookimpl
        def on_waterfall(self, value, next):
            calls.append("b")
            return next()

    reg.register(A())
    reg.register(B())
    # pluggy 调用顺序为"后注册先调用"：B 先执行并委托，A 否决。
    result = reg.waterfall("on_waterfall", _initial="start")
    assert result == "VETOED"
    assert calls == ["b", "a"]


def test_waterfall_tail_is_reached_when_all_delegate():
    reg = new_registry()

    class B:
        @hookimpl
        def on_waterfall(self, value, next):
            return next()

    reg.register(B())
    result = reg.waterfall("on_waterfall", _initial="start", _tail=lambda: "TAIL")
    assert result == "TAIL"


def test_waterfall_no_listeners_returns_initial():
    reg = new_registry()
    assert reg.waterfall("on_waterfall", _initial="start") == "start"
