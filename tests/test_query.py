"""F15 会话检索：接口契约 / 文本抽取与命中 / 转义。"""

from __future__ import annotations

import pytest

from python_cordis import (
    SearchHit,
    SessionNotFound,
    SessionQueryEngine,
    SessionStore,
    InMemoryQueryEngine,
)
from python_cordis.query import extract_text


def make_store() -> SessionStore:
    store = SessionStore()
    s1 = store.create("s1")
    s1.append("turn/start", {"agent": "a"})
    s1.append("user/message", {"content": "what is the weather in Beijing"}, surface_op="user")
    s1.append("assistant/message", {"content": "it is sunny and warm"}, surface_op="assistant")
    s1.append(
        "tool/result",
        {"id": "c1", "tool": "weather", "result": {"temp": 26, "condition": "sunny"}},
        surface_op="tool",
        source_seqs=(1,),
    )
    s1.append("turn/end", {"reason": "completed"})
    s2 = store.create("s2")
    s2.append("user/message", {"content": "unrelated topic"}, surface_op="user")
    return store


# ---- F15.1 SessionQueryEngine 接口 ----

def test_query_engine_interface_contract():
    # 契约：两个抽象方法，可作为抽象基类被多个引擎实现
    assert isinstance(SessionQueryEngine, type)
    assert "search_events" in SessionQueryEngine.__abstractmethods__
    assert "search_sessions" in SessionQueryEngine.__abstractmethods__
    # InMemoryQueryEngine 是具体实现（非抽象）
    assert "search_events" not in InMemoryQueryEngine.__abstractmethods__


def test_in_memory_engine_implements_interface():
    store = SessionStore()
    assert isinstance(InMemoryQueryEngine(store), SessionQueryEngine)


# ---- F15.2 文本抽取与命中 ----

def test_search_events_hits_content_with_snippet():
    engine = InMemoryQueryEngine(make_store())
    hits = engine.search_events("beijing", "s1")
    assert len(hits) == 1
    hit = hits[0]
    assert isinstance(hit, SearchHit)
    assert hit.session_id == "s1"
    # 命中对应事件：user/message（seq=1）
    assert hit.seq == 1
    # snippet 包含查询词
    assert "beijing" in hit.snippet.lower()


def test_tool_result_contributes_text():
    engine = InMemoryQueryEngine(make_store())
    hits = engine.search_events("sunny", "s1")
    seqs = [h.seq for h in hits]
    # assistant/message（内容 sunny）与 tool/result（结果 sunny）都命中
    assert 2 in seqs and 3 in seqs


def test_structural_events_do_not_hit():
    store = make_store()
    # 在结构事件中埋词：turn/start 的 agent 名、turn/end 的 reason
    store.get("s1").append("step/start", {"n": 1, "secret_marker": "zzz-invisible"})
    engine = InMemoryQueryEngine(store)
    # zzz-invisible 只出现在结构事件 step/start 中，不应命中
    assert engine.search_events("zzz-invisible", "s1") == []
    assert engine.search_sessions("zzz-invisible") == []


def test_special_chars_escaped_no_error():
    engine = InMemoryQueryEngine(make_store())
    # 正则特殊字符应被转义，不引发解析错误；字面命中仍有效
    store = make_store()
    store.get("s1").append("user/message", {"content": "price is a+b*"}, surface_op="user")
    engine = InMemoryQueryEngine(store)
    hits = engine.search_events("a+b*", "s1")
    assert len(hits) == 1
    assert "a+b*" in hits[0].snippet


def test_search_sessions_cross_session():
    engine = InMemoryQueryEngine(make_store())
    assert engine.search_sessions("beijing") == ["s1"]
    assert engine.search_sessions("weather") == ["s1"]
    assert engine.search_sessions("unrelated") == ["s2"]


def test_search_no_hits_returns_empty():
    engine = InMemoryQueryEngine(make_store())
    assert engine.search_events("nonexistent-term", "s1") == []
    assert engine.search_sessions("nonexistent-term") == []


def test_search_events_missing_session_raises():
    engine = InMemoryQueryEngine(SessionStore())
    with pytest.raises(SessionNotFound):
        engine.search_events("x", "nope")


def test_extract_text_surface_vs_structural():
    from python_cordis import Session

    s = Session("s1")
    s.append("user/message", {"content": "q"}, surface_op="user")
    s.append("chunk", {"t": "q"})
    s.append("turn/end", {"reason": "completed"})
    events = s.events()
    # 仅 surface 事件贡献可检索文本；结构/增量事件返回 None
    assert extract_text(events[0]) == "q"
    assert extract_text(events[1]) is None
    assert extract_text(events[2]) is None
