"""F7 工具执行流水线：pre → execute → post 三段瀑布。"""

from __future__ import annotations

from python_cordis import HookRegistry, REJECT, ToolRegistry
from python_cordis.core.hook import hookimpl
from python_cordis.seams import pipeline


def make_registry(*plugins) -> tuple[HookRegistry, ToolRegistry]:
    reg = HookRegistry()
    reg.add_spec(pipeline)
    tools = ToolRegistry(reg)
    tools.register("add", lambda a, b: a + b)
    tools.register("danger", lambda: "boom")
    for p in plugins:
        reg.register(p)
    return reg, tools


def test_basic_execution_passes_three_stages():
    _, tools = make_registry()
    assert tools.run("add", a=1, b=2) == {"ok": True, "result": 3}


def test_unknown_tool_reports_error():
    _, tools = make_registry()
    result = tools.run("nope")
    assert result["ok"] is False
    assert "unknown tool" in result["error"]


def test_pre_execute_can_reject():
    class Veto:
        @hookimpl
        def tools_pre_execute(self, tool, request, next):
            if tool == "danger":
                return REJECT
            return next()

    _, tools = make_registry(Veto())
    blocked = tools.run("danger")
    assert blocked["ok"] is False
    assert "rejected" in blocked["error"]
    # 其他工具不受影响
    assert tools.run("add", a=1, b=2)["ok"] is True


def test_pre_execute_vetoes_without_calling_next():
    class Veto:
        @hookimpl
        def tools_pre_execute(self, tool, request, next):
            return REJECT  # 不调 next 即否决

    _, tools = make_registry(Veto())
    assert tools.run("add", a=1, b=2)["ok"] is False


def test_post_execute_can_rewrite_result():
    class Rewrite:
        @hookimpl
        def tools_post_execute(self, tool, request, result, next):
            if tool == "add":
                return result + 100
            return next()

    _, tools = make_registry(Rewrite())
    assert tools.run("add", a=1, b=2)["result"] == 103


def test_unregister_middleware_removes_interception():
    class Veto:
        @hookimpl
        def tools_pre_execute(self, tool, request, next):
            return REJECT

    veto = Veto()
    reg, tools = make_registry(veto)
    assert tools.run("add", a=1, b=2)["ok"] is False
    reg.unregister(veto)  # 证明可逆：卸载后拦截消失
    assert tools.run("add", a=1, b=2)["ok"] is True


# ---- F6 LLM 能力缝（复用本文件的 HookRegistry 装配约定）----

from python_cordis import LlmStream, MockProvider  # noqa: E402
from python_cordis.seams import llm as llm_seam  # noqa: E402


def make_llm_stream(adapter, *plugins, **params):
    reg = HookRegistry()
    reg.add_spec(llm_seam)
    for p in plugins:
        reg.register(p)
    return reg, LlmStream(
        adapter, reg, [{"role": "user", "content": "hello world"}], **params
    )


def llm_collect(stream):
    return list(stream.run())


def test_llm_mock_provider_yields_normalized_sequence():
    events = list(MockProvider().stream([{"role": "user", "content": "hello world"}]))
    assert [e.kind for e in events] == ["start", "text", "text", "usage", "finish"]
    assert [e.data for e in events if e.kind == "text"] == ["hello", "world"]


def test_llm_mock_provider_is_deterministic():
    p = MockProvider()
    msgs = [{"role": "user", "content": "ping pong"}]
    a = [(e.kind, e.data) for e in p.stream(msgs)]
    b = [(e.kind, e.data) for e in p.stream(msgs)]
    assert a == b


def test_llm_adapter_exception_normalized_to_failure():
    class Boom:
        def stream(self, messages, **params):
            raise RuntimeError("provider exploded")
            yield  # pragma: no cover

    _, stream = make_llm_stream(Boom())
    events = llm_collect(stream)
    assert len(events) == 1
    assert events[0].kind == llm_seam.KIND_FAILURE
    assert events[0].data["error"] == "provider exploded"
    assert events[0].data["type"] == "RuntimeError"


def test_llm_request_middleware_rewrites_input():
    class Rewrite:
        @hookimpl
        def llm_request(self, request, next):
            request["messages"] = [{"role": "user", "content": "rewritten text"}]
            return next()

    _, stream = make_llm_stream(MockProvider(), Rewrite())
    texts = [e.data for e in llm_collect(stream) if e.kind == "text"]
    assert texts == ["rewritten", "text"]


def test_llm_event_middleware_observes_every_event():
    seen = []

    class Observer:
        @hookimpl
        def llm_event(self, event, next):
            seen.append(event.kind)
            return next()

    _, stream = make_llm_stream(MockProvider(), Observer())
    events = llm_collect(stream)
    assert seen == ["start", "text", "text", "usage", "finish"]
    assert seen == [e.kind for e in events]


def test_llm_event_middleware_can_drop_events():
    class DropText:
        @hookimpl
        def llm_event(self, event, next):
            if event.kind == "text":
                return None  # 丢弃
            return next()

    _, stream = make_llm_stream(MockProvider(), DropText())
    kinds = [e.kind for e in llm_collect(stream)]
    assert "text" not in kinds
    assert kinds == ["start", "usage", "finish"]
