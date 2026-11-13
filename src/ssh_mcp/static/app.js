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
  commands: ["命令审计", "COMMAND AUDIT", "查看发送到服务器的命令和交互输入。"],
  dashboard: [
    "概览",
    "SYSTEM OVERVIEW",
    "查看 SSH 服务器和连接概况。",
  ],
  servers: [
    "服务器",
    "SERVER INVENTORY",
    "搜索、维护并检测服务器连接。",
  ],
clients: [
    "MCP 接入",
    "CONNECT YOUR CLIENT",
    "配置 AI 客户端的 MCP 访问。",
  ],
  activity: [
    "操作记录",
    "WORKSPACE ACTIVITY",
    "搜索与筛选管理操作记录。",
  ],
};
let setupToken = new URLSearchParams(location.hash.slice(1)).get("setup") || "";
if (setupToken) history.replaceState(null, "", location.pathname + location.search);
let setupReady = false, bootGeneration = 0;
let authMode = "token", csrf = "", initialized = true, grants = [];
let authorizationRequest = new URLSearchParams(location.search).get("authorize");
let token = "",
  epoch = 0,
  view = "dashboard",
  state = null,
  selected = null,
  selectedSession = null;
let search = "",
  authFilter = "all",
  serverStatus = "all", serverPage = 1, serverSize = 10,
  activityPage = 1, activitySize = 10, activitySearch = "",
  activityEvent = "all", activityOutcome = "all", activityFrom = "", activityTo = "",
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
class AuthenticationError extends Error {}
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
        ...(authMode === "oauth" ? { "X-CSRF-Token": csrf } : { Authorization: `Bearer ${token}` }),
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
      throw new AuthenticationError(authMode === "oauth" ? "登录状态已失效，请重新登录。" : "管理员 Token 无效或已失效，请重新登录。");
    }
    if (!response.ok)
      throw new Error(
        result.error || `请求未完成（${response.status}），请稍后重试。`,
      );
    return result;
  } catch (error) {
    if (currentEpoch !== epoch && !(error instanceof AuthenticationError))
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
  csrf = "";
  grants = [];
  $("#consent-view").hidden = true;
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
  document.body.classList.remove("authenticated");
  $("#nav-count").textContent = "—";
  document.querySelectorAll("dialog[open]").forEach((d) => d.close());
}
async function refresh(renderPage = true) {
  state = await api("/state");
  if (!state.servers.some((s) => s.id === selected))
    selected = null;
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
  if (remember && authMode === "token") {
    try {
      sessionStorage.setItem(storageKey, token);
    } catch {
      notify("浏览器不允许保存登录状态，本次页面仍可使用。", true);
    }
  }
  $("#login-view").hidden = true;
  $("#app-view").hidden = false;
  document.body.classList.add("authenticated");
  $("#logout").hidden = false;
  $("#connection-label").textContent = "管理员已连接";
  render();
  if (authMode === "oauth" && authorizationRequest) await showConsent();
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
    dashboard: renderDashboard,
    servers: renderServers,
    clients: renderClients,
    activity: renderActivity,
    commands: renderCommands,
  })[view]();
}
function renderDashboard() {
  const servers = state.servers || [], recent = (state.activity || []).slice(0, 6);
  const running = (state.sessions || []).filter(x => x.status === "running").length;
  const stat = (label, val, note, symbol) =>
    '<div class="overview-stat"><span class="overview-stat-icon">' + symbol + '</span><span>' + label +
    '</span><strong>' + val + '</strong><small>' + note + '</small></div>';
  $("#page-content").innerHTML = `
    <div class="overview-stats">
      ${stat("服务器", servers.length, "已配置的服务器", "▤")}
      ${stat("活跃会话", running, "当前服务实例", "⇄")}
      ${stat("最近记录", (state.activity || []).length, "最多显示最近 50 条", "◷")}
    </div>
    <div class="overview-columns">
      <section class="overview-section"><div class="overview-heading"><h2>服务器</h2><button class="text-link" data-view-link="servers">查看全部 →</button></div>
        <div class="overview-hosts">${servers.length ? servers.slice(0,6).map(x => {
          const p = probes.get(x.id);
          return '<div class="overview-host"><span class="overview-host-icon">▤</span><span><strong>' +
            escapeHTML(x.id) + '</strong><small>' + escapeHTML(x.host) + ':' + x.port +
            '</small></span>' + (p ? badge(p.type,p.text) : badge("","未检测")) + '</div>';
        }).join("") : '<div class="overview-empty">暂无服务器。</div>'}</div></section>
      <section class="overview-section"><div class="overview-heading"><h2>最近操作</h2><button class="text-link" data-view-link="activity">查看全部 →</button></div>
        <div class="overview-events">${recent.length ? recent.map(x => '<div class="overview-event"><span class="event-bullet"></span><div><strong>' +
          escapeHTML(activityLabels[x.event] || x.event) + '</strong><small>' + escapeHTML(x.target) +
          '</small></div><time>' + escapeHTML(formatTime(x.timestamp)) + '</time></div>').join("") : '<div class="overview-empty">暂无操作记录。</div>'}</div></section>
    </div>
    <div class="overview-access"><span>⇄</span><div><strong>MCP 接入</strong><p>连接 Codex、Claude Code、Cursor 等客户端。</p></div><button class="text-link" data-view-link="clients">查看配置 →</button></div>`;
}
function renderServers() {
  $("#page-content").innerHTML = `
    <section class="panel"><div class="toolbar">
      <label class="search"><span>⌕</span><input id="server-search" type="search" aria-label="搜索服务器" value="${escapeHTML(search)}" placeholder="搜索名称、地址或备注"></label>
      <select id="auth-filter" aria-label="认证方式"><option value="all">全部认证方式</option><option value="key">SSH 私钥</option><option value="password">密码认证</option></select>
      <select id="status-filter" aria-label="连接测试状态"><option value="all">全部状态</option><option value="ok">可连接</option><option value="failed">连接失败</option><option value="untested">未检测</option></select>
    </div><div id="server-rows"></div></section><section class="panel" id="server-detail" hidden></section>`;
  $("#auth-filter").value = authFilter;
  $("#status-filter").value = serverStatus;
  $("#server-search").addEventListener("input", e => { search = e.target.value; serverPage = 1; renderServerRows(); });
  $("#auth-filter").addEventListener("change", e => { authFilter = e.target.value; serverPage = 1; renderServerRows(); });
  $("#status-filter").addEventListener("change", e => { serverStatus = e.target.value; serverPage = 1; renderServerRows(); });
  renderServerRows(); renderDetail();
}
function renderServerRows() {
  const term = search.trim().toLowerCase();
  const filtered = state.servers.filter(x => {
    const p = probes.get(x.id), status = p?.type === "ok" ? "ok" : p?.type === "failed" ? "failed" : "untested";
    return [x.id,x.host,x.description,x.username].some(v => String(v || "").toLowerCase().includes(term))
      && (authFilter === "all" || (authFilter === "key" ? !!x.private_key : !!x.password_env))
      && (serverStatus === "all" || serverStatus === status);
  });
  const count = filtered.length, pages = Math.max(1,Math.ceil(count/serverSize));
  serverPage = Math.min(serverPage,pages);
  const rows = filtered.slice((serverPage-1)*serverSize, serverPage*serverSize);
  if (!state.servers.length) {
    $("#server-rows").innerHTML = '<div class="empty"><h3>暂无服务器</h3><p>添加一台 SSH 服务器开始使用。</p><button class="primary" data-action="add">＋ 添加服务器</button></div>';
    return;
  }
  $("#server-rows").innerHTML = count ? `
    <div class="table-wrap"><table><thead><tr><th>名称</th><th>主机地址</th><th>认证方式</th><th>最近测试</th><th>状态</th><th>操作</th></tr></thead>
      <tbody>${rows.map(x => {
        const p = probes.get(x.id);
        return '<tr class="server-row ' + (selected === x.id ? "selected" : "") + '"><td><button class="server-name" data-action="select" data-id="' +
          escapeHTML(x.id) + '"><span class="server-icon">▤</span><span><strong>' + escapeHTML(x.id) +
          '</strong><small>' + escapeHTML(x.description || "") + '</small></span></button></td><td class="address">' +
          escapeHTML(x.host) + ':' + x.port + '<small>' + escapeHTML(x.username) +
          '</small></td><td>' + (x.private_key ? "SSH 私钥" : "密码认证") + '</td><td>' +
          escapeHTML(p?.checkedAt || "—") + '</td><td>' + statusBadge(x.id) +
          '</td><td><button class="text-link" data-action="test" data-id="' + escapeHTML(x.id) + '"' +
          (p?.type === "running" ? " disabled" : "") + '>测试连接</button></td></tr>';
      }).join("")}</tbody></table></div>
      <div class="pager"><span class="pager-meta">共 ${count} 条 · 第 ${serverPage} / ${pages} 页</span>
        <button data-action="server-prev" ${serverPage === 1 ? "disabled" : ""}>上一页</button>
        <button data-action="server-next" ${serverPage >= pages ? "disabled" : ""}>下一页</button>
        <select id="server-page-size" aria-label="每页条数"><option value="10">10 条/页</option><option value="20">20 条/页</option><option value="50">50 条/页</option></select>
      </div>` :
      '<div class="empty"><h3>没有匹配的服务器</h3><button class="secondary" data-action="clear-search">清除筛选</button></div>';
  const size = $("#server-page-size");
  if(size){ size.value = String(serverSize); size.addEventListener("change", e => { serverSize = Number(e.target.value); serverPage = 1; renderServerRows(); }); }
}
function renderDetail() {
  const el = $("#server-detail");
  if(!el) return;
  const x = state.servers.find(s => s.id === selected);
  el.hidden = !x;
  if(!x) return;
  const probe = probes.get(x.id);
  const rows = [["地址", x.host + ":" + x.port],["登录用户",x.username],
    ["认证方式",x.private_key ? "SSH 私钥" : "密码认证"],
    ["凭据引用", x.private_key || x.password_env],["主机公钥",x.known_hosts],
    ["最近测试",probe?.checkedAt || "未检测"]];
  el.innerHTML = `<div class="detail">
    <div class="detail-heading"><span class="server-icon">▤</span><div><h3>${escapeHTML(x.id)}</h3><p>${escapeHTML(x.description || "")}</p></div>
      <button class="icon-button" data-action="close-detail" aria-label="关闭详情">×</button></div>
    <dl class="details">${rows.map(([k,v]) => '<div><dt>' + escapeHTML(k) + '</dt><dd>' + escapeHTML(v) + '</dd></div>').join("")}</dl>
    <div class="inline-actions"><button class="primary" data-action="edit" data-id="${escapeHTML(x.id)}">编辑服务器</button>
      <button class="secondary" data-action="test" data-id="${escapeHTML(x.id)}">测试连接</button>
      <button class="text-link" data-action="delete" data-id="${escapeHTML(x.id)}">移除服务器</button></div>
    ${probe?.message ? '<p class="detail-foot">' + escapeHTML(probe.message) + '</p>' : ""}</div>`;
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
  if (authMode === "oauth") return renderOAuthClients();
  const clients = [
    ["Codex", "环境变量认证", "C"],
    ["Cursor", "远程 HTTP", "↗"],
    ["Claude Code", "远程 HTTP", "✳"],
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


const activityLabels = {
  "server.create":"添加服务器","server.update":"编辑服务器","server.delete":"移除服务器",
  "connection.test":"测试连接","session.create":"创建会话",
  "session.close":"关闭会话","session.input":"发送会话输入"
};
function formatTime(value) {
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("zh-CN", {hour12:false});
}
let activityRequestId = 0;
function renderCommands(before = null, previous = [], search = "", day = "") {
  const panel = document.createElement("section");
  panel.className = "command-ledger";
  panel.innerHTML = `<form class="ledger-filters">
    <input type="search" aria-label="搜索操作者、服务器或命令" placeholder="搜索操作者、服务器、命令…" maxlength="256">
    <input type="date" aria-label="本地日期"><button>查询</button></form>
    <div class="ledger-results" aria-live="polite">正在加载…</div>`;
  $("#page-content").replaceChildren(panel);
  const form = panel.querySelector("form"), [term, date] = form.querySelectorAll("input");
  term.value = search;
  date.value = day;
  form.onsubmit = e => {
    e.preventDefault();
    renderCommands(null, [], term.value.trim(), date.value);
  };
  const params = new URLSearchParams({search});
  if (before) params.set("before", before);
  if (day) {
    const start = new Date(day + "T00:00:00"), end = new Date(start);
    end.setDate(end.getDate() + 1);
    params.set("start", start.toISOString());
    params.set("end", end.toISOString());
  }
  const results = panel.querySelector(".ledger-results");
  api("/command-audit?" + params).then(data => {
    if (!panel.isConnected) return;
    if (!data.rows.length) {
      results.textContent = !data.enabled ? "服务端尚未启用命令审计" : "没有符合条件的记录";
      return;
    }
    results.innerHTML = '<div class="table-wrap"><table><thead><tr><th>操作者</th><th>服务器</th><th>时间（本地）</th><th>命令</th></tr></thead><tbody>' +
      data.rows.map(row => {
        const content = escapeHTML(row.content);
        const command = row.content.length > 70 || row.content.includes("\n")
          ? '<details><summary>' + escapeHTML(row.content.split("\n")[0].slice(0,70) || "查看输入") + '…</summary><pre>' + content + '</pre></details>'
          : '<code>' + content + '</code>';
        return '<tr><td><strong>' + escapeHTML(row.operator || "未记录") + '</strong></td><td>' +
          escapeHTML((row.ssh_user || "未记录") + " @ " + row.server_id) + '</td><td><time>' +
          escapeHTML(new Date(row.timestamp).toLocaleString("sv-SE")) + '</time></td><td>' +
          (row.event === "shell_input" ? '<small>交互输入</small>' : '') + command + '</td></tr>';
      }).join("") + '</tbody></table></div><div class="pager"><button id="audit-prev">上一页</button><button id="audit-next">下一页</button></div>';
    $("#audit-prev").disabled = !previous.length;
    $("#audit-prev").onclick = () => renderCommands(previous.at(-1), previous.slice(0,-1), search, day);
    $("#audit-next").disabled = !data.more;
    $("#audit-next").onclick = () => renderCommands(data.rows.at(-1).id, [...previous,before], search, day);
  }).catch(() => { results.textContent = "加载失败，请重新查询。"; });
}
function renderActivity() {
  $("#page-content").innerHTML = `
    <section class="panel"><div class="filters activity-filter">
      <label class="search"><span>⌕</span><input type="search" id="activity-search" aria-label="搜索操作" placeholder="搜索操作或服务器" value="${escapeHTML(activitySearch)}"></label>
      <select id="activity-event" aria-label="操作类型"><option value="all">全部操作</option><option value="server">服务器管理</option><option value="connection">连接检测</option><option value="session">MCP 会话</option></select>
      <select id="activity-outcome" aria-label="操作结果"><option value="all">全部结果</option><option value="ok">成功</option><option value="failed">失败</option></select>
      <input id="activity-from" type="date" aria-label="开始日期" value="${escapeHTML(activityFrom)}">
      <input id="activity-to" type="date" aria-label="结束日期" value="${escapeHTML(activityTo)}">
    </div><div id="activity-rows">正在加载…</div></section>`;
  $("#activity-event").value = activityEvent; $("#activity-outcome").value = activityOutcome;
  $("#activity-search").addEventListener("input", e => { activitySearch = e.target.value; activityPage = 1; loadActivity(); });
  for(const [id,key] of [["activity-event","event"],["activity-outcome","outcome"],["activity-from","start"],["activity-to","end"]]){
    $("#" + id).addEventListener("change", e => {
      if(key === "event") activityEvent = e.target.value;
      else if(key === "outcome") activityOutcome = e.target.value;
      else if(key === "start") activityFrom = e.target.value;
      else activityTo = e.target.value;
      activityPage = 1; loadActivity();
    });
  }
  loadActivity();
}
async function loadActivity() {
  const id = ++activityRequestId;
  const params = new URLSearchParams({page:String(activityPage),size:String(activitySize),search:activitySearch.trim(),
    event:activityEvent,outcome:activityOutcome,start:activityFrom,end:activityTo});
  try {
    const data = await api("/activity?" + params.toString());
    if(id !== activityRequestId || view !== "activity" || !$("#activity-rows")) return;
    const rows = data.items || [], pages = Math.max(1,Math.ceil(data.total/data.size));
    $("#activity-rows").innerHTML = rows.length ? `<div class="table-wrap"><table><thead>
      <tr><th>时间</th><th>操作</th><th>目标</th><th>结果</th></tr></thead><tbody>${rows.map(x =>
       '<tr><td>' + escapeHTML(formatTime(x.timestamp)) + '</td><td>' +
       escapeHTML(activityLabels[x.event] || x.event) + '</td><td class="activity-target">' +
       escapeHTML(x.target) + '</td><td>' + badge(x.outcome === "ok" ? "ok" : "failed",x.outcome === "ok" ? "成功" : "失败") +
       '</td></tr>').join("")}</tbody></table></div>` :
       '<div class="empty"><h3>没有匹配的操作记录</h3><p>请调整搜索条件。</p></div>';
    $("#activity-rows").insertAdjacentHTML("beforeend", `<div class="pager">
      <span class="pager-meta">共 ${data.total} 条 · 第 ${data.page} / ${pages} 页</span>
      <button data-action="activity-prev" ${data.page <= 1 ? "disabled" : ""}>上一页</button>
      <button data-action="activity-next" ${data.page >= pages ? "disabled" : ""}>下一页</button>
      <select id="activity-page-size" aria-label="每页记录条数"><option value="10">10 条/页</option><option value="20">20 条/页</option><option value="50">50 条/页</option></select></div>`);
    const size = $("#activity-page-size"); size.value = String(activitySize);
    size.addEventListener("change", e => { activitySize = Number(e.target.value); activityPage = 1; loadActivity(); });
  } catch(error) {
    if(id === activityRequestId && $("#activity-rows")){
      $("#activity-rows").innerHTML = '<div class="empty">加载失败，请点击刷新重试。</div>';
      notify(error.message, true);
    }
  }
}
$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  $("#login-error").textContent = "";
  try {
    if (authMode === "oauth") {
      const password = $("#admin-token").value;
      if (!initialized && password !== $("#confirm-password").value) throw new Error("两次输入的密码不一致。");
      const result = await authRequest(initialized ? "/login" : "/setup", "POST", { password, username: $("#username").value.trim() });
      csrf = result.csrf; initialized = true;
      configureLogin();
      setupToken = ""; $("#confirm-password").value = "";
      await login("browser-session");
    } else await login($("#admin-token").value.trim(), $("#remember").checked);
  } catch (error) {
    if (!(error instanceof StaleRequest)) {
      token = "";
      $("#login-error").textContent = error.message;
    }
  } finally {
    button.disabled = false;
  }
});
$("#logout").addEventListener("click", (event) => busy(event.currentTarget, async () => {
  if (authMode === "oauth") await authRequest("/logout", "POST", {});
  logout();
}));
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
  const link = event.target.closest("[data-view-link]");
  if (link && state) { view = link.dataset.viewLink; render(); return; }
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
    else if (action === "server-prev") { serverPage = Math.max(1,serverPage-1); renderServerRows(); }
    else if (action === "server-next") { serverPage++; renderServerRows(); }
    else if (action === "activity-prev") { activityPage = Math.max(1,activityPage-1); loadActivity(); }
    else if (action === "activity-next") { activityPage++; loadActivity(); }
    else if (action === "close-detail") { selected = null; renderServerRows(); renderDetail(); }
    else if (action === "select") {
      selected = id;
      renderServerRows();
      renderDetail();
    } else if (action === "clear-search") {
      search = ""; authFilter = "all"; serverStatus = "all"; serverPage = 1; renderServers();
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
                message: "SSH 登录测试成功。", checkedAt: formatTime(new Date().toISOString()),
              }
            : { type: "failed", text: "连接失败", message: result.message, checkedAt: formatTime(new Date().toISOString()) },
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
const authMessages = {
  invalid_credentials: "用户名或密码不正确。",
  invalid_username: "用户名可使用字母、数字和 . _ @ + -，最长 128 位。",
  setup_link_invalid: "初始化链接已失效，请让部署管理员重新生成链接。",
  password_length: "密码需要 12 到 256 个字符。",
  already_initialized: "已完成首次设置，请刷新页面后登录。",
  too_many_requests: "尝试次数过多，请一分钟后再试。",
  login_required: "登录已过期，请重新登录。",
  authorization_expired: "授权请求已过期，请回到客户端重新发起连接。",
};
async function authRequest(path, method = "GET", body) {
  const response = await fetch(`/auth${path}`, {
    method, credentials: "same-origin", cache: "no-store",
    headers: { "X-CSRF-Token": csrf, ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(authMessages[result.error] || "请求未完成，请刷新后重试。");
  return result;
}
function configureLogin() {
  const oauth = authMode === "oauth", setup = oauth && !initialized;
  const locked = setup && !setupReady;
  $("#login-fields").hidden = locked;
  const submit = $("#login-form button[type=submit]");
  submit.hidden = locked;
  submit.textContent = setup ? "创建账号并进入控制台" : "进入控制台";
  $("#login-title").textContent = locked ? "请使用初始化链接" : setup ? "创建管理员账号" : "登录 SSH-MCP";
  $("#login-description").textContent = locked ? "当前还没有管理员账号。请打开部署时生成的完整初始化链接，再创建用户名和密码。" : oauth ? (setup ? "设置用户名和密码，即可开始使用。" : "使用用户名和密码登录。") : "使用管理员 Token 登录。";
  $("#password-label").textContent = oauth ? (setup ? "设置密码" : "密码") : "管理员 Token";
  const input = $("#admin-token");
  input.minLength = oauth ? (setup ? 12 : 1) : 32;
  input.maxLength = oauth ? 256 : 4096;
  input.autocomplete = oauth ? (setup ? "new-password" : "current-password") : "off";
  input.placeholder = oauth ? (setup ? "至少 12 个字符" : "输入管理员密码") : "输入 SSH_MCP_ADMIN_TOKEN";
  $("#setup-fields").hidden = !setup;
  $("#confirm-password").required = setup;
  $("#username-label").hidden = !oauth;
  $("#username").required = oauth;
  $("#login-form button[type=submit]").disabled = locked;
  $("#remember").closest("label").hidden = oauth;
  $(".login-help").textContent = oauth ? (setup ? "初始化链接只能使用一次。" : "") : "管理员 Token 不等于 MCP Token。";
}
async function showConsent() {
  const info = await authRequest(`/consent?request=${encodeURIComponent(authorizationRequest)}`);
  $("#consent-client").textContent = `${info.client_name} 请求连接你的 SSH MCP。`;
  $("#consent-redirect").textContent = info.redirect_uri;
  $("#app-view").hidden = true;
  $("#consent-view").hidden = false;
  $("#allow-consent").focus();
}
for (const [id, approve] of [["#allow-consent", true], ["#deny-consent", false]]) {
  $(id).addEventListener("click", (event) => busy(event.currentTarget, async () => {
    const result = await authRequest("/consent", "POST", { request: authorizationRequest, approve });
    location.assign(result.redirect);
  }));
}
function renderOAuthClients() {
  const url = state.mcp_url;
  const code = `codex mcp add ssh_mcp --url ${url}\ncodex mcp login ssh_mcp`;
  $("#page-content").innerHTML = `<section class="panel setup-panel"><span class="section-kicker">BROWSER AUTHORIZATION</span><h2>添加地址，在浏览器中授权</h2><p>客户端自动保存登录凭据。日常使用无需设置 Token 环境变量或运行启动脚本。</p><div class="endpoint"><code id="endpoint-url">${escapeHTML(url)}</code><button class="text-link" data-action="copy-url">复制地址</button></div><div class="step"><h3>Codex CLI</h3><div class="code-block"><div class="code-heading"><span>终端</span><button data-action="copy-config">复制命令</button></div><pre id="client-config">${escapeHTML(code)}</pre></div><p class="note">如果之前配置过 bearer_token_env_var 或固定 Authorization 请求头，请先移除，再重新登录。</p></div><div class="step"><h3>其他远程 MCP 客户端</h3><p>在 ChatGPT、Cursor 或 Claude 的 MCP 设置中添加上方 URL，选择 OAuth 或浏览器授权，然后登录并确认客户端权限。具体入口以客户端支持情况为准。</p><p class="note">这些说明不代表已在每个客户端完成验收。静态 Bearer Token 仍可作为自动化兼容方式。</p></div></section><section class="panel setup-panel"><div class="panel-title"><h2>已授权的客户端</h2><button id="load-grants" class="secondary">刷新授权</button></div><div id="grants-list">正在读取…</div><p class="note">撤销会阻止客户端继续调用 MCP，已经启动的远程进程需要在终端会话中另外关闭。</p></section>`;
  $("#load-grants").addEventListener("click", (event) => busy(event.currentTarget, loadGrants));
  loadGrants().catch((error) => notify(error.message, true));
}
async function loadGrants() {
  const currentEpoch = epoch;
  const result = await authRequest("/grants");
  if (currentEpoch !== epoch || !$("#grants-list")) return;
  grants = result.grants;
  $("#grants-list").innerHTML = grants.length ? grants.map((g) => `<div class="grant-row"><div><strong>${escapeHTML(g.client_name)}</strong><small>${escapeHTML(new Date(g.created * 1000).toLocaleString("zh-CN"))} · ${g.revoked ? "已撤销" : "已授权"}</small></div>${g.revoked ? "" : `<button class="secondary" data-revoke="${escapeHTML(g.id)}">撤销授权</button>`}</div>`).join("") : '<p class="muted">还没有授权的客户端。</p>';
  document.querySelectorAll("[data-revoke]").forEach((button) => button.addEventListener("click", () => busy(button, async () => {
    await authRequest("/revoke", "POST", { grant_id: button.dataset.revoke });
    await loadGrants();
  })));
}
async function boot() {
  const generation = ++bootGeneration, initialToken = setupToken;
  setupToken = "";
  if (initialToken) {
    try { await authRequest("/setup-session", "POST", { setup_token: initialToken }); }
    catch (error) { $("#login-error").textContent = error.message; }
  }
  const status = await authRequest("/session");
  if (generation !== bootGeneration) return;
  authMode = status.mode;
  initialized = status.initialized !== false;
  setupReady = status.setup_ready === true;
  configureLogin();
  if (authMode === "oauth") {
    try { sessionStorage.removeItem(storageKey); } catch { /* Cookie 登录不依赖 Web Storage */ }
    if (status.authenticated) { csrf = status.csrf; await login("browser-session"); }
  } else {
    let saved;
    try { saved = sessionStorage.getItem(storageKey); } catch { /* 无存储也能登录 */ }
    if (saved) await login(saved, true);
  }
}
function startLogin() {
  boot().catch((error) => { $("#login-error").textContent = error.message; });
}
window.addEventListener("hashchange", () => {
  const value = new URLSearchParams(location.hash.slice(1)).get("setup");
  if (!value) return;
  setupToken = value;
  history.replaceState(null, "", location.pathname + location.search);
  startLogin();
});
startLogin();

const themeStoreKey = "ssh-mcp.theme";
const legacyThemeStoreKey = "portlane.theme";
function applyTheme(next) {
  document.body.dataset.theme = next;
  for (const id of ["#theme-toggle","#login-theme-toggle"]) {
    const btn = $(id);
    if (!btn) continue;
    btn.textContent = next === "dark" ? "☀" : "☾";
    btn.setAttribute("aria-label",next === "dark" ? "切换到浅色模式" : "切换到深色模式");
  }
}
let storedTheme = "";
try { storedTheme = (localStorage.getItem(themeStoreKey) || localStorage.getItem(legacyThemeStoreKey)) || ""; } catch {}
const wantsDark = typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
applyTheme(["light","dark"].includes(storedTheme) ? storedTheme : wantsDark ? "dark" : "light");
function toggleTheme() {
  const next = document.body.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem(themeStoreKey,next); } catch {}
}
$("#theme-toggle").addEventListener("click",toggleTheme);
$("#login-theme-toggle").addEventListener("click",toggleTheme);
