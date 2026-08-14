"""F16 传输/前端：四象限消息模型 / RPC 注册表 / EventBus / HTTP+WS 载体 / 传输插件。

覆盖 F16.1–F16.5 的验收标准：消息判别与 rpcId 关联、RpcResult 信封折叠、方法表
静态区分 ask/push、HTTP 上行应答、client-response 回执、WS 回放+实时+下行专用、
EventBus 线程安全广播、插件可逆启动/停止与 entry point 自动发现。
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from python_cordis import (
    Context,
    Fiber,
    HookRegistry,
    Session,
    SessionStore,
    decode_message,
    encode_message,
)
from python_cordis.contrib.web_frontend import STATIC_ROOT
from python_cordis.contrib.web_server import (
    ClientRequest,
    ClientResponse,
    EventBus,
    MethodKind,
    RpcErrorCode,
    RpcResult,
    ServerRequest,
    ServerResponse,
    WebServerPlugin,
)
from python_cordis.contrib.web_server.registry import RpcRegistry
from python_cordis.contrib.web_server.ws import EVENT_METHOD, WebSocketServer


# ---------------------------------------------------------------------------
# F16.1 传输消息模型（四象限 RPC）
# ---------------------------------------------------------------------------


def make_session(sid: str = "s1") -> Session:
    s = Session(sid)
    s.append("user/message", {"content": "hello"}, surface_op="user")
    s.append("assistant/message", {"content": "hi"}, surface_op="assistant")
    return s


def test_rpc_result_ok_roundtrip():
    envelope = RpcResult.success({"status": "ok"})
    rebuilt = RpcResult.from_dict(envelope.to_dict())
    assert rebuilt.ok
    assert rebuilt.result == {"status": "ok"}
    assert rebuilt.error is None


def test_rpc_result_error_roundtrip_carries_code_and_details():
    envelope = RpcResult.failure(
        RpcErrorCode.METHOD_NOT_FOUND, "no such method", rpc_id="abc"
    )
    rebuilt = RpcResult.from_dict(envelope.to_dict())
    assert not rebuilt.ok
    assert rebuilt.error is not None
    assert rebuilt.error["code"] == "method_not_found"
    assert rebuilt.error["rpc_id"] == "abc"


def test_four_messages_roundtrip():
    messages: list[Any] = [
        ClientRequest("client-request", "r1", "chat.send", {"text": "hi"}),
        ServerResponse("server-response", "r1", RpcResult.success("done")),
        ServerRequest("server-request", "r2", "session/event", {"session_id": "s"}),
        ClientResponse("client-response", "r2", RpcResult.success(True)),
    ]
    for msg in messages:
        rebuilt = decode_message(encode_message(msg))
        assert type(rebuilt) is type(msg)
        assert rebuilt.rpc_id == msg.rpc_id


def test_responder_echoes_initiator_rpc_id():
    request = ClientRequest("client-request", "req-42", "ping", {})
    wire = encode_message(request)
    # 响应方回显发起方铸造的 rpc_id（跨载体关联）
    response = ServerResponse("server-response", wire["rpc_id"], RpcResult.success("pong"))
    assert encode_message(response)["rpc_id"] == "req-42"


def test_decode_rejects_missing_rpc_id():
    with pytest.raises(ValueError, match="rpc_id"):
        decode_message({"kind": "client-request", "method": "x", "params": {}})


def test_decode_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unknown message kind"):
        decode_message({"kind": "teleport", "rpc_id": "r1"})


def test_decode_rejects_missing_method():
    with pytest.raises(ValueError, match="method"):
        decode_message({"kind": "client-request", "rpc_id": "r1"})


# ---------------------------------------------------------------------------
# F16.2 RpcRegistry：方法表 + 应答 + ask/respond 路由
# ---------------------------------------------------------------------------


def make_registry() -> RpcRegistry:
    registry = RpcRegistry()
    registry.register("ping", MethodKind.CALL, lambda params: "pong")
    registry.register("add", MethodKind.CALL, lambda params: int(params["a"]) + int(params["b"]))
    registry.register("danger", MethodKind.CALL, lambda params: (_ for _ in ()).throw(RuntimeError("boom")))
    registry.register("session/event", MethodKind.PUSH)
    registry.register("auth", MethodKind.ASK)
    return registry


def test_register_lookup_methods_and_disposer():
    registry = RpcRegistry()
    dispose = registry.register("a", MethodKind.CALL, lambda p: 1)
    assert registry.lookup("a") is not None
    assert "a" in registry.methods()
    dispose()
    assert registry.lookup("a") is None


def test_answer_success_envelope():
    registry = make_registry()
    response = registry.answer(ClientRequest("client-request", "r1", "add", {"a": 1, "b": 2}))
    assert response.kind == "server-response"
    assert response.result.ok
    assert response.result.result == 3
    assert response.rpc_id == "r1"


def test_answer_unknown_method_returns_coded_envelope():
    registry = make_registry()
    response = registry.answer(ClientRequest("client-request", "r1", "nope", {}))
    assert not response.result.ok
    assert response.result.error is not None
    assert response.result.error["code"] == "method_not_found"


def test_answer_wrong_quadrant_returns_invalid_method():
    registry = make_registry()
    # push 方法不允许客户端 call
    response = registry.answer(ClientRequest("client-request", "r1", "session/event", {}))
    assert not response.result.ok
    assert response.result.error is not None
    assert response.result.error["code"] == "invalid_method"


def test_answer_handler_raise_folds_into_internal():
    registry = make_registry()
    response = registry.answer(ClientRequest("client-request", "r1", "danger", {}))
    assert not response.result.ok
    assert response.result.error is not None
    assert response.result.error["code"] == "internal_error"
    assert "RuntimeError" in response.result.error["message"]


def test_push_publishes_to_downlink():
    registry = RpcRegistry()
    registry.register("session/event", MethodKind.PUSH)
    published: list[ServerRequest] = []
    registry.set_downlink(published.append)
    request = registry.push("session/event", {"session_id": "s"})
    assert request is not None
    assert request.method == "session/event"
    assert len(published) == 1


def test_push_unknown_or_wrong_kind_returns_none():
    registry = make_registry()
    assert registry.push("nope", {}) is None
    assert registry.push("ping", {}) is None  # CALL 不是 PUSH


def test_ask_respond_roundtrip():
    registry = RpcRegistry()
    registry.register("auth", MethodKind.ASK)
    published: list[ServerRequest] = []
    published_event = threading.Event()

    def record(req: ServerRequest) -> None:
        published.append(req)
        published_event.set()

    registry.set_downlink(record)
    outcomes: list[RpcResult[Any]] = []

    def responder() -> None:
        if not published_event.wait(5.0):
            return
        outcomes.append(registry.respond(published[0].rpc_id, RpcResult.success("granted")))

    thread = threading.Thread(target=responder)
    thread.start()
    ask_result = registry.ask("auth", {"user": "u"}, timeout=5.0)
    thread.join()
    assert ask_result.ok
    assert ask_result.result == "granted"


def test_ask_timeout_returns_timeout_error():
    registry = RpcRegistry()
    registry.register("auth", MethodKind.ASK)
    registry.set_downlink(lambda _: None)  # 无人应答
    result = registry.ask("auth", {}, timeout=0.1)
    assert not result.ok
    assert result.error is not None
    assert result.error["code"] == "timeout"


def test_respond_not_pending_returns_receipt():
    registry = make_registry()
    receipt = registry.respond("ghost", RpcResult.success(1))
    assert not receipt.ok
    assert receipt.error is not None
    assert receipt.error["code"] == "not_pending"


# ---------------------------------------------------------------------------
# F16.3 EventBus：线程安全广播
# ---------------------------------------------------------------------------


def test_event_bus_session_filter_and_global_stream():
    bus = EventBus()
    got_session: list[tuple[str, str]] = []
    got_global: list[tuple[str, str]] = []
    bus.subscribe("s1", lambda sid, ev: got_session.append((sid, ev.type)))
    bus.subscribe(None, lambda sid, ev: got_global.append((sid, ev.type)))
    s = make_session("s1")
    s2 = make_session("s2")
    bus.attach(s)
    bus.attach(s2)
    # attach 只订阅追加、不重放既有事件；会话订阅只收本会话，全局订阅收所有会话
    s.append("turn/end", {"reason": "completed"})
    s2.append("turn/end", {"reason": "completed"})
    assert got_session == [("s1", "turn/end")]
    assert got_global == [("s1", "turn/end"), ("s2", "turn/end")]


def test_event_bus_disposer_removes_listener():
    bus = EventBus()
    received: list[str] = []
    dispose = bus.subscribe(None, lambda sid, ev: received.append(ev.type))
    s = make_session("s1")
    bus.attach(s)
    s.append("turn/start", {"agent": "a"})
    dispose()
    s.append("turn/end", {"reason": "completed"})
    assert received == ["turn/start"]
    assert bus.subscriber_count() == 0


def test_event_bus_attach_store_follows_lifecycle():
    bus = EventBus()
    store = SessionStore()
    s1 = store.create("s1")
    dispose = bus.attach_store(store)
    received: list[tuple[str, str]] = []
    bus.subscribe(None, lambda sid, ev: received.append((sid, ev.type)))
    store.append("s1", "user/message", {"content": "a"}, surface_op="user")
    s2 = store.create("s2")  # 新会话自动 attach
    store.append("s2", "user/message", {"content": "b"}, surface_op="user")
    assert received == [("s1", "user/message"), ("s2", "user/message")]
    assert bus.attached_count() == 2
    dispose()
    assert bus.attached_count() == 0
    assert s1 is not None and s2 is not None


def test_event_bus_publish_is_thread_safe():
    bus = EventBus()
    total = 500
    delivered: list[int] = []
    lock = threading.Lock()

    def record(_sid: str, _ev: object) -> None:
        with lock:
            delivered.append(1)

    bus.subscribe(None, record)
    s = make_session("s1")
    bus.attach(s)

    def publisher() -> None:
        for _ in range(total):
            s.append("chunk", {"n": 1})

    threads = [threading.Thread(target=publisher) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(delivered) == total * 4


# ---------------------------------------------------------------------------
# F16.2 HTTP 上行服务
# ---------------------------------------------------------------------------


def _post_json(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_http_api_call_returns_server_response():
    registry = make_registry()
    http = _start_http(registry)
    try:
        status, body = _post_json(
            f"http://127.0.0.1:{http.bound_port}/api/add",
            {"kind": "client-request", "rpc_id": "r9", "method": "add", "params": {"a": 2, "b": 3}},
        )
        assert status == 200
        assert body["kind"] == "server-response"
        assert body["rpc_id"] == "r9"
        assert body["result"] == {"ok": True, "result": 5, "error": None}
    finally:
        http.stop()


def test_http_api_unknown_method_returns_coded_error():
    registry = make_registry()
    http = _start_http(registry)
    try:
        status, body = _post_json(
            f"http://127.0.0.1:{http.bound_port}/api/nope",
            {"kind": "client-request", "rpc_id": "r1", "method": "nope", "params": {}},
        )
        assert status == 200  # 方法级结果仍为 200，错误折叠进信封
        assert body["result"]["ok"] is False
        assert body["result"]["error"]["code"] == "method_not_found"
    finally:
        http.stop()


def test_http_api_invalid_body_returns_400():
    registry = make_registry()
    http = _start_http(registry)
    try:
        status, body = _post_json(
            f"http://127.0.0.1:{http.bound_port}/api/ping", {"kind": "nope", "rpc_id": "r1"}
        )
        assert status == 400
        assert body["ok"] is False
        assert body["error"]["code"] == "invalid_request"
    finally:
        http.stop()


def test_http_respond_receipt_accepted():
    registry = RpcRegistry()
    registry.register("auth", MethodKind.ASK)
    published: list[ServerRequest] = []
    published_event = threading.Event()

    def record(req: ServerRequest) -> None:
        published.append(req)
        published_event.set()

    registry.set_downlink(record)
    http = _start_http(registry)
    outcomes: list[RpcResult[Any]] = []

    def ask_in_thread() -> None:
        outcomes.append(registry.ask("auth", {"user": "u"}, timeout=5.0))

    try:
        thread = threading.Thread(target=ask_in_thread)
        thread.start()
        assert published_event.wait(5.0)  # ask 已发布到 downlink
        rpc_id = published[0].rpc_id
        status, body = _post_json(
            f"http://127.0.0.1:{http.bound_port}/api/respond",
            {"kind": "client-response", "rpc_id": rpc_id, "result": {"ok": True, "result": "granted", "error": None}},
        )
        thread.join()
        assert status == 200
        assert body["ok"] is True
        assert body["result"]["status"] == "accepted"
        assert outcomes[0].ok
        assert outcomes[0].result == "granted"
    finally:
        http.stop()


def test_http_respond_not_pending_receipt():
    registry = make_registry()
    http = _start_http(registry)
    try:
        status, body = _post_json(
            f"http://127.0.0.1:{http.bound_port}/api/respond",
            {"kind": "client-response", "rpc_id": "ghost", "result": {"ok": True, "result": None, "error": None}},
        )
        assert status == 200
        assert body["ok"] is False
        assert body["error"]["code"] == "not_pending"
    finally:
        http.stop()


def test_http_serves_index_and_static():
    registry = make_registry()
    http = _start_http(registry, static_root=STATIC_ROOT)
    try:
        status, body = _get(f"http://127.0.0.1:{http.bound_port}/")
        assert status == 200
        assert b"python-cordis" in body
        status, body = _get(f"http://127.0.0.1:{http.bound_port}/static/app.js")
        assert status == 200
        assert b"apiCall" in body
    finally:
        http.stop()


def test_http_serves_config_js_with_ws_port():
    from python_cordis.contrib.web_server.http import HttpServer

    registry = make_registry()
    http = HttpServer(registry)
    http.ws_port = 43210  # 插件在 start() 前设置（启动时拷到 server）
    http.start()
    try:
        status, body = _get(f"http://127.0.0.1:{http.bound_port}/config.js")
        assert status == 200
        assert body.decode("utf-8").strip() == "window.WS_PORT = 43210;"
    finally:
        http.stop()


def _start_http(registry: RpcRegistry, static_root=None):
    from python_cordis.contrib.web_server.http import HttpServer

    http = HttpServer(registry, static_root=static_root)
    http.start()
    return http


# ---------------------------------------------------------------------------
# F16.3 WebSocket 下行服务
# ---------------------------------------------------------------------------


def _start_ws(bus: EventBus, sessions: SessionStore) -> WebSocketServer:
    ws = WebSocketServer(bus, sessions)
    ws.start()
    return ws


def test_ws_replays_then_pushes_realtime():
    bus = EventBus()
    store = SessionStore()
    # 会话必须经 store 创建并持有事件：回放读 store，实时推送经 bus 关联到同一对象
    session = store.create("s1")
    session.append("user/message", {"content": "hello"}, surface_op="user")
    session.append("assistant/message", {"content": "hi"}, surface_op="assistant")
    bus.attach_store(store)
    ws = _start_ws(bus, store)
    try:
        with connect(f"ws://127.0.0.1:{ws.bound_port}/ws?session_id=s1") as conn:
            # 1) 既有事件回放
            replay = [json.loads(conn.recv()) for _ in range(2)]
            assert [m["method"] for m in replay] == [EVENT_METHOD, EVENT_METHOD]
            assert [m["params"]["event"]["seq"] for m in replay] == [0, 1]
            assert replay[0]["params"]["event"]["data"]["content"] == "hello"
            # 2) 实时追加
            session.append("user/message", {"content": "again"}, surface_op="user")
            pushed = json.loads(conn.recv())
            assert pushed["params"]["event"]["seq"] == 2
            assert pushed["params"]["event"]["data"]["content"] == "again"
    finally:
        ws.stop()


def test_ws_rejects_client_message_with_1008():
    bus = EventBus()
    store = SessionStore()
    store.create("s1")
    bus.attach_store(store)
    ws = _start_ws(bus, store)
    try:
        with connect(f"ws://127.0.0.1:{ws.bound_port}/ws?session_id=s1") as conn:
            conn.send("up")  # 下行专用：上行消息为协议违规
            with pytest.raises(ConnectionClosed) as excinfo:
                conn.recv()
            assert excinfo.value.rcvd.code == 1008
    finally:
        ws.stop()


def test_ws_unknown_session_closed_with_1008():
    bus = EventBus()
    store = SessionStore()
    bus.attach_store(store)
    ws = _start_ws(bus, store)
    try:
        with connect(f"ws://127.0.0.1:{ws.bound_port}/ws?session_id=ghost") as conn:
            with pytest.raises(ConnectionClosed) as excinfo:
                conn.recv()
            assert excinfo.value.rcvd.code == 1008
    finally:
        ws.stop()


def test_ws_stop_releases_and_restarts():
    bus = EventBus()
    store = SessionStore()
    store.create("s1")
    bus.attach_store(store)
    ws = _start_ws(bus, store)
    port1 = ws.bound_port
    ws.stop()
    assert not ws.running
    # 可重启（端口释放后可再次绑定）
    ws.start()
    assert ws.running
    ws.stop()


# ---------------------------------------------------------------------------
# F16.4 传输插件（可逆 + entry point）
# ---------------------------------------------------------------------------


def _start_plugin() -> tuple[Context, Fiber, WebServerPlugin]:
    ctx = Context()
    ctx.register("sessions", SessionStore())
    plugin = WebServerPlugin()
    plugin.start(ctx)
    fiber = Fiber(ctx).start()
    return ctx, fiber, plugin


def test_plugin_registers_services_via_ctx():
    ctx, fiber, plugin = _start_plugin()
    try:
        assert ctx.rpc is plugin.registry
        assert ctx.events is plugin.bus
        assert ctx.web is plugin
        assert ctx.sessions is not None
    finally:
        fiber.stop()


def test_plugin_stop_is_reversible_and_releases_ports():
    ctx, fiber, plugin = _start_plugin()
    http_port = plugin.http_port
    ws_port = plugin.ws_port
    assert http_port > 0 and ws_port > 0
    fiber.stop()
    # 逆序清理后服务不再可用，端口释放（可被再次绑定）
    assert not plugin._ws.running
    assert not plugin._http.running


def test_plugin_start_is_idempotent():
    ctx = Context()
    ctx.register("sessions", SessionStore())
    plugin = WebServerPlugin()
    fiber = Fiber(ctx).start()
    try:
        first = plugin.start(ctx)
        again = plugin.start(ctx)
        assert again is first
    finally:
        fiber.stop()


def test_plugin_binds_http_on_fixed_port_ws_on_ephemeral():
    # 回归：固定端口只给 HTTP，WS 用临时端口并经 /config.js 暴露——
    # 两个载体共享同一端口必然导致第二次绑定失败（demo 崩溃场景）。
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    fixed = sock.getsockname()[1]
    sock.close()
    ctx = Context()
    ctx.register("sessions", SessionStore())
    plugin = WebServerPlugin(port=fixed)
    plugin.start(ctx)
    fiber = Fiber(ctx).start()
    try:
        assert plugin.http_port == fixed
        assert plugin.ws_port not in (None, fixed)
        status, body = _get(f"http://127.0.0.1:{fixed}/config.js")
        assert status == 200
        assert body.decode("utf-8").strip() == f"window.WS_PORT = {plugin.ws_port};"
    finally:
        fiber.stop()


def test_entry_point_discovers_web_server_without_starting():
    hooks = HookRegistry()
    count = hooks.load_entry_points("python_cordis.plugins")
    names = [getattr(p, "name", "") for p in hooks.plugins()]
    assert count >= 2
    assert "web-server" in names
    assert "demo-plugin" in names
