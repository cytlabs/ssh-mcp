import { h, render } from "vue";

const sizes = [10, 20, 50];

export function listPagination(list) {
  const key = "ssh-mcp.page-size." + list;
  let size = 10;
  try {
    const saved = Number(localStorage.getItem(key));
    if (sizes.includes(saved)) size = saved;
  } catch { /* Storage is optional. */ }
  return { list, key, page: 1, size };
}

export function renderPager(element, state, total, update) {
  const pages = Math.max(1, Math.ceil(total / state.size));
  const page = Math.min(state.page, pages);
  function go(next) {
    if (!Number.isInteger(next) || next < 1 || next > pages || next === state.page) return;
    state.page = next;
    update();
  }
  function setSize(event) {
    const size = Number(event.target.value);
    if (!sizes.includes(size)) return;
    state.size = size;
    state.page = 1;
    try { localStorage.setItem(state.key, String(size)); } catch { /* Optional. */ }
    update();
  }
  render(h("nav", { class: "pager", "aria-label": "列表分页" }, [
    h("span", { class: "pager-meta", "aria-live": "polite" }, `共 ${total} 条 · 第 ${page} / ${pages} 页`),
    h("button", { id: state.list + "-prev", disabled: page <= 1, onClick: () => go(page - 1) }, "上一页"),
    h("button", { id: state.list + "-next", disabled: page >= pages, onClick: () => go(page + 1) }, "下一页"),
    h("select", { id: state.list + "-page-size", value: state.size, "aria-label": "每页条数", onChange: setSize },
      sizes.map(n => h("option", { value: n }, n + " 条/页"))),
    pages > 1 && h("form", { class: "page-jump", onSubmit(event) {
      event.preventDefault();
      go(event.currentTarget.elements.page.valueAsNumber);
    } }, [
      h("input", { key: page, name: "page", type: "number", min: 1, max: pages, value: page,
        required: true, "aria-label": "跳到页码" }),
      h("button", { type: "submit" }, "跳转"),
    ]),
  ]), element);
}
