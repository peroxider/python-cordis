"""F4 配置装配：加载、overlay 叠加、dump、interpolation。"""

from __future__ import annotations

import pytest

from python_cordis.core.config import dump, load, load_file, load_str, overlay, resolve


def test_load_str_builds_nested_config():
    cfg = load_str("a: 1\nb:\n  c: x\n")
    assert cfg.a == 1
    assert cfg.b.c == "x"


def test_load_detects_file_path(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("x: 1\n")
    assert load(path).x == 1
    assert load_file(path).x == 1


def test_overlay_later_wins_and_inserts_new_entries():
    base = load_str("a: 1\nkeep: hello\n")
    patch = load_str("a: 2\nnew: added\n")
    merged = overlay(base, patch)
    assert merged.a == 2  # 后写覆盖先写
    assert merged.keep == "hello"
    assert merged.new == "added"


def test_overlay_returns_fresh_config_not_aliasing_inputs():
    base = load_str("a: 1\n")
    merged = overlay(base)
    merged.a = 99
    assert base.a == 1  # 不别名输入


def test_dump_roundtrip():
    cfg = load_str("a: 1\n")
    text = dump(cfg)
    assert load_str(text).a == 1


def test_resolve_interpolation():
    cfg = load_str("x: 5\ny: ${x}\n")
    resolve(cfg)
    assert cfg.y == 5


def test_resolve_cycle_detected():
    cfg = load_str("a: ${b}\nb: ${a}\n")
    with pytest.raises(Exception):
        resolve(cfg)


def test_no_eval_exec_capability():
    # 需求：配置系统禁止任意代码执行——无 eval/exec 依赖，直接验证模块源码不含。
    import inspect

    src = inspect.getsource(__import__("python_cordis.core.config", fromlist=["x"]))
    assert "eval(" not in src
    assert "exec(" not in src
