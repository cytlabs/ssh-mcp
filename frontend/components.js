import { createApp, h, reactive, ref, render, shallowRef } from "vue";
import PrimeVue from "primevue/config";
import Button from "primevue/button";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Tag from "primevue/tag";
import Settings from "./Settings.js";
import CommandReader, { describeCommand } from "./CommandReader.js";

const mount = (element, component) => createApp(component)
  .use(PrimeVue, { unstyled: true, ripple: false }).mount(element);

const links = [
  ["dashboard", "概览", "⌂"], ["servers", "服务器", "▤"],
  ["activity", "操作记录", "◷"], ["commands", "命令审计", "⌘"],
  ["clients", "MCP 接入", "⇄"], ["settings", "设置", "⚙"],
];

export function mountNavigation(element) {
  const model = reactive({ view: "dashboard", count: "—" });
  mount(element, { render: () => links.map(([id, label, icon]) =>
    h(Button, { key: id, "data-view": id, "aria-current": model.view === id ? "page" : "false" }, {
      default: () => [h("span", { class: "nav-icon", "aria-hidden": true }, icon), label,
        id === "servers" && h("span", { id: "nav-count", class: "nav-count" }, model.count)],
    })) });
  return model;
}

// Each list uses the same table. Cell renderers receive data as text, including command input.
let pageApp, tableHost, tableData;
export function releasePage() {
  pageApp?.unmount();
  pageApp = null;
  tableHost = tableData = null;
}
export function mountSettings(element, props) {
  releasePage();
  pageApp = createApp(Settings, props);
  pageApp.use(PrimeVue, { unstyled: true, ripple: false }).mount(element);
}
export function mountTable(element, rows, columns, rowClass) {
  const next = { rows, columns, rowClass };
  if (tableHost === element) {
    tableData.value = next;
    return;
  }
  releasePage();
  tableHost = element;
  tableData = shallowRef(next);
  pageApp = createApp({ render() {
    const model = tableData.value;
    return h(DataTable, { value: model.rows, rowClass: model.rowClass, class: "table-wrap", dataKey: "id" },
      { default: () => model.columns.map(([header, field, cell]) =>
        h(Column, { key: field, field, header }, cell ? { body: ({ data }) => cell(data) } : {})) });
  } });
  pageApp.use(PrimeVue, { unstyled: true, ripple: false }).mount(element);
}

const status = (type, text) => h(Tag, { class: ["badge", type], value: text });
export function serverColumns(probes) {
  return [
    ["服务器", "id", r => h(Button, { class: "server-name", "aria-controls": "server-drawer", "data-action": "select", "data-id": r.id }, {
      default: () => [h("span", { class: "server-icon" }, "▤"), h("span", [h("strong", r.id), h("small", r.host + ":" + r.port)])],
    })],
    ["连接状态", "status", r => status(probes.get(r.id)?.type, probes.get(r.id)?.text || "未检测")],
    ["服务器配置", "system_info", r => {
      const probe = probes.get(r.id), info = probe?.systemInfo;
      const capacity = kib => (kib / 1048576).toLocaleString("zh-CN", { maximumFractionDigits: 1 }) + " GiB";
      const specs = [info?.cpu && 'CPU ' + info.cpu + ' 线程', info?.memory_kib && "内存 " + capacity(info.memory_kib),
        info?.root_disk_kib && "根分区 " + capacity(info.root_disk_kib)].filter(Boolean);
      return h("div", { class: "server-specs" }, [
        info?.os && h("strong", info.os),
        specs.length ? h("span", specs.join(" · ")) : !info?.os && (probe?.type === "running" ? "采集中…" : probe ? "配置暂不可用" : "待检测"),
      ]);
    }],
    ["最近检测", "checked", r => probes.get(r.id)?.checkedAt || "—"],
    ["操作", "test", r => h(Button, { label: "立即检测", class: "text-link", disabled: probes.get(r.id)?.type === "running",
      "data-action": "test", "data-id": r.id })],
  ];
}
export function renderServerDetail(element, row, probe) {
  if (!row) { render(null, element); return; }
  const fields = [["地址", row.host + ":" + row.port], ["登录用户", row.username],
    ["认证方式", row.private_key ? "SSH 私钥" : "密码认证"], ["凭据引用", row.private_key || row.password_env],
    ["主机公钥", row.known_hosts], ["最近检测", probe?.checkedAt || "未检测"]];
  render(h("section", { id: "server-detail" }, [
    h("header", { class: "drawer-heading" }, [h("div", [h("h2", { id: "drawer-title" }, row.id), row.description && h("p", row.description)]),
      h("button", { class: "icon-button", "data-action": "close-detail", "aria-label": "关闭详情" }, "×")]),
    h("div", { class: "drawer-body" }, [
      status(probe?.type, probe?.text || "未检测"),
      probe?.type === "failed" && h("p", { class: "detail-foot" }, probe.message),
      h("h3", "SSH 连接"),
      h("dl", { class: "details" }, fields.map(([k,v]) => h("div", [h("dt", k), h("dd", v)]))),
    ]),
    h("footer", { class: "drawer-actions" }, [
      ["test", "primary", "重新检测"], ["edit", "secondary", "编辑配置"], ["delete", "text-link", "移除服务器"],
    ].map(([action, cls, label]) => h("button", { class: cls, "data-action": action, "data-id": row.id,
      disabled: action === "test" && probe?.type === "running" }, label))),
  ]), element);
}
export function activityColumns(labels, formatTime) {
  return [["时间", "timestamp", r => formatTime(r.timestamp)],
    ["操作", "event", r => labels[r.event] || r.event], ["目标", "target"],
    ["结果", "outcome", r => status(r.outcome === "ok" ? "ok" : "failed", r.outcome === "ok" ? "成功" : "失败")]];
}
const identityColumns = [
  ["操作者", "operator", r => [h("strong", r.nickname || r.operator || "未记录"), r.nickname && h("small", r.operator)]],
  ["服务器", "server_id", r => (r.ssh_user || "未记录") + " @ " + r.server_id],
  ["时间（本地）", "timestamp", r => h("time", new Date(r.timestamp).toLocaleString("sv-SE"))],
];

export function mountCommands(element, rows) {
  releasePage();
  const selected = ref(null);
  const records = rows.map(row => ({ ...row, ...describeCommand(row.content) }));
  function preview(row) {
    if (!row.content) return h("span", { class: "muted" }, "未记录正文");
    const expanded = selected.value === row.id;
    return h(Button, { class: "command-preview", "aria-expanded": expanded,
      "aria-controls": expanded ? "reader-" + row.id : undefined,
      onClick: () => { selected.value = expanded ? null : row.id; } }, {
      default: () => [
        h("span", { class: "preview-arrow", "aria-hidden": true }, expanded ? "▾" : "▸"),
        h("code", row.preview),
        (row.lines.length > 1 || row.event === "shell_input") && h("small",
          [row.event === "shell_input" && "交互输入", row.lines.length + " 行"].filter(Boolean).join(" · ")),
      ],
    });
  }
  pageApp = createApp({ render: () => h(DataTable, { value: records, dataKey: "id", class: "table-wrap",
    expandedRows: selected.value == null ? {} : { [selected.value]: true },
    rowClass: row => selected.value === row.id ? "reading" : "",
  }, {
    default: () => [...identityColumns, ["命令", "content", preview]].map(([header, field, cell]) =>
      h(Column, { key: field, field, header }, { body: ({ data }) => cell(data) })),
    expansion: ({ data }) => h(CommandReader, { key: data.id, record: data, lines: data.lines }),
  }) });
  pageApp.use(PrimeVue, { unstyled: true, ripple: false }).mount(element);
}
