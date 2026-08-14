"""End-to-end demo: fs seam + approval middleware + tool pipeline.

Run:  python examples/demo.py
Expected flow: write a file -> read it back -> a "dangerous" write is vetoed
by the approval middleware -> list the workdir.

P2 additions: structured lifecycle logging (F10.1) prints Fiber start/stop
events, and the entry-point plugin (F11.2) auto-discovered via
``load_entry_points`` tags the ``read_file`` result with ``demo: seen``.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from python_cordis import (
    Context,
    Fiber,
    HookRegistry,
    LocalFS,
    REJECT,
    ToolRegistry,
    setup_lifecycle_logging,
)
from python_cordis.core.hook import hookimpl
from python_cordis.seams import pipeline
from python_cordis.seams.fs import tool_fs


class ApprovalMiddleware:
    """A plain plugin: veto dangerous writes in the pre_execute hook."""

    @hookimpl
    def tools_pre_execute(self, tool: str, request: dict, next) -> object:
        if tool == "write_file" and "danger" in str(request.get("content", "")):
            return REJECT
        return next()


def _enable_lifecycle_logging() -> None:
    """Print Fiber lifecycle events as structured key=value records (F10.1)."""
    logger = logging.getLogger("python_cordis.lifecycle")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(levelname)s event=%(event)s fiber=%(fiber)s")
    )
    logger.addHandler(handler)


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="python-cordis-demo-"))
    print(f"workdir: {work}\n")

    # 1. Kernel: hooks + context + fiber (lifecycle events enabled)
    hooks = HookRegistry()
    hooks.add_spec(pipeline)
    _enable_lifecycle_logging()
    setup_lifecycle_logging(hooks)  # F10.1: 生命周期 -> 结构化日志
    ctx = Context()
    fiber = Fiber(ctx, hooks=hooks).start()  # 打印 fiber_started

    # 2. fs capability seam (interface + provider + consumer)
    fs = LocalFS(cwd=work)
    ctx.register("fs", fs)
    tools = ToolRegistry(hooks)
    for name, fn in tool_fs(fs).items():
        tools.register(name, fn)
    print(f"registered tools: {tools.list()}\n")

    # 3. approval middleware (a plain plugin) + entry-point plugin (F11.2)
    hooks.register(ApprovalMiddleware())
    loaded = hooks.load_entry_points("python_cordis.plugins")  # 自动发现 demo-plugin
    print(f"entry-point plugins loaded: {loaded}\n")

    # 4. Drive the pipeline
    print("write_file(a.txt):", tools.run("write_file", path="a.txt", content="hello python-cordis"))
    print("read_file(a.txt): ", tools.run("read_file", path="a.txt"))  # 结果带 demo: seen
    print("write_file(b.txt):", tools.run("write_file", path="b.txt", content="danger forbidden!"))
    print("list_dir():        ", tools.run("list_dir"))

    # 5. Cleanup
    fiber.stop()  # 打印 fiber_stopped
    print("\nfiber stopped.")


if __name__ == "__main__":
    main()
