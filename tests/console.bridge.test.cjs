const { test } = require("node:test");
const assert = require("node:assert/strict");
const { startBridge } = require("./console.bridge.cjs");

const ready = 'print(json.dumps({"event": "ready"}), flush=True)\n';
const hold = 'sys.stdin.read()\n';
function fixture(t, script, limits) {
  const bridge = startBridge(process.env.PYTHON || "python3",
    ["-u", "-c", "import sys, json\n" + script], {}, limits);
  t.after(() => bridge.close());
  return bridge;
}

test("启动超时提供状态，不输出标准错误中的秘密", async (t) => {
  const bridge = fixture(t,
    'sys.stderr.write("private-token")\n' + hold, { startupMs: 500 });
  await assert.rejects(bridge.ready, /夹具启动超时/);
  assert.doesNotMatch(bridge.snapshot(), /private-token/);
});

test("启动失败立即拒绝，不等待启动时限", { timeout: 5000 }, async (t) => {
  const bridge = startBridge("/nonexistent/ssh-mcp-test-python", []);
  t.after(() => bridge.close());
  await assert.rejects(bridge.ready, /夹具无法启动/);
});

test("收到无效协议消息时立即失败，不回显正文", async (t) => {
  const bridge = fixture(t, 'print("private-token", flush=True)\n' + hold);
  await assert.rejects(bridge.ready, /无效 JSON/);
  assert.doesNotMatch(bridge.snapshot(), /private-token/);
});

test("后端就绪后退出会拒绝正在等待的请求", async (t) => {
  const bridge = fixture(t, ready + 'sys.stdin.readline()\nsys.exit(7)\n');
  await bridge.ready;
  await assert.rejects(bridge.fetch("/admin/state"), /夹具已退出/);
  assert.deepEqual(JSON.parse(bridge.snapshot()).exit, { code: 7, signal: null });
  assert.deepEqual(JSON.parse(bridge.snapshot()).pending, []);
});

test("请求超时清理等待项且不输出凭据或请求体", async (t) => {
  const bridge = fixture(t, ready + hold, { requestMs: 100 });
  await bridge.ready;
  await assert.rejects(bridge.fetch("/admin/state", {
    headers: { Authorization: "Bearer private-token" }, body: "private-content",
  }), (error) => {
    assert.match(error.message, /夹具请求超时/);
    assert.doesNotMatch(error.message, /private-token|private-content/);
    return true;
  });
  assert.deepEqual(JSON.parse(bridge.snapshot()).pending, []);
});

test("取消请求清理等待项，已取消的请求不写入管道", async (t) => {
  const bridge = fixture(t, ready + hold);
  await bridge.ready;
  const controller = new AbortController();
  const response = bridge.fetch("/admin/state", { signal: controller.signal });
  // fetch 在 await ready 后登记请求，等待该微任务再取消。
  await Promise.resolve();
  assert.equal(JSON.parse(bridge.snapshot()).pending.length, 1);
  controller.abort();
  await assert.rejects(response, { name: "AbortError" });
  await assert.rejects(bridge.fetch("/admin/state", { signal: controller.signal }),
    { name: "AbortError" });
  assert.deepEqual(JSON.parse(bridge.snapshot()).pending, []);
});
