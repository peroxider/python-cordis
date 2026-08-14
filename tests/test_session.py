"""F13 事件溯源会话日志：append-only 不可变日志 / surface / 重放 / SessionStore。"""

from __future__ import annotations

import pytest

from python_cordis import (
    Context,
    Session,
    SessionEvent,
    SessionNotFound,
    SessionStore,
)


def make_session() -> Session:
    s = Session("s1")
    s.append("user/message", {"content": "hello"}, surface_op="user")
    s.append("assistant/message", {"content": "hi"}, surface_op="assistant")
    return s


# ---- F13.1 append-only 不可变日志 ----

def test_append_returns_contiguous_seq():
    s = Session("s1")
    seqs = [
        s.append("user/message", {"content": f"m{i}"}, surface_op="user")
        for i in range(3)
    ]
    assert seqs == [0, 1, 2]
    assert s.length == 3


def test_mutating_input_data_does_not_affect_log():
    s = Session("s1")
    d = {"content": "original"}
    s.append("user/message", d, surface_op="user")
    d["content"] = "CHANGED"
    d["extra"] = True
    ev = s.get(0)
    assert ev.data["content"] == "original"
    assert "extra" not in ev.data


def test_log_is_append_only_snapshot():
    s = make_session()
    snapshot = s.events()
    s.append("user/message", {"content": "again"}, surface_op="user")
    assert len(snapshot) == 2  # 既有快照不受后续追加影响
    assert s.length == 3
    assert [ev.seq for ev in s.events()] == [0, 1, 2]


# ---- F13.2 模型可见即记录（surface） ----

def test_surface_event_without_marker_rejected():
    s = Session("s1")
    with pytest.raises(ValueError, match="surface_op"):
        s.append("user/message", {"content": "x"})


def test_non_surface_event_needs_no_marker():
    s = Session("s1")
    assert s.append("turn/start", {"agent": "a"}) == 0
    assert s.append("chunk", {"n": 1}) == 1


def test_derive_messages_only_surface():
    s = Session("s1")
    s.append("turn/start", {"agent": "a"})
    s.append("user/message", {"content": "hi"}, surface_op="user")
    s.append("chunk", {"t": "hi"})
    s.append("assistant/message", {"content": "yo"}, surface_op="assistant")
    s.append("turn/end", {"reason": "completed"})
    assert s.derive_messages() == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "yo"},
    ]


def test_model_visible_is_reconstructible_from_log():
    s = Session("s1")
    s.append("user/message", {"content": "q"}, surface_op="user")
    s.append(
        "assistant/message",
        {
            "content": "",
            "tool_calls": [{"id": "c1", "tool": "add", "args": {"a": 1, "b": 2}}],
        },
        surface_op="assistant",
    )
    s.append(
        "tool/result",
        {"id": "c1", "tool": "add", "result": {"ok": True, "result": 3}},
        surface_op="tool",
        source_seqs=(1,),
    )
    msgs = s.derive_messages()
    assert msgs == [
        {"role": "user", "content": "q"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "tool": "add", "args": {"a": 1, "b": 2}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true, "result": 3}'},
    ]
    # 每条模型可见内容都能从日志逐条还原（模型可见 ⟺ 已记录）
    logged = [ev.data for ev in s.events() if ev.type == "user/message"]
    assert msgs[0]["content"] in [str(d.get("content", "")) for d in logged]


# ---- F13.3 重放 ----

def test_from_events_replays_identical_history():
    s = make_session()
    rebuilt = Session.from_events("s1-rebuilt", s.events())
    assert rebuilt.derive_messages() == s.derive_messages()
    assert [ev.seq for ev in rebuilt.events()] == [0, 1]


def test_from_events_rejects_gapped_seq():
    evs = [
        SessionEvent("user/message", 0, 0.0, {"content": "x"}, "user"),
        SessionEvent("user/message", 2, 0.0, {"content": "x"}, "user"),
    ]
    with pytest.raises(ValueError, match="contiguous"):
        Session.from_events("s1", evs)


def test_from_events_rebuild_appends_contiguously():
    s = make_session()
    rebuilt = Session.from_events("s1", s.events())
    assert rebuilt.append("user/message", {"content": "next"}, surface_op="user") == 2


# ---- F13.4 会话仓库（SessionStore） ----

def test_store_registered_as_ctx_sessions():
    ctx = Context()
    store = SessionStore()
    ctx.register("sessions", store)
    session = ctx.sessions.create("sid-1")
    ctx.sessions.append("sid-1", "user/message", {"content": "hi"}, surface_op="user")
    assert session.derive_messages() == [{"role": "user", "content": "hi"}]
    assert ctx.sessions.list() == ["sid-1"]


def test_store_get_missing_raises():
    store = SessionStore()
    with pytest.raises(SessionNotFound):
        store.get("nope")


def test_store_dispose_removes_session():
    store = SessionStore()
    store.create("a")
    store.create("b")
    store.dispose("a")
    assert store.list() == ["b"]
    with pytest.raises(SessionNotFound):
        store.get("a")
