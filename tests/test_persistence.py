"""F14 持久化后端：接口 / JSONL / SQLite / 协调批量写。"""

from __future__ import annotations

import time

from python_cordis import (
    JsonlSessionPersistence,
    PersistenceCoordinator,
    Session,
    SqliteSessionPersistence,
)


def make_events() -> Session:
    s = Session("s1")
    s.append("user/message", {"content": "hello"}, surface_op="user")
    s.append("assistant/message", {"content": "hi"}, surface_op="assistant")
    s.append("turn/end", {"reason": "completed"})
    return s


def append_all(backend, session, session_id: str = "s1") -> None:
    backend.create(session_id)
    for ev in session.events():
        backend.append(session_id, ev)


# ---- F14.1 接口契约 ----

def test_persistence_interface_contract():
    for method in ("create", "append", "load", "inspect", "list_sessions"):
        assert callable(getattr(JsonlSessionPersistence, method))
        assert callable(getattr(SqliteSessionPersistence, method))


# ---- F14.2 JSONL Provider ----

def test_jsonl_roundtrip(tmp_path):
    backend = JsonlSessionPersistence(tmp_path)
    s = make_events()
    append_all(backend, s)
    recovered = backend.load("s1")
    assert [e.to_dict() for e in recovered] == [e.to_dict() for e in s.events()]
    assert backend.inspect("s1")["count"] == 3
    assert backend.list_sessions() == ["s1"]


def test_jsonl_load_missing_session_is_empty(tmp_path):
    backend = JsonlSessionPersistence(tmp_path)
    assert backend.load("nope") == []
    assert backend.inspect("nope")["count"] == 0
    assert backend.list_sessions() == []


def test_jsonl_no_partial_write_residue(tmp_path):
    backend = JsonlSessionPersistence(tmp_path)
    append_all(backend, make_events())
    # 原子发布：目录中不应残留 .tmp 文件
    assert list(tmp_path.glob("*.tmp")) == []
    assert (tmp_path / "s1.jsonl").exists()


def test_jsonl_tolerates_torn_tail(tmp_path):
    backend = JsonlSessionPersistence(tmp_path)
    s = make_events()
    append_all(backend, s)
    path = tmp_path / "s1.jsonl"
    # 模拟并发写者留下的未提交尾部（半行 JSON）
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"type": "user/message", "seq": 99, ')
    recovered = backend.load("s1")
    assert [e.to_dict() for e in recovered] == [e.to_dict() for e in s.events()]


# ---- F14.3 SQLite Provider ----

def test_sqlite_roundtrip(tmp_path):
    backend = SqliteSessionPersistence(tmp_path / "db.sqlite")
    try:
        s = make_events()
        append_all(backend, s)
        recovered = backend.load("s1")
        assert [e.to_dict() for e in recovered] == [e.to_dict() for e in s.events()]
        assert backend.list_sessions() == ["s1"]
    finally:
        backend.close()


def test_sqlite_matches_jsonl(tmp_path):
    events = make_events()
    jb = JsonlSessionPersistence(tmp_path / "j")
    append_all(jb, events)
    sb = SqliteSessionPersistence(tmp_path / "s.sqlite")
    try:
        append_all(sb, events)
        assert [e.to_dict() for e in jb.load("s1")] == [e.to_dict() for e in sb.load("s1")]
    finally:
        sb.close()


# ---- F14.4 协调与批量写 ----

def test_coordinator_flush_is_barrier(tmp_path):
    backend = JsonlSessionPersistence(tmp_path)
    session = Session("s1")
    coord = PersistenceCoordinator(backend, session, delay=0.05)
    coord.append("user/message", {"content": "a"}, surface_op="user")
    coord.append("user/message", {"content": "b"}, surface_op="user")
    coord.flush()
    assert [e.data["content"] for e in backend.load("s1")] == ["a", "b"]


def test_coordinator_batch_flushes_after_delay(tmp_path):
    backend = JsonlSessionPersistence(tmp_path)
    session = Session("s1")
    coord = PersistenceCoordinator(backend, session, delay=0.01)
    for i in range(3):
        coord.append("user/message", {"content": f"m{i}"}, surface_op="user")
    # 延迟窗口触发批量落盘是异步行为：轮询等待"最终"落盘，
    # 而非依赖固定 sleep（在 coverage 等慢速环境下 sleep 会偶发失稳）。
    deadline = time.monotonic() + 5.0
    contents: list[str] = []
    while time.monotonic() < deadline:
        contents = [e.data["content"] for e in backend.load("s1")]
        if contents == ["m0", "m1", "m2"]:
            break
        time.sleep(0.01)
    assert contents == ["m0", "m1", "m2"]
    coord.close()


def test_coordinator_backend_swappable(tmp_path):
    def strip_time(events):
        # 两个后端对同一逻辑事件的记录时间不同（各自 time.time()），
        # 可互换性比较的是事件内容，而非易变的时间戳。
        return [
            {k: v for k, v in e.to_dict().items() if k != "time"}
            for e in events
        ]

    def run_with(backend):
        session = Session("s1")
        coord = PersistenceCoordinator(backend, session, delay=0.01)
        coord.append("user/message", {"content": "hello"}, surface_op="user")
        coord.append("assistant/message", {"content": "hi"}, surface_op="assistant")
        coord.flush()
        return strip_time(backend.load("s1"))

    jb = JsonlSessionPersistence(tmp_path / "j")
    sb = SqliteSessionPersistence(tmp_path / "s.sqlite")
    try:
        # 同一协调器读写路径，仅换后端，结果一致（剔除易变时间戳）
        assert run_with(jb) == run_with(sb)
    finally:
        sb.close()
