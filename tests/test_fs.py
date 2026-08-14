"""F5 文件系统能力缝：接口 + LocalFS + SandboxFS + tool-fs 消费者。"""

from __future__ import annotations

import pytest

from python_cordis import LocalFS, SandboxFS
from python_cordis.seams.fs import NotATextFileError, PathEscapeError, tool_fs


def test_write_read_roundtrip(tmp_path):
    fs = LocalFS(cwd=tmp_path)
    fs.write("a.txt", "hello")
    assert fs.read("a.txt") == "hello"
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"


def test_write_is_atomic_no_tmp_leftover(tmp_path):
    fs = LocalFS(cwd=tmp_path)
    fs.write("a.txt", "x" * 1000)
    assert (tmp_path / "a.txt").exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_read_rejects_binary(tmp_path):
    fs = LocalFS(cwd=tmp_path)
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(NotATextFileError):
        fs.read("bin.dat")


def test_relative_paths_resolved_against_cwd(tmp_path):
    fs = LocalFS(cwd=tmp_path)
    fs.write("sub/a.txt", "hi")  # 自动创建父目录
    assert (tmp_path / "sub" / "a.txt").exists()
    assert fs.read("sub/a.txt") == "hi"


def test_edit_text_single_replacement(tmp_path):
    fs = LocalFS(cwd=tmp_path)
    fs.write("a.txt", "foo bar foo")
    assert fs.edit_text("a.txt", "foo", "baz", 1) is True
    assert fs.read("a.txt") == "baz bar foo"


def test_edit_text_no_match_returns_false(tmp_path):
    fs = LocalFS(cwd=tmp_path)
    fs.write("a.txt", "abc")
    assert fs.edit_text("a.txt", "zzz", "x") is False
    assert fs.read("a.txt") == "abc"


def test_stat_and_list(tmp_path):
    fs = LocalFS(cwd=tmp_path)
    fs.write("a.txt", "hi")
    st = fs.stat("a.txt")
    assert st["size"] == 2
    assert fs.list() == ["a.txt"]


def test_tool_fs_consumer_works_over_interface(tmp_path):
    fs = LocalFS(cwd=tmp_path)
    tools = tool_fs(fs)
    tools["write_file"](path="a.txt", content="hi")
    assert tools["read_file"](path="a.txt") == {"content": "hi"}
    assert tools["list_dir"]() == {"entries": ["a.txt"]}


# ---- F5.3 SandboxFS：路径 containment ----

def test_sandbox_legal_paths_match_localfs(tmp_path):
    root = tmp_path / "box"
    root.mkdir()
    fs = SandboxFS(root)
    fs.write("a.txt", "hello")
    assert fs.read("a.txt") == "hello"
    assert fs.edit_text("a.txt", "hello", "hi") is True
    assert fs.read("a.txt") == "hi"
    assert fs.list() == ["a.txt"]
    st = fs.stat("a.txt")
    assert st["size"] == 2
    assert (root / "a.txt").exists()  # 只落在沙箱根内


def test_sandbox_rejects_parent_traversal(tmp_path):
    root = tmp_path / "box"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("top-secret", encoding="utf-8")
    fs = SandboxFS(root)
    with pytest.raises(PathEscapeError):
        fs.read("../secret.txt")
    with pytest.raises(PathEscapeError):
        fs.write("../../escaped.txt", "nope")
    with pytest.raises(PathEscapeError):
        fs.edit_text("sub/../../secret.txt", "x", "y")


def test_sandbox_rejects_absolute_path_outside_root(tmp_path):
    root = tmp_path / "box"
    root.mkdir()
    fs = SandboxFS(root)
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(PathEscapeError):
        fs.read(outside)
    with pytest.raises(PathEscapeError):
        fs.write(outside, "y")
    assert outside.read_text(encoding="utf-8") == "x"  # 未被触碰


def test_sandbox_accepts_absolute_path_inside_root(tmp_path):
    root = tmp_path / "box"
    root.mkdir()
    fs = SandboxFS(root)
    fs.write(root / "a.txt", "ok")
    assert fs.read(root / "a.txt") == "ok"
