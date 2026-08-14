"""F12 Agent 主循环：Inbox / turn-step 驱动 / 工具回流 / 终止。"""

from __future__ import annotations

from python_cordis import (
    NEXT_STEP,
    NEXT_TURN,
    HookRegistry,
    Inbox,
    REJECT,
    Session,
    ToolRegistry,
)
from python_cordis.agent.loop import Agent
from python_cordis.core.hook import hookimpl
from python_cordis.seams import llm as llm_seam
from python_cordis.seams import pipeline
from python_cordis.seams.llm import LlmAdapter, LlmEvent


class ScriptedLLM(LlmAdapter):
    """按脚本逐次返回事件序列；脚本耗尽后回退为纯文本响应。"""

    def __init__(self, responses: list[list[LlmEvent]]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def stream(self, messages: list[dict], **params):
        self.calls += 1
        if self._responses:
            yield from self._responses.pop(0)
        else:
            yield from text_response("done")


def text_response(content: str = "done") -> list[LlmEvent]:
    return [
        LlmEvent(llm_seam.KIND_START, {"id": "s"}),
        LlmEvent(llm_seam.KIND_TEXT, content),
        LlmEvent(llm_seam.KIND_USAGE, {"prompt_tokens": 0, "completion_tokens": 0}),
        LlmEvent(llm_seam.KIND_FINISH, {"stop_reason": "stop"}),
    ]


def tool_response(tool: str, args: dict, call_id: str = "call-1") -> list[LlmEvent]:
    return [
        LlmEvent(llm_seam.KIND_START, {"id": "s"}),
        LlmEvent(llm_seam.KIND_TOOL_CALL, {"id": call_id, "tool": tool, "args": args}),
        LlmEvent(llm_seam.KIND_USAGE, {"prompt_tokens": 0, "completion_tokens": 0}),
        LlmEvent(llm_seam.KIND_FINISH, {"stop_reason": "tool_calls"}),
    ]


def make_agent(
    llm,
    *,
    hooks: HookRegistry | None = None,
    tools: ToolRegistry | None = None,
    session: Session | None = None,
    max_steps: int = 10,
) -> Agent:
    hooks = hooks if hooks is not None else HookRegistry()
    hooks.add_spec(llm_seam)
    hooks.add_spec(pipeline)
    tools = tools if tools is not None else ToolRegistry(hooks)
    session = session if session is not None else Session("s1")
    return Agent(
        llm=llm, tools=tools, session=session, hooks=hooks, max_steps=max_steps
    )


# ---- F12.1 Inbox ----

def test_inbox_send_claim_next_step():
    inbox = Inbox()
    inbox.send({"role": "user", "content": "hi"})
    assert inbox.has_pending
    assert inbox.claim(NEXT_STEP) == {"role": "user", "content": "hi"}
    assert not inbox.has_pending


def test_inbox_empty_claim_returns_none():
    inbox = Inbox()
    assert inbox.claim(NEXT_STEP) is None
    assert inbox.claim(NEXT_TURN) is None
    assert not inbox.has_pending
    assert inbox.size() == 0


def test_inbox_tool_result_reflux_as_user_to_next_step():
    inbox = Inbox()
    # 工具结果以 user 角色追加到 next-step（Agent 回流逻辑使用）
    inbox.send({"role": "user", "content": "tool add returned: 3"}, NEXT_STEP)
    msg = inbox.claim(NEXT_STEP)
    assert msg["role"] == "user"
    assert "tool add returned" in msg["content"]


# ---- F12.2 turn / step 驱动 ----

def test_run_produces_turn_boundaries_and_completes():
    agent = make_agent(ScriptedLLM([text_response("hi there")]))
    agent.send({"role": "user", "content": "hello"})
    assert agent.run() == "completed"
    types = [ev.type for ev in agent.session.events()]
    # 一次对话产生一对 turn/start…turn/end
    assert types.count("turn/start") == 1
    assert types.count("turn/end") == 1
    # 边界嵌套正确：turn/start 在最前，turn/end 在最后
    assert types[0] == "turn/start"
    assert types[-1] == "turn/end"
    assert "step/start" in types and "step/end" in types
    # 模型无工具调用 → turn 以 completed 结束
    turn_end = [ev for ev in agent.session.events() if ev.type == "turn/end"][0]
    assert turn_end.data["reason"] == "completed"


def test_run_with_empty_inbox_returns_completed():
    agent = make_agent(ScriptedLLM([]))
    assert agent.run() == "completed"
    assert agent.session.length == 0


# ---- F12.3 工具结果回流 ----

def test_tool_result_reflux_drives_next_step():
    hooks = HookRegistry()
    hooks.add_spec(pipeline)
    tools = ToolRegistry(hooks)
    tools.register("add", lambda a, b: a + b)
    llm = ScriptedLLM(
        [
            tool_response("add", {"a": 1, "b": 2}, call_id="call-1"),
            text_response("the sum is 3"),
        ]
    )
    agent = make_agent(llm, hooks=hooks, tools=tools)
    agent.send({"role": "user", "content": "compute 1+2"})
    assert agent.run() == "completed"
    # 结果回流 inbox 后 agent 继续下一 step，无需外部介入
    assert llm.calls == 2
    events = agent.session.events()
    types = [ev.type for ev in events]
    assert types.count("turn/start") == 1
    assert types.count("step/start") == 2
    # 工具执行结果出现在日志中且可溯源到其调用
    tool_results = [ev for ev in events if ev.type == "tool/result"]
    assert len(tool_results) == 1
    assistant_seqs = [ev.seq for ev in events if ev.type == "assistant/message"]
    assert tool_results[0].source_seqs == (assistant_seqs[0],)
    # 模型可见历史可完整还原
    msgs = agent.session.derive_messages()
    assert msgs[-1]["role"] == "assistant"
    assert msgs[-1]["content"] == "the sum is 3"


# ---- F12.4 循环终止 ----

def test_run_returns_blocked_when_tool_rejected():
    hooks = HookRegistry()
    hooks.add_spec(llm_seam)
    hooks.add_spec(pipeline)
    tools = ToolRegistry(hooks)
    tools.register("danger", lambda: "boom")

    class Veto:
        @hookimpl
        def tools_pre_execute(self, tool, request, next):
            if tool == "danger":
                return REJECT
            return next()

    hooks.register(Veto())
    llm = ScriptedLLM([tool_response("danger", {})])
    agent = make_agent(llm, hooks=hooks, tools=tools)
    agent.send({"role": "user", "content": "go"})
    assert agent.run() == "blocked"


def test_run_returns_error_on_model_failure():
    llm = ScriptedLLM(
        [[LlmEvent(llm_seam.KIND_FAILURE, {"error": "boom", "type": "RuntimeError"})]]
    )
    agent = make_agent(llm)
    agent.send({"role": "user", "content": "hi"})
    assert agent.run() == "error"


def test_run_returns_max_tokens_when_budget_exhausted():
    hooks = HookRegistry()
    hooks.add_spec(pipeline)
    tools = ToolRegistry(hooks)
    tools.register("spin", lambda: True)
    llm = ScriptedLLM([tool_response("spin", {}) for _ in range(20)])
    agent = make_agent(llm, hooks=hooks, tools=tools, max_steps=2)
    agent.send({"role": "user", "content": "loop"})
    assert agent.run() == "max-tokens"
