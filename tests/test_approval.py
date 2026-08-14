"""F17 人机协同工具审批（HITL）：审批插件 / 批准执行 / 拒绝阻断 / 超时安全默认。

覆盖 F17.1 的验收标准：工具调用产生 ``tool.approve`` 的 ASK 且 rpc_id 双向关联、
批准后工具继续执行、拒绝后被 ``REJECT`` 阻断、ASK 超时默认拒绝、卸载后钩子不再触发。
"""

from __future__ import annotations

from python_cordis import (
    APPROVE_METHOD,
    Context,
    HookRegistry,
    REJECT,
    RpcResult,
    ServerRequest,
    ToolRegistry,
)
from python_cordis.contrib.approval import ApprovalPlugin
from python_cordis.contrib.web_server import MethodKind, RpcRegistry
from python_cordis.seams import pipeline


def make_rig(decision: bool | None = None) -> tuple[HookRegistry, ToolRegistry, RpcRegistry, list[ServerRequest]]:
    """A hooks + tools rig with an approval plugin and a fake frontend.

    ``decision=None`` means the frontend never responds (drives the timeout
    path); otherwise it answers every ask with ``approved=<decision>``.
    """
    hooks = HookRegistry()
    hooks.add_spec(pipeline)
    tools = ToolRegistry(hooks)
    tools.register("greet", lambda who: f"hi {who}")
    tools.register("danger", lambda: "boom")
    requests: list[ServerRequest] = []

    registry = RpcRegistry()

    def downlink(request: ServerRequest) -> None:
        requests.append(request)
        if decision is not None:
            registry.respond(
                request.rpc_id, RpcResult.success({"approved": decision})
            )

    registry.set_downlink(downlink)
    ctx = Context()
    ctx.register("rpc", registry)
    approval = ApprovalPlugin(timeout=0.2)
    approval.start(ctx, hooks=hooks)
    return hooks, tools, registry, requests


# ---- F17.1 审批插件 ----

def test_approval_approved_runs_tool():
    hooks, tools, _registry, requests = make_rig(decision=True)
    result = tools.run("greet", who="world")
    assert result["ok"]
    assert result["result"] == "hi world"
    # 工具调用产生了一次 tool.approve 的 server-request（ASK）
    assert len(requests) == 1
    assert requests[0].method == APPROVE_METHOD
    assert requests[0].params["tool"] == "greet"
    assert requests[0].params["request"] == {"who": "world"}


def test_approval_ask_rpc_id_echoed_back_by_response():
    import threading
    import time

    # decision=None：前端只收集 ASK，不应答；由本测试在 ask 阻塞期间手动应答
    _hooks, tools, registry, requests = make_rig(decision=None)
    box: dict[str, Any] = {}

    def run_tool() -> None:
        box["result"] = tools.run("greet", who="world")

    thread = threading.Thread(target=run_tool)
    thread.start()
    deadline = time.monotonic() + 2.0
    while not requests and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(requests) == 1
    ask_rpc_id = requests[0].rpc_id
    # 客户端应答回显发起方铸造的 rpc_id（跨载体关联）
    receipt = registry.respond(ask_rpc_id, RpcResult.success({"approved": True}))
    assert receipt.ok and receipt.result == {"status": "accepted", "rpc_id": ask_rpc_id}
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    # 同一 rpc_id 的应答唤醒了 ask → 批准 → 工具执行
    assert box["result"]["ok"]
    assert box["result"]["result"] == "hi world"


def test_approval_denied_rejects_tool():
    hooks, tools, _registry, _requests = make_rig(decision=False)
    result = tools.run("danger")
    assert not result["ok"]
    assert result["reason"] == "REJECT"
    assert "rejected by pre_execute" in result["error"]


def test_approval_timeout_defaults_to_reject():
    # decision=None：前端从不响应 → ASK 超时 → 默认拒绝（安全默认）
    hooks, tools, _registry, requests = make_rig(decision=None)
    result = tools.run("danger")
    assert not result["ok"]
    assert result["reason"] == "REJECT"
    # ASK 确实发出（但没有应答），工具未执行
    assert len(requests) == 1
    assert requests[0].method == APPROVE_METHOD


def test_approval_unregister_removes_hook():
    hooks, tools, _registry, requests = make_rig(decision=False)
    # 卸载审批插件后，其 tools_pre_execute 钩子不再触发
    for plugin in hooks.plugins():
        if isinstance(plugin, ApprovalPlugin):
            hooks.unregister(plugin)
    result = tools.run("danger")
    assert result["ok"]
    assert result["result"] == "boom"
    assert requests == []


def test_approval_require_predicate_filters():
    hooks = HookRegistry()
    hooks.add_spec(pipeline)
    tools = ToolRegistry(hooks)
    tools.register("danger", lambda: "boom")
    requests: list[ServerRequest] = []
    registry = RpcRegistry()
    registry.set_downlink(lambda req: requests.append(req))
    ctx = Context()
    ctx.register("rpc", registry)
    # 只对 danger 工具要求审批
    approval = ApprovalPlugin(
        require=lambda tool, request: tool == "danger",
    )
    approval.start(ctx, hooks=hooks)
    tools.run("greet", who="x")  # 不需要审批，直接执行
    assert requests == []
    result = tools.run("danger")
    assert not result["ok"]
    assert result["reason"] == "REJECT"


def test_approval_unbound_delegates_without_ask():
    # 未 start（rpc 未绑定）时直接放行，不发起 ASK
    hooks = HookRegistry()
    hooks.add_spec(pipeline)
    tools = ToolRegistry(hooks)
    tools.register("greet", lambda who: f"hi {who}")
    approval = ApprovalPlugin()
    hooks.register(approval)  # 只挂钩子，不 bind rpc
    assert approval.rpc is None
    result = tools.run("greet", who="world")
    assert result["ok"]
    assert result["result"] == "hi world"


def test_approval_agent_loop_with_approval():
    """端到端：Agent 请求工具 → 审批 → 批准后执行并回流（F17.3 单元级验证）。"""
    from python_cordis import NEXT_STEP, Session
    from python_cordis.agent.loop import Agent
    from python_cordis.seams import llm as llm_seam
    from python_cordis.seams.llm import LlmAdapter, LlmEvent
    from python_cordis.seams.pipeline import REJECT

    class ScriptedLLM(LlmAdapter):
        def __init__(self, responses):
            self._responses = list(responses)
            self.calls = 0

        def stream(self, messages, **params):
            self.calls += 1
            if self._responses:
                yield from self._responses.pop(0)
            else:
                yield from [
                    LlmEvent(llm_seam.KIND_START, {"id": "s"}),
                    LlmEvent(llm_seam.KIND_TEXT, "done"),
                    LlmEvent(llm_seam.KIND_FINISH, {"stop_reason": "stop"}),
                ]

    def tool_response(tool, args):
        return [
            LlmEvent(llm_seam.KIND_START, {"id": "s"}),
            LlmEvent(llm_seam.KIND_TOOL_CALL, {"id": "c1", "tool": tool, "args": args}),
            LlmEvent(llm_seam.KIND_FINISH, {"stop_reason": "tool_calls"}),
        ]

    hooks = HookRegistry()
    hooks.add_spec(llm_seam)
    hooks.add_spec(pipeline)
    tools = ToolRegistry(hooks)
    tools.register("add", lambda a, b: a + b)
    session = Session("s1")
    llm = ScriptedLLM([tool_response("add", {"a": 1, "b": 2})])
    agent = Agent(llm=llm, tools=tools, session=session, hooks=hooks)

    # 审批插件：批准 add 工具
    registry = RpcRegistry()
    registry.set_downlink(
        lambda req: registry.respond(req.rpc_id, RpcResult.success({"approved": True}))
    )
    ctx = Context()
    ctx.register("rpc", registry)
    ApprovalPlugin().start(ctx, hooks=hooks)

    agent.send({"role": "user", "content": "compute 1+2"})
    assert agent.run() == "completed"
    # 批准后工具执行，结果回流驱动第二次模型调用
    assert llm.calls == 2
    events = [ev.type for ev in session.events()]
    assert "tool/result" in events
    # 模型可见历史可完整还原
    msgs = session.derive_messages()
    assert msgs[-1]["role"] == "assistant"
