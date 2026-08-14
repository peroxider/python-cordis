"""F16.5: the reference frontend (a minimal browser client).

Ships static assets only (``static/``) — no server logic. The client talks to
the kernel exclusively through the transport layer API: HTTP up-link
(``POST /api/<method>`` for client-request / client-response) and WebSocket
down-link (server-request event stream). It never touches kernel objects
directly. The ``index.html`` / ``app.js`` are served by the transport plugin's
HTTP server at ``/``.
"""

from pathlib import Path

__all__ = ["STATIC_ROOT"]

#: Absolute path of the static assets, wired as the plugin's ``static_root``.
STATIC_ROOT = Path(__file__).parent / "static"
