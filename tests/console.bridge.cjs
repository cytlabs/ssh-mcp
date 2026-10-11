// 测试专用 stdio 桥：就绪后才发请求，诊断只记录状态元数据。
const { spawn } = require("node:child_process");
const readline = require("node:readline");

function startBridge(command, args, options = {}, limits = {}) {
  const backend = spawn(command, args, {
    ...options,
    stdio: ["pipe", "pipe", "pipe"],
  });
  const pending = new Map();
  let next = 0, readySeen = false, failure, exit, stderrBytes = 0;
  const statuses = [];
  let resolveReady, rejectReady;
  const ready = new Promise((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });
  // 启动错误可能先于调用方等待就绪；仍由 ready 向调用方报告。
  ready.catch(() => {});
  const snapshot = () => JSON.stringify({
    ready: readySeen, exit, stderrBytes, pending: [...pending.keys()], statuses,
  });
  const fail = (reason) => {
    if (failure) return;
    failure = new Error(`${reason}; ${snapshot()}`);
    clearTimeout(startupTimer);
    rejectReady(failure);
    for (const request of [...pending.values()]) request.finish(failure);
  };
  const startupTimer = setTimeout(
    () => fail("夹具启动超时"), limits.startupMs ?? 15000,
  );
  backend.stderr.on("data", (data) => { stderrBytes += data.length; });
  backend.on("error", () => fail("夹具无法启动"));
  backend.stdin.on("error", () => fail("夹具输入管道已断开"));
  const closed = new Promise((resolve) => {
    backend.once("close", (code, signal) => {
      exit = { code, signal };
      fail("夹具已退出");
      resolve();
    });
  });
  const lines = readline.createInterface({ input: backend.stdout });
  lines.on("line", (line) => {
    let result;
    try { result = JSON.parse(line); }
    catch { fail("夹具返回了无效 JSON"); return; }
    if (!readySeen && result?.event === "ready") {
      readySeen = true;
      clearTimeout(startupTimer);
      resolveReady();
      return;
    }
    if (!readySeen || !Number.isInteger(result?.id) ||
        !Number.isInteger(result.status) || typeof result.body !== "string") {
      fail("夹具返回了无效协议消息");
      return;
    }
    statuses.push({ id: result.id, status: result.status });
    if (statuses.length > 10) statuses.shift();
    pending.get(result.id)?.finish(null, {
      ok: result.status < 400,
      status: result.status,
      json: async () => JSON.parse(result.body),
    });
  });

  return {
    ready,
    snapshot,
    assertHealthy() { if (failure) throw failure; },
    async fetch(url, options = {}) {
      await ready;
      if (failure) throw failure;
      if (options.signal?.aborted) throw new DOMException("Aborted", "AbortError");
      return new Promise((resolve, reject) => {
        const id = ++next;
        const finish = (error, response) => {
          if (!pending.delete(id)) return;
          clearTimeout(timer);
          options.signal?.removeEventListener("abort", abort);
          if (error) reject(error); else resolve(response);
        };
        const abort = () => finish(new DOMException("Aborted", "AbortError"));
        const timer = setTimeout(() => finish(new Error(
          `夹具请求超时; ${snapshot()}`,
        )), limits.requestMs ?? 5000);
        pending.set(id, { finish });
        options.signal?.addEventListener("abort", abort, { once: true });
        backend.stdin.write(JSON.stringify({
          id, path: url, method: options.method,
          headers: options.headers, body: options.body,
        }) + "\n");
      });
    },
    async close() {
      // EOF 让 Python 执行 finally，关闭 SQLite 并删除临时目录。
      fail("测试正在关闭夹具");
      backend.stdin.end();
      const timer = setTimeout(() => backend.kill("SIGKILL"), 2000);
      await closed;
      clearTimeout(timer);
      lines.close();
    },
  };
}

module.exports = { startBridge };
