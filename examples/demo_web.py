"""F16/F17 end-to-end demo: kernel + transport plugin + reference frontend + HITL approval.

Run:  python examples/demo_web.py
Then open the printed URL (default http://127.0.0.1:8765/) in a browser:
type a message and watch the event stream render in real time over
WebSocket; the "ask 往返" button exercises a server->client ask followed by
the client-response over the HTTP up-link. Send a message containing
"write a file" and a tool-approval card appears (F17): the ApprovalPlugin
asks the human over the ASK quadrant, and the tool runs only after 批准.

Flow: browser (HTTP up / WS down) -> transport plugin (EventBus + RpcRegistry)
-> kernel Agent over a SessionStore session -> events appended to the session
-> EventBus -> WebSocket -> browser renders. First message: the client
connects after the run, so the WS replays the existing events (F16.5 AC3);
later messages on an open connection are pushed in real time (F16.5 AC1).
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import uuid
import webbrowser
from typing import Any, Iterator, Mapping

from python_cordis import Context, Fiber, HookRegistry, SessionStore
from python_cordis.agent import Agent
from python_cordis.contrib.approval import ApprovalPlugin
from python_cordis.contrib.web_frontend import STATIC_ROOT
from python_cordis.contrib.web_server import MethodKind, WebServerPlugin
from python_cordis.seams import llm as llm_seam
from python_cordis.seams import pipeline
from python_cordis.seams.llm import KIND_TOOL_CALL, LlmEvent, MockProvider
from python_cordis.seams.pipeline import ToolRegistry


def _write_file(path: str, content: str) -> dict[str, Any]:
    """A tool with a real side effect, so human approval actually matters."""
    target = os.path.join(
        tempfile.gettempdir(), f"python_cordis_demo_{os.path.basename(path)}"
    )
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(content)
    return {"path": target, "bytes": len(content)}


class DemoLLM(MockProvider):
    """Offline, deterministic LLM: requests the ``write_file`` tool when the
    last user message mentions "write", otherwise echoes text like MockProvider.

    The refluxed tool result arrives as a user message beginning with
    ``tool write_file returned:``, which never matches the trigger, so the
    follow-up call echoes the outcome and the loop completes.
    """

    def stream(
        self, messages: list[dict[str, Any]], **params: Any
    ) -> Iterator[LlmEvent]:
        text = next(
            (
                str(m.get("content", ""))
                for m in reversed(messages)
                if m.get("role") == "user"
            ),
            "",
        )
        if "write" in text.lower() and not text.startswith("tool "):
            yield LlmEvent(llm_seam.KIND_START, {"id": "demo-1", "provider": "demo"})
            yield LlmEvent(
                KIND_TOOL_CALL,
                {
                    "id": "c1",
                    "tool": "write_file",
                    "args": {"path": "hello.txt", "content": "hello from python-cordis"},
                },
            )
            yield LlmEvent(llm_seam.KIND_FINISH, {"stop_reason": "tool_calls"})
            return
        yield from super().stream(messages, **params)


def main() -> None:
    # 1. kernel: hooks + context + fiber
    hooks = HookRegistry()
    hooks.add_spec(llm_seam)
    hooks.add_spec(pipeline)
    ctx = Context()
    fiber = Fiber(ctx, hooks=hooks).start()

    # 2. sessions + agent loop (deterministic offline LLM + an approvable tool)
    store = SessionStore()
    ctx.register("sessions", store)
    llm = DemoLLM()
    tools = ToolRegistry(hooks)
    tools.register("write_file", _write_file)
    agents: dict[str, Agent] = {}
    lock = threading.Lock()

    def agent_for(session_id: str) -> Agent:
        with lock:
            agent = agents.get(session_id)
            if agent is not None:
                return agent
            try:
                session = store.get(session_id)
            except KeyError:
                session = store.create(session_id)
            agent = Agent(llm=llm, tools=tools, session=session, hooks=hooks)
            agents[session_id] = agent
            return agent

    # 3. transport plugin (entry point auto-discovery would also install it)
    plugin = WebServerPlugin(host="127.0.0.1", port=8765, static_root=STATIC_ROOT)
    plugin.start(ctx)
    registry = ctx.rpc
    assert registry is not None

    # 4. human-in-the-loop approval: the ASK channel needs ctx.rpc live first
    approval = ApprovalPlugin()
    approval.start(ctx, hooks=hooks)

    # 5. kernel methods exposed over the HTTP up-link
    def session_list(_params: Mapping[str, Any]) -> Any:
        return store.list()

    def session_send(params: Mapping[str, Any]) -> Any:
        content = str(params.get("content", ""))
        if not content:
            return {"session_id": "", "reason": "empty-content"}
        existing = store.list()
        session_id = str(params.get("session_id") or (existing[-1] if existing else ""))
        if not session_id:
            session_id = uuid.uuid4().hex[:8]
        agent = agent_for(session_id)
        agent.send({"role": "user", "content": content})
        reason = agent.run()
        return {"session_id": session_id, "reason": reason}

    def ping(_params: Mapping[str, Any]) -> Any:
        return {"pong": True}

    registry.register("session.list", MethodKind.CALL, session_list)
    registry.register("session.send", MethodKind.CALL, session_send)
    registry.register("ping", MethodKind.CALL, ping)

    print(f"reference frontend : http://127.0.0.1:{plugin.http_port}/")
    print(f"ws down-link       : ws://127.0.0.1:{plugin.ws_port}/ws")
    print("methods            :", registry.methods())
    print('try               : send "write a file" to see the approval card')
    print("press Ctrl+C to stop")
    sys.stdout.flush()
    if "--no-browser" not in sys.argv:
        webbrowser.open(f"http://127.0.0.1:{plugin.http_port}/")

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        fiber.stop()  # reverses effects: HTTP stops, WS stops, bus detaches
        print("\ntransport plugin stopped; ports released.")


if __name__ == "__main__":
    main()
