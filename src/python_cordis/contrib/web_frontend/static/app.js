// F16.5 reference client: HTTP up-link + WebSocket down-link.
// The client only talks to the transport API; it never touches kernel objects.
"use strict";

const $ = (sel) => document.querySelector(sel);

const state = { ws: null, sessionId: null };
let WS_PORT = 0; // discovered from /config.js (HTTP and WS bind separate ports)

// ---- transport API (HTTP up-link) ----

async function loadConfig() {
  try {
    const res = await fetch("/config.js");
    const text = await res.text();
    const m = text.match(/window\.WS_PORT\s*=\s*(\d+)/);
    if (m) WS_PORT = Number(m[1]);
  } catch { /* WS on the same origin when no config is advertised */ }
}

function apiCall(method, params) {
  const rpcId = crypto.randomUUID();
  return fetch(`/api/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: "client-request", rpc_id: rpcId, method, params }),
  })
    .then((r) => r.json())
    .then((msg) => (msg.kind === "server-response" ? msg.result : msg));
}

function apiRespond(rpcId, result) {
  return fetch("/api/respond", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind: "client-response", rpc_id: rpcId, result }),
  }).then((r) => r.json());
}

// ---- rendering ----

const TAGS = { "user/message": "user", "assistant/message": "assistant", "tool/result": "tool" };

function renderEvent(sessionId, event) {
  const line = document.createElement("div");
  line.className = "ev" + (TAGS[event.type] ? " surface" : "");
  const tag = document.createElement("span");
  tag.className = "tag";
  tag.textContent = `#${event.seq} ${event.type}`;
  line.appendChild(tag);
  let text = JSON.stringify(event.data);
  if (typeof event.data?.content === "string") text = event.data.content;
  if (event.type === "tool/result") text = JSON.stringify(event.data.result);
  line.appendChild(document.createTextNode(` ${sessionId} ${text}`));
  $("#log").appendChild(line);
  $("#log").scrollTop = $("#log").scrollHeight;
}

// ---- approval UI (F17: human-in-the-loop tool approval) ----

// A server-request with method "tool.approve" asks the human to approve a tool
// call. Render a card with the tool name + params, then answer via the HTTP
// up-link (client-response) so the waiting asker on the server wakes up.

function renderApproval(rpcId, params) {
  const card = document.createElement("div");
  card.className = "approval-card";
  const title = document.createElement("div");
  title.className = "a-title";
  const tool = params?.tool || "?";
  title.textContent = `审批工具调用：${tool}`;
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify(params, null, 2);
  const approve = document.createElement("button");
  approve.textContent = "批准";
  approve.onclick = () => {
    apiRespond(rpcId, { ok: true, result: { approved: true } });
    card.remove();
  };
  const deny = document.createElement("button");
  deny.textContent = "拒绝";
  deny.onclick = () => {
    apiRespond(rpcId, { ok: true, result: { approved: false } });
    card.remove();
  };
  card.append(title, pre, approve, deny);
  $("#approval").appendChild(card);
}

// ---- WS down-link ----

function connect(sessionId) {
  if (state.ws) state.ws.close();
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const host = WS_PORT ? `${location.hostname}:${WS_PORT}` : location.host;
  const ws = new WebSocket(`${proto}://${host}/ws?session_id=${sessionId}`);
  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    if (msg.kind !== "server-request") return;
    if (msg.method === "session/event") {
      renderEvent(msg.params.session_id, msg.params.event);
    } else if (msg.method === "client.echo") {
      // answer a server ask: echo the text back (client-response via HTTP up)
      apiRespond(msg.rpc_id, { ok: true, result: { echoed: msg.params.text } });
    } else if (msg.method === "tool.approve") {
      renderApproval(msg.rpc_id, msg.params);
    }
  };
  ws.onopen = () => { $("#status").textContent = `已连接 #${sessionId}`; };
  ws.onclose = () => { state.ws = null; };
  state.ws = ws;
  state.sessionId = sessionId;
}

// ---- actions ----

async function refreshSessions() {
  const res = await apiCall("session.list", {});
  const ids = res.ok ? (res.result || []) : [];
  const box = $("#sessions");
  box.innerHTML = "";
  ids.forEach((sid) => {
    const btn = document.createElement("button");
    btn.textContent = sid.slice(0, 8);
    btn.onclick = () => connect(sid);
    box.appendChild(btn);
  });
  return ids;
}

async function sendMessage() {
  const text = $("#input").value.trim();
  if (!text) return;
  $("#input").value = "";
  const res = await apiCall("session.send", { content: text });
  if (res.ok && res.result?.session_id) {
    if (state.sessionId !== res.result.session_id) connect(res.result.session_id);
  } else {
    renderEvent("-", { seq: "?", type: "error", data: res.error });
  }
  refreshSessions();
}

async function pingRoundTrip() {
  const res = await apiCall("ping", {});
  renderEvent("-", { seq: "?", type: "ping", data: res.ok ? res.result : res.error });
}

// ---- boot ----

window.addEventListener("DOMContentLoaded", async () => {
  $("#send").onclick = sendMessage;
  $("#input").addEventListener("keydown", (e) => { if (e.key === "Enter") sendMessage(); });
  $("#ping").onclick = pingRoundTrip;
  await loadConfig();
  const ids = await refreshSessions();
  if (ids.length) {
    connect(ids[ids.length - 1]); // replay the most recent session via WS
  } else {
    $("#status").textContent = "无会话，发送第一条消息";
  }
});
