import { computed, h, ref } from "vue";
import Button from "primevue/button";

export function describeCommand(content) {
  const lines = content.split(/\r\n|\n|\r/);
  if (lines.length > 1 && lines.at(-1) === "") lines.pop();
  const setup = /^\s*(?:#|$|set\s+-|cd\s|(?:export\s+)?[A-Za-z_]\w*=)/;
  const preview = lines.find(line => !setup.test(line)) || lines.find(line => line.trim()) || "查看输入";
  return { lines, preview: preview.trim() };
}

// Highlight a small set of shell tokens, preserving every source character as text.
function highlight(line) {
  const tokens = [];
  const pattern = /^(\s*)([\w./-]+)|"(?:\\.|[^"\\])*"|'[^']*'|(?:^|(?<=\s))--?[\w-]+/g;
  let end = 0;
  for (const match of line.matchAll(pattern)) {
    tokens.push(line.slice(end, match.index));
    const kind = match[2] ? "command" : /^['"]/.test(match[0]) ? "string" : "option";
    tokens.push(h("span", { class: "syntax-" + kind }, match[0]));
    end = match.index + match[0].length;
  }
  tokens.push(line.slice(end));
  return tokens;
}

export default {
  props: ["record", "lines"],
  setup(props) {
    const wrap = ref(true), feedback = ref(""), limit = ref(100);
    const visible = computed(() => props.lines.slice(0, limit.value).map(highlight));
    async function copy() {
      try {
        await navigator.clipboard.writeText(props.record.content);
        feedback.value = "已复制原文";
      } catch {
        feedback.value = "复制失败，请选中原文复制";
      }
    }
    return () => h("section", { class: "command-reader", id: "reader-" + props.record.id, "aria-label": "命令原文" }, [
      h("header", { class: "reader-toolbar" }, [
        h("strong", "命令原文"), h("span", { class: "reader-count" }, props.lines.length + " 行"),
        h("label", [h("input", { type: "checkbox", checked: wrap.value, onChange: e => { wrap.value = e.target.checked; } }), "自动换行"]),
        h(Button, { label: "复制原文", class: "secondary", onClick: copy }),
      ]),
      h("div", { class: ["reader-source", { wrapped: wrap.value }] }, visible.value.map((tokens, i) =>
        h("div", { class: "source-line", key: i }, [
          h("span", { class: "line-number", "aria-hidden": true }, i + 1),
          h("code", tokens),
        ]))),
      limit.value < props.lines.length && h(Button, { label: "显示更多行", class: "text-link", onClick: () => { limit.value += 100; } }),
      h("span", { role: "status" }, feedback.value),
    ]);
  },
};
