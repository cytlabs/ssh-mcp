import { createApp, h, reactive } from "vue";
import PrimeVue from "primevue/config";
import Button from "primevue/button";
import DataTable from "primevue/datatable";
import Column from "primevue/column";
import Tag from "primevue/tag";
import Settings from "./Settings.js";

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
let pageApp;
export function releasePage() {
  pageApp?.unmount();
  pageApp = null;
}
export function mountSettings(element, props) {
  releasePage();
  pageApp = createApp(Settings, props);
  pageApp.use(PrimeVue, { unstyled: true, ripple: false }).mount(element);
}
export function mountTable(element, rows, columns, rowClass) {
  releasePage();
  pageApp = createApp({ render: () => h(DataTable, {
    value: rows, rowClass, class: "table-wrap", dataKey: "id",
  }, { default: () => columns.map(([header, field, cell]) =>
    h(Column, { key: field, field, header }, cell ? { body: ({ data }) => cell(data) } : {})) }) });
  pageApp.use(PrimeVue, { unstyled: true, ripple: false }).mount(element);
}

const status = (type, text) => h(Tag, { class: ["badge", type], value: text });
export function serverColumns(probes) {
  return [
    ["名称", "id", r => h(Button, { class: "server-name", "data-action": "select", "data-id": r.id }, {
      default: () => [h("span", { class: "server-icon" }, "▤"), h("span", [h("strong", r.id), h("small", r.description)])],
    })],
    ["主机地址", "host", r => r.host + ":" + r.port], ["SSH 用户", "username"],
    ["最近检测", "checked", r => probes.get(r.id)?.checkedAt || "—"],
    ["状态", "status", r => status(probes.get(r.id)?.type, probes.get(r.id)?.text || "未检测")],
    ["操作", "test", r => h(Button, { label: "立即检测", class: "text-link", disabled: probes.get(r.id)?.type === "running",
      "data-action": "test", "data-id": r.id })],
  ];
}
export function activityColumns(labels, formatTime) {
  return [["时间", "timestamp", r => formatTime(r.timestamp)],
    ["操作", "event", r => labels[r.event] || r.event], ["目标", "target"],
    ["结果", "outcome", r => status(r.outcome === "ok" ? "ok" : "failed", r.outcome === "ok" ? "成功" : "失败")]];
}
export const commandColumns = [
  ["操作者", "operator", r => [h("strong", r.nickname || r.operator || "未记录"), r.nickname && h("small", r.operator)]],
  ["服务器", "server_id", r => (r.ssh_user || "未记录") + " @ " + r.server_id],
  ["时间（本地）", "timestamp", r => h("time", new Date(r.timestamp).toLocaleString("sv-SE"))],
  ["命令", "content", r => [r.event === "shell_input" && h("small", "交互输入"),
    r.content.length > 70 || r.content.includes("\n")
      ? h("details", [h("summary", (r.content.split("\n")[0].slice(0, 70) || "查看输入") + "…"), h("pre", r.content)])
      : h("code", r.content)]],
];
