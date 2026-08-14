"""F16.3: the WebSocket downlink server.

The kernel is synchronous, so the server runs on its own asyncio event-loop
thread. A client connects to ``/ws`` with an optional ``?session_id=`` query
parameter (absent = the global stream); the server first replays the
subscribed session's existing events, then pushes real-time appends marshalled
from kernel threads onto the loop with ``loop.call_soon_threadsafe``.

The link is downlink-only: a client message is a protocol violation and the
connection is closed with code 1008 (``downlink only``). Server→client
``server-request`` messages (ask / push) are broadcast to every connection
from any thread via ``asyncio.run_coroutine_threadsafe``.
"""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from typing import Any
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from ...session import SessionEvent, SessionStore
from .events import EventBus
from .messages import ServerRequest, encode_message

__all__ = ["WebSocketServer", "EVENT_METHOD"]

EVENT_METHOD = "session/event"


class WebSocketServer:
    """A downlink-only WebSocket server on its own event-loop thread."""

    def __init__(
        self,
        bus: EventBus,
        sessions: SessionStore,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self._bus = bus
        self._sessions = sessions
        self._host = host
        self._port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: Server | None = None
        self._thread: threading.Thread | None = None
        self._paths: dict[ServerConnection, str] = {}
        self._bound_port: int | None = None

    # ---- lifecycle ----

    @property
    def bound_port(self) -> int:
        """The port the server actually bound (useful with ``port=0``)."""
        if self._bound_port is None:
            raise RuntimeError("WebSocket server is not bound")
        return self._bound_port

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout: float = 5.0) -> None:
        """Spawn the event-loop thread and wait until the socket is bound."""
        ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(ready,), name="python-cordis-ws", daemon=True
        )
        self._thread.start()
        if not ready.wait(timeout):
            raise RuntimeError("WebSocket server failed to bind")

    def stop(self, timeout: float = 5.0) -> None:
        """Close the server, its connections, and join the loop thread."""
        loop, server = self._loop, self._server
        if loop is not None and server is not None:
            loop.call_soon_threadsafe(server.close)
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        self._thread = None

    def _run(self, ready: threading.Event) -> None:
        asyncio.run(self._main(ready))

    async def _main(self, ready: threading.Event) -> None:
        self._loop = asyncio.get_running_loop()
        server = await serve(
            self._handle,
            self._host,
            self._port,
            process_request=self._capture_path,
        )
        self._server = server
        sockets = server.sockets
        if sockets:
            self._bound_port = int(sockets[0].getsockname()[1])
        ready.set()
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            pass  # stop() -> server.close() cancels serve_forever
        finally:
            self._server = None
            self._bound_port = None
            self._loop = None

    def _capture_path(
        self, connection: ServerConnection, request: Request
    ) -> Response | None:
        """Record the handshake path so the handler knows the subscription."""
        self._paths[connection] = request.path
        return None

    # ---- connection handling ----

    async def _handle(self, connection: ServerConnection) -> None:
        path = self._paths.pop(connection, "")
        session_id = _session_id_from_path(path)
        await self._downlink(connection, session_id)

    async def _downlink(
        self, connection: ServerConnection, session_id: str | None
    ) -> None:
        """Replay the subscription, then push real-time events (downlink-only)."""
        queue: asyncio.Queue[tuple[str, SessionEvent]] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _push(sid: str, ev: SessionEvent) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, (sid, ev))

        disposer = self._bus.subscribe(session_id, _push)
        last_seq = -1
        wait_closed = asyncio.ensure_future(connection.wait_closed())
        try:
            # 1) replay the subscribed session's existing events
            if session_id is not None:
                try:
                    session = self._sessions.get(session_id)
                except KeyError:
                    await connection.close(1008, f"unknown session {session_id!r}")
                    return
                for ev in session.events():
                    await connection.send(self._encode_event(session_id, ev))
                    last_seq = ev.seq
            # 2) real-time push + downlink-only guard
            while True:
                get_task = asyncio.ensure_future(queue.get())
                recv_task = asyncio.ensure_future(connection.recv())
                done, _ = await asyncio.wait(
                    {get_task, recv_task, wait_closed},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in (get_task, recv_task):
                    if task not in done:
                        task.cancel()
                if wait_closed in done:
                    break  # server shutdown / client disconnect
                if recv_task in done and recv_task.exception() is None:
                    # a real client message violates the downlink-only contract
                    await connection.close(1008, "downlink only")
                    break
                if get_task in done:
                    sid, ev = get_task.result()
                    if ev.seq > last_seq:
                        await connection.send(self._encode_event(sid, ev))
                        last_seq = ev.seq
        except ConnectionClosed:
            pass
        finally:
            if not wait_closed.done():
                wait_closed.cancel()
            disposer()

    def _encode_event(self, session_id: str, event: SessionEvent) -> str:
        """Serialize one session event as a ``session/event`` server-request."""
        message = ServerRequest(
            "server-request",
            uuid.uuid4().hex,
            EVENT_METHOD,
            {"session_id": session_id, "event": event.to_dict()},
        )
        return json.dumps(encode_message(message), ensure_ascii=False)

    # ---- server-request broadcast (ask / push) ----

    def publish(self, message: ServerRequest) -> None:
        """Broadcast a server-request to every client (thread-safe, fire-and-forget)."""
        loop, server = self._loop, self._server
        if loop is None or server is None:
            return
        payload = json.dumps(encode_message(message), ensure_ascii=False)
        future = asyncio.run_coroutine_threadsafe(
            self._broadcast(server, payload), loop
        )
        future.add_done_callback(_swallow_result)

    async def _broadcast(self, server: Server, payload: str) -> None:
        for connection in list(server.connections):
            try:
                await connection.send(payload)
            except Exception:  # noqa: BLE001  (a dead peer must not stop the pump)
                continue


def _swallow_result(future: Any) -> None:
    """Consume a fire-and-forget future so no exception is 'never retrieved'."""
    try:
        future.exception()
    except Exception:  # noqa: BLE001  (only here to keep asyncio quiet)
        pass


def _session_id_from_path(path: str) -> str | None:
    """Parse ``?session_id=`` from the handshake path; ``None`` = global stream."""
    query = parse_qs(urlsplit(path).query)
    values = query.get("session_id")
    if not values:
        return None
    return values[0]
