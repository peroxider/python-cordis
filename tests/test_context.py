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
