"""论文 §4.2 声明式组件加载器：配置协调 + 增量 reconciliation + HMR 事务回滚。

覆盖 Loader 的三个加载能力：
- 声明式配置层（entry = module/component + config + isolate 标志）；
- 增量协调（reconcile 对新增/删除/配置变更做最小操作，未变更条目保持运行态）；
- 热模块替换（hot_reload 原地重执行模块，失败时回滚到旧组件）。
"""

from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest

from python_cordis import Context, Loader, LoaderError


# ---- 组件（声明 inject + apply，业务无关）----


def _make_component(comp_name: str, events: list[str], *, deps: tuple[str, ...] = ()) -> type:
    """构造一个可复用的测试组件：激活/停用/apply 调用都被记录。"""

    class Component:
        name = comp_name
        inject = deps

        def apply(self, ctx: Context, config: Any) -> None:
            events.append((comp_name, "apply", config))
            if config and config.get("register"):
                ctx.register(f"svc_{comp_name}", object())
                events.append((comp_name, "registered"))

    return Component


# ---- 声明式配置层：start 实例化 + stop 全部清理 ----


def test_start_instantiates_each_entry_and_stop_disposes_all():
    ctx = Context()
    events: list[tuple[str, str, Any]] = []
    comp_a = _make_component("a", events)()

    loader = Loader(ctx)
    fibers = loader.start(
        [
            {"id": "a", "component": comp_a, "config": {"register": True}},
            {"id": "b", "component": _make_component("b", events)(), "config": None},
        ]
    )
    assert [f.component.name for f in fibers] == ["a", "b"]
    assert ("a", "apply", {"register": True}) in events
    assert ("b", "apply", None) in events
    fiber_a = loader.fibers()["a"]
    assert fiber_a.ctx.svc_a is not None  # a 的注册在其 fiber 上下文上

    loader.stop()
    assert loader.fibers() == {}
    assert fiber_a.disposed
    with pytest.raises(AttributeError):
        _ = fiber_a.ctx.svc_a  # 服务随 fiber 卸载而注销


def test_entry_without_id_uses_module_or_name():
    ctx = Context()
    comp = _make_component("comp", [])()

    loader = Loader(ctx)
    loader.start([{"component": comp}])  # 无 id：回退到组件 name
    assert "comp" in loader.fibers()


def test_entry_needing_module_or_component_fails_loud():
    loader = Loader(Context())
    with pytest.raises(LoaderError, match="needs a 'module' or 'component'"):
        loader.start([{"id": "x"}])


def test_isolate_entry_is_sealed_from_host():
    ctx = Context()
    ctx.register("host_only", 1)
    events: list[Any] = []

    comp_iso = _make_component("iso", events, deps=("host_only",))()

    loader = Loader(ctx)
    loader.start([{"id": "iso", "component": comp_iso, "isolate": True}])
    # isolate 条目看不到父级服务 -> 依赖不满足 -> 不激活
    assert not loader.fibers()["iso"].active
    assert events == []

    # 非 isolate 条目可见父级服务 -> 依赖满足 -> 激活
    comp_open = _make_component("open", events, deps=("host_only",))()
    loader.start([{"id": "open", "component": comp_open}])
    assert loader.fibers()["open"].active


# ---- 增量 reconciliation：新增 / 删除 / 仅配置变更重载 ----


def test_reconcile_adds_removes_and_reloads_only_changed_config():
    ctx = Context()
    events: list[Any] = []
    comp_a = _make_component("a", events)()
    comp_b = _make_component("b", events)()
    comp_c = _make_component("c", events)()

    loader = Loader(ctx)
    loader.reconcile(
        [
            {"id": "a", "component": comp_a, "config": {"v": 1}},
            {"id": "b", "component": comp_b},
        ]
    )
    apply_count = sum(1 for e in events if e[1] == "apply")

    # 配置变更只影响 a：b 保持运行态（不再 apply）
    loader.reconcile(
        [
            {"id": "a", "component": comp_a, "config": {"v": 2}},
            {"id": "b", "component": comp_b},
            {"id": "c", "component": comp_c},
        ]
    )
    apply_count_after = sum(1 for e in events if e[1] == "apply")
    assert apply_count_after - apply_count == 2  # a 重载 + c 新增，b 未动
    assert set(loader.fibers()) == {"a", "b", "c"}

    # 删除 b：b 被 dispose
    loader.reconcile([{"id": "a", "component": comp_a, "config": {"v": 2}}])
    assert set(loader.fibers()) == {"a"}


def test_reconcile_reloads_when_component_object_changes():
    ctx = Context()
    events: list[Any] = []
    loader = Loader(ctx)
    loader.reconcile([{"id": "a", "component": _make_component("a", events)()}])
    old_fiber = loader.fibers()["a"]

    # 同 id 换新组件对象 -> 旧 fiber 替换
    loader.reconcile([{"id": "a", "component": _make_component("a", events)()}])
    new_fiber = loader.fibers()["a"]
    assert new_fiber is not old_fiber
    assert old_fiber.disposed


# ---- HMR：原地重执行模块，失败回滚到旧组件 ----


_MODULE_V1 = """\
from python_cordis.core.context import Context

def apply(ctx: Context, config):
    ctx.register("hmr_value", "v1")
"""


_MODULE_V2 = """\
from python_cordis.core.context import Context

def apply(ctx: Context, config):
    ctx.register("hmr_value", "v2")
"""


_MODULE_BROKEN = "raise RuntimeError('boom')\n"


def _write_module(tmp_path, text: str, name: str) -> None:
    (tmp_path / f"{name}.py").write_text(text, encoding="utf-8")


def test_hot_reload_swaps_module_code_in_place(tmp_path):
    sys.path.insert(0, str(tmp_path))
    try:
        _write_module(tmp_path, _MODULE_V1, "hmr_mod")
        loader = Loader(Context())
        loader.start([{"id": "h", "module": "hmr_mod"}])
        assert loader.fibers()["h"].ctx.hmr_value == "v1"

        _write_module(tmp_path, _MODULE_V2, "hmr_mod")  # 修改源码
        assert loader.hot_reload("h") is True
        assert loader.fibers()["h"].ctx.hmr_value == "v2"  # 新代码无需重启即生效
        assert loader.errors == []
    finally:
        sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()


def test_hot_reload_failure_rolls_back_to_old_component(tmp_path):
    sys.path.insert(0, str(tmp_path))
    try:
        _write_module(tmp_path, _MODULE_V1, "hmr_broken")
        loader = Loader(Context())
        loader.start([{"id": "h", "module": "hmr_broken"}])
        assert loader.fibers()["h"].ctx.hmr_value == "v1"

        _write_module(tmp_path, _MODULE_BROKEN, "hmr_broken")  # 注入坏代码
        assert loader.hot_reload("h") is False
        assert loader.errors and "boom" in str(loader.errors[-1])
        assert loader.fibers()["h"].ctx.hmr_value == "v1"  # 回滚到旧组件
    finally:
        sys.path.remove(str(tmp_path))
        importlib.invalidate_caches()


def test_hot_reload_rejects_unloaded_or_plain_component_entry():
    ctx = Context()
    loader = Loader(ctx)
    comp = _make_component("plain", [])()

    assert loader.hot_reload("missing") is False  # 未加载
    assert "not loaded" in str(loader.errors[-1])

    loader.start([{"id": "plain", "component": comp}])  # 组件对象无 module -> 不可重载
    assert loader.hot_reload("plain") is False
    assert "no reloadable module" in str(loader.errors[-1])
