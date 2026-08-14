"""F11.2: an example plugin discovered via setuptools entry points.

This module is registered in ``pyproject.toml`` under the
``python_cordis.plugins`` entry-point group (``demo-plugin``). After
``pip install -e .``, ``HookRegistry.load_entry_points()`` auto-discovers it
and its hookimpl fires — no explicit ``register()`` call needed (F1.1b).

It is an observation middleware: it tags every ``read_file`` tool result, so
you can see the plugin is live in the demo output.
"""

from __future__ import annotations

from typing import Any

from ..core.hook import hookimpl

__all__ = ["plugin"]


class DemoPlugin:
    """A plain plugin: observe the tool pipeline via ``tools_post_execute``."""

    name = "demo-plugin"

    @hookimpl
    def tools_post_execute(
        self, tool: str, request: dict[str, Any], result: Any, next: Any
    ) -> Any:
        if tool == "read_file" and isinstance(result, dict):
            return {**result, "demo": "seen"}  # tag the result, then stop
        return next()


plugin = DemoPlugin()
