"""F12.2–F12.4: the turn/step-driven agent loop.

``Agent.run()`` drives an outer turn loop; each turn runs inner steps while
the inbox has pending messages. Every step: claim a message → record
``user/message`` → call the LLM (F6 seam) → record ``assistant/message`` →
execute any tool calls through the F7 pipeline → record ``tool/result`` and
reflux the results as user messages so the loop continues without external
intervention. Turn/step boundaries are written as ``turn/start`` /
``turn/end`` / ``step/start`` / ``step/end`` events.

``run()`` returns a terminal reason: ``completed`` (inbox drained), ``blocked``
(a tool call was rejected by the pre-execute stage), ``max-tokens`` (step
budget exhausted) or ``error`` (the model failed).
"""

from __future__ import annotations

from typing import Any, Mapping

from ..core.hook import HookRegistry
from ..seams.llm import KIND_FAILURE, KIND_TEXT, KIND_TOOL_CALL, LlmAdapter, LlmStream
from ..seams.pipeline import ToolRegistry
from ..session import Session
from .inbox import NEXT_STEP, NEXT_TURN, Inbox

__all__ = ["Agent"]

END_COMPLETED = "completed"
END_BLOCKED = "blocked"
END_MAX_TOKENS = "max-tokens"
END_ERROR = "error"


class Agent:
    """Drives turns and steps over a session and an inbox."""

    def __init__(
        self,
        *,
        llm: LlmAdapter,
        tools: ToolRegistry,
        session: Session,
        hooks: HookRegistry | None = None,
        inbox: Inbox | None = None,
        max_steps: int = 10,
        name: str = "agent",
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._session = session
        self._hooks = hooks if hooks is not None else HookRegistry()
        self._inbox = inbox if inbox is not None else Inbox()
        self._max_steps = max_steps
        self._name = name

    @property
    def inbox(self) -> Inbox:
        return self._inbox

    @property
    def session(self) -> Session:
        return self._session

    def send(self, message: Mapping[str, Any], target: str = NEXT_STEP) -> None:
        """Seed the inbox (e.g. the initial user message)."""
        self._inbox.send(message, target)

    def run(self) -> str:
        """Drive turns until the inbox is empty; return the end reason."""
        while self._inbox.has_pending:
            turn_start = self._session.append("turn/start", {"agent": self._name})
            reason = self._run_turn()
            self._session.append(
                "turn/end", {"reason": reason}, source_seqs=(turn_start,)
            )
            if reason != END_COMPLETED:
                return reason
        return END_COMPLETED

    # ---- internals ----

    def _run_turn(self) -> str:
        """Run steps until the model stops requesting tools or a terminal
        reason fires; return the turn's outcome."""
        step = 0
        while self._inbox.has_pending:
            if step >= self._max_steps:
                return END_MAX_TOKENS
            step += 1
            step_start = self._session.append("step/start", {"n": step})
            msg = self._inbox.claim(NEXT_STEP)
            if msg is None:
                msg = self._inbox.claim(NEXT_TURN)
            if msg is None:
                break
            self._session.append(
                "user/message",
                {"content": str(msg.get("content", ""))},
                surface_op="user",
            )
            outcome = self._model_step()
            self._session.append(
                "step/end", {"status": outcome}, source_seqs=(step_start,)
            )
            if outcome != "tool":
                return outcome
        return END_COMPLETED

    def _model_step(self) -> str:
        """One model call: record the assistant message and, if the model
        requested tools, execute them and reflux results. Returns the step
        outcome (``tool`` / ``completed`` / ``blocked`` / ``error``)."""
        messages = self._session.derive_messages()
        text_parts: list[str] = []
        tool_calls: list[dict[str, object]] = []
        failed = False
        for event in LlmStream(self._llm, self._hooks, messages).run():
            if event.kind == KIND_TEXT:
                text_parts.append(str(event.data))
            elif event.kind == KIND_TOOL_CALL:
                tool_calls.append(dict(event.data or {}))
            elif event.kind == KIND_FAILURE:
                failed = True
        if failed:
            return END_ERROR

        data: dict[str, object] = {"content": "".join(text_parts)}
        if tool_calls:
            data["tool_calls"] = tool_calls
        assistant_seq = self._session.append(
            "assistant/message", data, surface_op="assistant"
        )
        if not tool_calls:
            return END_COMPLETED

        for call in tool_calls:
            tool = str(call.get("tool", ""))
            raw_args = call.get("args")
            params = dict(raw_args) if isinstance(raw_args, Mapping) else {}
            result = self._tools.run(tool, **params)
            self._session.append(
                "tool/result",
                {
                    "id": str(call.get("id", "")),
                    "tool": tool,
                    "result": result,
                },
                surface_op="tool",
                source_seqs=(assistant_seq,),
            )
            if not result.get("ok"):
                if result.get("reason") == "REJECT":
                    return END_BLOCKED
                return END_ERROR
            self._inbox.send(
                {"role": "user", "content": f"tool {tool} returned: {result}"},
                NEXT_STEP,
            )
        return "tool"
