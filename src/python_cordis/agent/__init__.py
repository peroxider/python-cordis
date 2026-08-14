"""F12: the agent main loop.

``Inbox`` distinguishes message cadence: ``next-step`` (continue the current
turn) vs ``next-turn`` (defer to the next turn). ``Agent`` drives the
turn/step loop over a session, calling the LLM (F6 seam) and executing tools
through the F7 pipeline, with tool results refluxed as user messages.
"""

from .inbox import NEXT_STEP, NEXT_TURN, Inbox
from .loop import Agent

__all__ = ["NEXT_STEP", "NEXT_TURN", "Inbox", "Agent"]
