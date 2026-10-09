"use strict";

const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const storageKey = "ssh-mcp.console.admin";
const titles = {
  servers: [
    "服务器",
    "SERVER INVENTORY",
    "管理连接目标，让 AI 在合适的服务器上工作。",
  ],
  sessions: [
    "终端会话",
    "LIVE SESSIONS",
    "查看 AI 和控制台的会话，继续操作或释放连接。",
  ],
  clients: [
    "MCP 接入",
    "CONNECT YOUR CLIENT",
    "配置一次，让你的 AI 客户端连接这些服务器。",
  ],
  activity: [
    "操作记录",
    "WORKSPACE ACTIVITY",
    "查看最近的管理操作。记录不包含命令正文和凭据。",
  ],
};
let token = "",
  epoch = 0,
  view = "servers",
  state = null,
  selected = null,
  selectedSession = null;
let search = "",
  authFilter = "all",
  client = "Codex",
  editId = null,
  editRevision = null;
let pollTimer,
  pollGeneration = 0,
  toastTimer;
const probes = new Map(),
  outputs = new Map(),
  requests = new Set();

class StaleRequest extends Error {}
function notify(message, error = false) {
  clearTimeout(toastTimer);
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.hidden = false;
  toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 5500);
}
async function api(path, method = "GET", body) {
  const currentEpoch = epoch,
    controller = new AbortController();
  requests.add(controller);
  const timer = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch(`/admin${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
      signal: controller.signal,
    });
    if (currentEpoch !== epoch) throw new StaleRequest();
    let result;
    try {
      result = await response.json();
    } catch {
      result = {};
    }
    if (currentEpoch !== epoch) throw new StaleRequest();
    if (response.status === 401) {
      logout();
      throw new Error("管理员 Token 无效或已失效，请重新登录。");
    }
    if (!response.ok)
      throw new Error(
        result.error || `请求未完成（${response.status}），请稍后重试。`,
      );
    return result;
  } catch (error) {
    if (currentEpoch !== epoch && !(error.message || "").includes("Token"))
      throw new StaleRequest();
    if (error.name === "AbortError")
      throw new Error("请求超时。请检查服务状态，刷新后再决定是否重试。");
    if (error instanceof TypeError)
      throw new Error("无法连接服务。请检查网络，然后点击刷新重试。");
    throw error;
  } finally {
    clearTimeout(timer);
    requests.delete(controller);
  }
}
async function busy(button, action) {
  if (button?.disabled) return;
  if (button) button.disabled = true;
  try {
    await action();
  } catch (error) {
    if (!(error instanceof StaleRequest)) notify(error.message, true);
  } finally {
    if (button) button.disabled = false;
  }
}
function stopPolling() {
  clearTimeout(pollTimer);
  pollGeneration++;
}
function logout() {
  epoch++;
  token = "";
  stopPolling();
  requests.forEach((r) => r.abort());
  try {
    sessionStorage.removeItem(storageKey);
  } catch {
    /* storage may be disabled */
  }
  state = null;
  selected = null;
  selectedSession = null;
  probes.clear();
  outputs.clear();
  $("#page-content").replaceChildren();
  $("#admin-token").value = "";
  $("#login-view").hidden = false;
  $("#app-view").hidden = true;
  $("#logout").hidden = true;
  $("#connection-label").textContent = "尚未登录";
  $("#nav-count").textContent = "—";
  document.querySelectorAll("dialog[open]").forEach((d) => d.close());
}
async function refresh(renderPage = true) {
  state = await api("/state");
  if (!state.servers.some((s) => s.id === selected))
    selected = state.servers[0]?.id || null;
  if (!state.sessions.some((s) => s.session_id === selectedSession))
    selectedSession = state.sessions[0]?.session_id || null;
  $("#nav-count").textContent = state.servers.length;
  $("#version").textContent = `v${state.version}`;
  if (renderPage) render();
}
async function login(value, remember = false) {
  epoch++;
  token = value;
  await refresh(false);
  $("#login-error").textContent = "";
  $("#admin-token").value = "";
  if (remember) {
    try {
      sessionStorage.setItem(storageKey, token);
    } catch {
      notify("浏览器不允许保存登录状态，本次页面仍可使用。", true);
    }
  }
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  $("#logout").hidden = false;
  $("#connection-label").textContent = "管理员已连接";
  render();
}
function badge(status, text) {
  return `<span class="badge ${escapeHTML(status)}">${escapeHTML(text)}</span>`;
}
function statusBadge(id) {
  const status = probes.get(id);
  return status ? badge(status.type, status.text) : badge("", "未检测");
}
const sessionLabels = {
  running: "运行中",
  completed: "已结束",
  timed_out: "已超时",
  disconnected: "已断开",
  closed: "已关闭",
};
function sessionBadge(status) {
  return badge(
    status === "running" ? "running" : "",
    sessionLabels[status] || status,
  );
}
function render() {
  if (!state) return;
  stopPolling();
  const [title, kicker, description] = titles[view];
  $("#breadcrumb").textContent = title;
  $("#page-title").textContent = title;
  $("#page-kicker").textContent = kicker;
  $("#page-description").textContent = description;
  $("#add-server").hidden = view !== "servers";
  document
    .querySelectorAll("[data-view]")
    .forEach((b) =>
      b.setAttribute(
        "aria-current",
        b.dataset.view === view ? "page" : "false",
      ),
    );
  ({
    servers: renderServers,
    sessions: renderSessions,
    clients: renderClients,
    activity: renderActivity,
  })[view]();
}
function renderServers() {
  const running = state.sessions.filter((s) => s.status === "running").length;
  $("#page-content").innerHTML =
    `<div class="route-strip"><span>AI 客户端</span><span class="route-line"></span><b>›_ SSH MCP</b><span class="route-line"></span><span>${state.servers.length} 台服务器</span><span class="route-meta">${running} ACTIVE SESSIONS · SSH / SFTP</span></div>
    <div class="content-split"><section class="panel"><div class="panel-title"><h2>全部服务器</h2><small>${String(state.servers.length).padStart(2, "0")} SERVERS</small></div>
    <div class="toolbar"><label class="search" aria-label="搜索服务器"><span aria-hidden="true">⌕</span><input id="server-search" type="search" placeholder="搜索名称、地址或备注" value="${escapeHTML(search)}"></label><select id="auth-filter" aria-label="筛选认证方式"><option value="all">全部认证方式</option><option value="key">SSH 私钥</option><option value="password">密码认证</option></select></div><div id="server-rows"></div><div class="table-footer"><span>凭据保留在服务端</span><span>SQLite · 持久保存</span></div></section><aside><div class="panel" id="server-detail"></div><div class="help-card"><strong>把连接交给 MCP</strong>AI 通过服务器 ID 选择目标，使用通用 Shell 自主操作。实际权限由 SSH 登录账户决定。</div></aside></div>`;
  $("#auth-filter").value = authFilter;
  $("#server-search").addEventListener("input", (event) => {
    search = event.target.value;
    renderServerRows();
  });
  $("#auth-filter").addEventListener("change", (event) => {
    authFilter = event.target.value;
    renderServerRows();
  });
  renderServerRows();
  renderDetail();
}
function renderServerRows() {
  const filtered = state.servers.filter(
    (s) =>
      `${s.id} ${s.host} ${s.description}`
        .toLowerCase()
        .includes(search.toLowerCase()) &&
      (authFilter === "all" ||
        (authFilter === "key" ? !!s.private_key : !!s.password_env)),
  );
  if (!state.servers.length) {
    $("#server-rows").innerHTML =
      `<div class="empty"><span class="empty-symbol">▤</span><h3>添加第一台服务器</h3><p>配置 SSH 连接后，你的 AI 客户端就能发现它。</p><button class="primary" data-action="add">＋ 添加服务器</button></div>`;
    return;
  }
  if (!filtered.length) {
    $("#server-rows").innerHTML =
      `<div class="empty"><h3>没有匹配的服务器</h3><p>试试其他关键词，或清除筛选条件。</p><button class="secondary" data-action="clear-search">清除筛选</button></div>`;
    return;
  }
  $("#server-rows").innerHTML =
    `<div class="table-wrap"><table><thead><tr><th>服务器</th><th>连接地址</th><th>连接状态</th><th>操作</th></tr></thead><tbody>${filtered.map((s) => `<tr class="server-row ${selected === s.id ? "selected" : ""}"><td><button class="server-name" data-action="select" data-id="${escapeHTML(s.id)}" aria-pressed="${selected === s.id}"><span class="server-icon" aria-hidden="true">▤</span><span><strong>${escapeHTML(s.id)}</strong><small>${escapeHTML(s.description || "暂无备注")}</small></span></button></td><td class="address">${escapeHTML(s.host)}:${s.port}<small>${escapeHTML(s.username)} · ${s.private_key ? "SSH 私钥" : "密码认证"}</small></td><td>${statusBadge(s.id)}</td><td><button class="text-link" data-action="test" data-id="${escapeHTML(s.id)}" ${probes.get(s.id)?.type === "running" ? "disabled" : ""}>测试连接</button></td></tr>`).join("")}</tbody></table></div>`;
}
function renderDetail() {
  const s = state.servers.find((s) => s.id === selected);
  if (!s) {
    $("#server-detail").innerHTML =
      `<div class="selection-empty"><h3>连接详情</h3>添加或选择一台服务器，查看它的连接方式与会话。</div>`;
    return;
  }
  const rows = [
    ["主机地址", `${s.host}:${s.port}`],
    ["登录账户", s.username],
    [
      s.private_key ? "服务端私钥" : "密码环境变量",
      s.private_key || s.password_env,
    ],
    ["主机公钥文件", s.known_hosts],
  ];
  $("#server-detail").innerHTML =
    `<div class="detail"><div class="detail-heading"><span class="server-icon" aria-hidden="true">▤</span><div><h3>${escapeHTML(s.id)}</h3><p>${escapeHTML(s.description || "SSH 服务器")}</p></div></div><dl class="details">${rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${escapeHTML(v)}</dd></div>`).join("")}</dl><button class="primary wide" data-action="open-session" data-id="${escapeHTML(s.id)}">›_ 打开会话</button><button class="secondary wide" data-action="edit" data-id="${escapeHTML(s.id)}">编辑连接</button><div class="detail-rule"></div><div class="detail-foot">${probes.get(s.id)?.message ? escapeHTML(probes.get(s.id).message) : "测试连接只验证 SSH 登录，不执行远程命令。"}<br><button class="text-link" data-action="delete" data-id="${escapeHTML(s.id)}">移除此服务器</button></div></div>`;
}
function editServer(id = null) {
  const form = $("#server-form");
  form.reset();
  editId = id;
  editRevision = state.revision;
  const s = state.servers.find((s) => s.id === id);
  $("#server-dialog-title").textContent = s ? "编辑服务器" : "添加服务器";
  $("#server-error").textContent = "";
  form.elements.id.disabled = !!s;
  if (s) {
    [
      "id",
      "host",
      "port",
      "username",
      "description",
      "known_hosts",
      "passphrase_env",
    ].forEach((k) => {
      form.elements[k].value = s[k] || "";
    });
    form.elements.auth.value = s.private_key ? "private_key" : "password_env";
    form.elements.credential.value = s.private_key || s.password_env;
  }
  authFields();
  $("#server-dialog").showModal();
  (s ? form.elements.host : form.elements.id).focus();
}
function authFields() {
  const key = $("#server-form").elements.auth.value === "private_key";
  $("#credential-label").firstChild.textContent = key
    ? "服务端私钥路径"
    : "密码环境变量名称";
  $("#server-form").elements.credential.placeholder = key
    ? "/etc/ssh-mcp/secrets/id_ed25519"
    : "例如 STAGING_SSH_PASSWORD";
  $("#passphrase-label").hidden = !key;
}
function confirmAction(title, text) {
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title;
  $("#confirm-description").textContent = text;
  dialog.returnValue = "cancel";
  dialog.showModal();
  return new Promise((resolve) =>
    dialog.addEventListener(
      "close",
      () => resolve(dialog.returnValue === "confirm"),
      { once: true },
    ),
  );
}
function renderClients() {
  const clients = [
    ["Codex", "环境变量认证", "C"],
    ["Cursor", "远程 HTTP", "↗"],
    ["Claude Code", "远程 HTTP", "✳"],
    ["ChatGPT", "OAuth 待支持", "G"],
  ];
  const url = state.mcp_url;
  let code, filename;
  if (client === "Codex") {
    filename = "~/.codex/config.toml";
    code = `[mcp_servers.ssh]\nurl = "${url}"\nbearer_token_env_var = "SSH_MCP_TOKEN"\nstartup_timeout_sec = 20\ntool_timeout_sec = 90`;
  } else {
    filename = client === "Cursor" ? "~/.cursor/mcp.json" : ".mcp.json";
    code = JSON.stringify(
      {
        mcpServers: {
          ssh: {
            ...(client === "Claude Code" ? { type: "http" } : {}),
            url,
            headers: {
              Authorization:
                client === "Cursor"
                  ? "Bearer ${env:SSH_MCP_TOKEN}"
                  : "Bearer ${SSH_MCP_TOKEN}",
            },
          },
        },
      },
      null,
      2,
    );
  }
  $("#page-content").innerHTML =
    `<div class="client-layout"><div class="client-options" aria-label="选择 AI 客户端">${clients.map(([name, note, icon]) => `<button class="client-option" data-action="client" data-id="${name}" aria-pressed="${client === name}"><span class="client-logo" aria-hidden="true">${icon}</span><span><strong>${name}</strong><small>${note}</small></span></button>`).join("")}</div><section class="panel setup-panel"><span class="section-kicker">CLIENT CONNECTION</span><h2>连接 ${escapeHTML(client)}</h2><p class="muted">把服务器能力带到你习惯的 AI 工作流中。</p>${client === "ChatGPT" ? `<div class="callout"><strong>ChatGPT 的 OAuth 接入尚未实现</strong><p>当前服务支持 Bearer Token。ChatGPT 的远程 OAuth 流程需要后续的 OAuth 网关或原生支持。请勿通过关闭认证来接入。</p></div>` : `<div class="step"><div class="step-label"><span>1</span>确认 MCP 地址</div><div class="endpoint"><code id="endpoint-url">${escapeHTML(url)}</code><button class="text-link" data-action="copy-url">复制地址</button></div></div><div class="step"><div class="step-label"><span>2</span>添加客户端配置</div><div class="code-block"><div class="code-heading"><span>${filename}</span><button data-action="copy-config">复制配置</button></div><pre id="client-config">${escapeHTML(code)}</pre></div></div><div class="step"><div class="step-label"><span>3</span>设置 Token，然后验证连接</div><p class="note">在客户端环境中设置 <code>SSH_MCP_TOKEN</code>，使用服务端的 MCP Token，不能使用管理员 Token。重新加载客户端后，让 AI「查看我有哪些服务器」。</p></div><p class="note">配置示例不代表已在你的客户端中完成验收。远程连接请使用有效的 HTTPS 地址。</p>`}</section></div>`;
}
function renderSessions() {
  const current = state.sessions.find((s) => s.session_id === selectedSession);
  $("#page-content").innerHTML =
    `<section class="panel"><div class="session-create"><select id="session-server" aria-label="新会话的服务器">${state.servers.map((s) => `<option value="${escapeHTML(s.id)}">${escapeHTML(s.id)}</option>`).join("")}</select><button class="primary" data-action="new-session" ${state.servers.length ? "" : "disabled"}>＋ 新建会话</button></div></section><p class="note">会话与 MCP 客户端共享。服务重启后会话不恢复；控制台提供逐行 Shell 输入。</p><div class="session-layout"><section class="panel session-list">${state.sessions.length ? state.sessions.map((s) => `<button class="session-item" data-action="select-session" data-id="${escapeHTML(s.session_id)}" aria-pressed="${s.session_id === selectedSession}"><strong>${escapeHTML(s.server_id)}</strong>${sessionBadge(s.status)}<small>${escapeHTML(s.session_id.slice(0, 10))} · ${s.kind === "shell" ? "SHELL" : "COMMAND"}</small></button>`).join("") : `<div class="small-empty">还没有会话。选择一台服务器建立连接。</div>`}</section><section class="panel terminal-panel">${current ? `<div class="terminal-head"><strong>${escapeHTML(current.server_id)} / ${escapeHTML(current.session_id.slice(0, 12))}</strong><div class="inline-actions"><span id="terminal-status">${sessionBadge(current.status)}</span><button class="text-link" data-action="close-session" data-id="${escapeHTML(current.session_id)}">关闭会话</button></div></div><pre class="terminal-output" id="terminal-output" tabindex="0" aria-label="会话输出"></pre><form class="terminal-form" id="terminal-form"><input id="terminal-input" autocomplete="off" spellcheck="false" aria-label="Shell 命令" placeholder="输入命令，Enter 发送" ${current.status === "running" ? "" : "disabled"}><button class="primary" ${current.status === "running" ? "" : "disabled"}>发送</button></form><p class="terminal-note">输入会在所选远程账户下执行。全屏交互程序请使用支持 PTY 的 MCP 客户端。</p>` : `<div class="empty"><span class="empty-symbol">›_</span><h3>选择一个终端会话</h3><p>在这里读取输出并继续操作。</p></div>`}</section></div>`;
  if (current) {
    $("#terminal-output").textContent =
      outputs.get(current.session_id)?.text || "等待输出…";
    $("#terminal-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const input = $("#terminal-input"),
        value = input.value;
      if (!value.trim()) return;
      busy(event.submitter, async () => {
        await api(`/sessions/${current.session_id}/input`, "POST", {
          data: value + "\n",
        });
        input.value = "";
      });
    });
    pollSession(current.session_id, pollGeneration);
  }
}
async function pollSession(id, generation) {
  if (generation !== pollGeneration || !token) return;
  if (document.hidden) {
    pollTimer = setTimeout(() => pollSession(id, generation), 1000);
    return;
  }
  const buffer = outputs.get(id) || {
    text: "",
    stdout_cursor: 0,
    stderr_cursor: 0,
  };
  try {
    const result = await api(`/sessions/${id}/read`, "POST", {
      stdout_cursor: buffer.stdout_cursor,
      stderr_cursor: buffer.stderr_cursor,
    });
    if (generation !== pollGeneration) return;
    if (result.stdout.dropped_chars || result.stderr.dropped_chars)
      buffer.text += "\n[部分输出已超出服务端缓冲容量]\n";
    buffer.text +=
      result.stdout.text +
      (result.stderr.text ? "\n[stderr] " + result.stderr.text : "");
    buffer.text = buffer.text
      .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, "")
      .slice(-100000);
    buffer.stdout_cursor = result.stdout.cursor;
    buffer.stderr_cursor = result.stderr.cursor;
    outputs.set(id, buffer);
    const output = $("#terminal-output"),
      atBottom =
        output.scrollTop + output.clientHeight >= output.scrollHeight - 30;
    output.textContent = buffer.text || "等待输出…";
    if (atBottom) output.scrollTop = output.scrollHeight;
    $("#terminal-status").innerHTML = sessionBadge(result.status);
    if (result.status !== "running") {
      $("#terminal-input").disabled = true;
      $("#terminal-form button").disabled = true;
    }
    if (
      result.status === "running" ||
      result.stdout.has_more ||
      result.stderr.has_more
    )
      pollTimer = setTimeout(
        () => pollSession(id, generation),
        result.stdout.has_more || result.stderr.has_more ? 100 : 1000,
      );
  } catch (error) {
    if (generation === pollGeneration && !(error instanceof StaleRequest))
      notify(`${error.message} 可点击刷新恢复。`, true);
  }
}
function renderActivity() {
  const labels = {
    "server.create": "添加服务器",
    "server.update": "编辑服务器",
    "server.delete": "移除服务器",
    "connection.test": "测试连接",
    "session.create": "创建会话",
    "session.close": "关闭会话",
    "session.input": "发送会话输入",
  };
  $("#page-content").innerHTML =
    `<section class="panel"><div class="panel-title"><h2>最近的管理操作</h2><small>最多显示 50 条</small></div>${state.activity.length ? `<div class="table-wrap"><table><thead><tr><th>时间</th><th>操作</th><th>目标</th><th>结果</th></tr></thead><tbody>${state.activity.map((a) => `<tr><td>${escapeHTML(new Date(a.timestamp).toLocaleString("zh-CN", { hour12: false }))}</td><td>${escapeHTML(labels[a.event] || a.event)}</td><td class="activity-target">${escapeHTML(a.target)}</td><td>${a.outcome === "ok" ? badge("ok", "已完成") : badge("failed", "未完成")}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty"><span class="empty-symbol">◷</span><h3>还没有操作记录</h3><p>添加服务器或测试连接后，记录会出现在这里。</p></div>`}</section><p class="note">这里只展示控制台操作，SQLite 保留最近 1,000 条记录。MCP 工具调用仍记录在服务端日志中。</p>`;
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  $("#login-error").textContent = "";
  try {
    await login($("#admin-token").value.trim(), $("#remember").checked);
  } catch (error) {
    if (!(error instanceof StaleRequest)) {
      token = "";
      $("#login-error").textContent = error.message;
    }
  } finally {
    button.disabled = false;
  }
});
$("#logout").addEventListener("click", logout);
$("#refresh").addEventListener("click", (event) =>
  busy(event.currentTarget, () => refresh()),
);
$("#add-server").addEventListener("click", () => editServer());
$("#server-form").elements.auth.addEventListener("change", authFields);
$("#server-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter,
    form = event.target;
  const data = Object.fromEntries(new FormData(form));
  data.id = editId || data.id;
  const server = {
    id: data.id,
    host: data.host.trim(),
    username: data.username.trim(),
    port: Number(data.port),
    description: data.description.trim(),
    known_hosts: data.known_hosts.trim(),
    [data.auth]: data.credential.trim(),
  };
  if (data.auth === "private_key" && data.passphrase_env.trim())
    server.passphrase_env = data.passphrase_env.trim();
  button.disabled = true;
  $("#server-error").textContent = "";
  try {
    await api(
      editId ? `/servers/${editId}` : "/servers",
      editId ? "PUT" : "POST",
      { revision: editRevision, server },
    );
    probes.delete(server.id);
    selected = server.id;
    $("#server-dialog").close();
    await refresh();
    notify("服务器已保存，新的连接立即使用此配置。");
  } catch (error) {
    if (!(error instanceof StaleRequest))
      $("#server-error").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
document.addEventListener("click", (event) => {
  const close = event.target.closest("[data-close]");
  if (close) {
    $(`#${close.dataset.close}`).close();
    return;
  }
  const nav = event.target.closest("[data-view]");
  if (nav) {
    if (!state) {
      $("#admin-token").focus();
      notify("请先登录管理控制台。");
      return;
    }
    view = nav.dataset.view;
    render();
    return;
  }
  const button = event.target.closest("[data-action]");
  if (!button || !state) return;
  const { action, id } = button.dataset;
  busy(button, async () => {
    if (action === "add") editServer();
    else if (action === "edit") editServer(id);
    else if (action === "select") {
      selected = id;
      renderServerRows();
      renderDetail();
    } else if (action === "clear-search") {
      search = "";
      authFilter = "all";
      renderServers();
    } else if (action === "test") {
      probes.set(id, { type: "running", text: "连接中" });
      renderServerRows();
      renderDetail();
      try {
        const result = await api(`/servers/${id}/test`, "POST", {});
        probes.set(
          id,
          result.ok
            ? {
                type: "ok",
                text: `可连接 · ${result.latency_ms} ms`,
                message: "刚刚通过 SSH 登录测试。",
              }
            : { type: "failed", text: "连接失败", message: result.message },
        );
        notify(result.ok ? `${id} 连接成功` : result.message, !result.ok);
      } catch (error) {
        probes.delete(id);
        throw error;
      } finally {
        if (state && view === "servers") {
          renderServerRows();
          renderDetail();
        }
      }
    } else if (action === "delete") {
      if (
        !(await confirmAction(
          "移除服务器",
          `将从工作空间移除 ${id}。这不会删除远程服务器或文件。如有运行中的会话，请先关闭。`,
        ))
      )
        return;
      await api(`/servers/${id}`, "DELETE", { revision: state.revision });
      await refresh();
      notify("服务器已移除。");
    } else if (action === "open-session" || action === "new-session") {
      const result = await api("/sessions", "POST", {
        server_id: id || $("#session-server").value,
      });
      selectedSession = result.session_id;
      view = "sessions";
      await refresh();
    } else if (action === "select-session") {
      selectedSession = id;
      render();
    } else if (action === "close-session") {
      if (
        !(await confirmAction(
          "关闭会话",
          "关闭后将释放连接并丢弃缓冲输出。远程脱离终端的后台进程不保证结束。",
        ))
      )
        return;
      stopPolling();
      await api(`/sessions/${id}`, "DELETE", {});
      outputs.delete(id);
      await refresh();
      notify("会话已关闭。");
    } else if (action === "client") {
      client = id;
      renderClients();
    } else if (action === "copy-url" || action === "copy-config") {
      const content = $(
        action === "copy-url" ? "#endpoint-url" : "#client-config",
      ).textContent;
      try {
        await navigator.clipboard.writeText(content);
        notify("已复制到剪贴板。");
      } catch {
        notify("浏览器未允许复制，请选中内容手动复制。", true);
      }
    }
  });
});
let saved = null;
try {
  saved = sessionStorage.getItem(storageKey);
} catch {
  /* login still works without storage */
}
if (saved)
  login(saved, true).catch((error) => {
    if (!(error instanceof StaleRequest))
      $("#login-error").textContent = error.message;
  });
