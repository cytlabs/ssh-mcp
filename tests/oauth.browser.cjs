// 真实 HTTPS / Cookie / 浏览器授权；空服务器清单，不访问线上资源。
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");
const { chromium } = require("playwright");
const root = path.resolve(__dirname, "..");
const origin = "https://127.0.0.1:18766";
(async () => {
  const fixture = spawn(process.env.PYTHON || "python3", ["tests/preview_oauth.py"], {
    cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "src") }, stdio: ["ignore", "pipe", "pipe"],
  });
  let browser, setupURL;
  const exited = new Promise((resolve) => fixture.once("exit", resolve));
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("OAuth 夹具启动超时")), 15000);
      fixture.stdout.once("data", (data) => { setupURL = JSON.parse(data.toString()).setup_url; clearTimeout(timer); resolve(); });
      fixture.once("exit", () => { clearTimeout(timer); reject(new Error("OAuth 夹具退出")); });
    });
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 960 } });
    const page = await context.newPage(), errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("response", (r) => { if (new URL(r.url()).pathname === "/auth/consent") console.log("授权请求状态", r.status()); });
    await page.goto(setupURL);
    await page.getByRole("heading", { name: "创建管理员账号" }).waitFor();
    const password = "browser-fixture-password-only";
    await page.locator("#username").fill("admin");
    await page.locator("#admin-token").fill(password);
    await page.locator("#confirm-password").fill(password);
    await page.locator("#username").fill("admin");
    assert.equal(await page.locator("#bootstrap-token").count(), 0);
    assert.equal(new URL(page.url()).hash, "");
    await page.locator("#login-form button[type=submit]").click();
    await page.locator("#app-view").waitFor({ state: "visible" });
    assert.equal(await page.evaluate(() => document.cookie), "");
    assert.equal(await page.evaluate(() => sessionStorage.length), 0);
    await page.reload();
    await page.locator("#app-view").waitFor({ state: "visible" });
    const client = await (await context.request.post(origin + "/oauth/register", { data: {
      client_name: "浏览器验收客户端 <script>", redirect_uris: ["http://127.0.0.1:19999/callback"],
      token_endpoint_auth_method: "none",
    } })).json();
    const verifier = "v".repeat(64);
    const query = new URLSearchParams({ client_id: client.client_id, redirect_uri: client.redirect_uris[0],
      response_type: "code", code_challenge_method: "S256", code_challenge: crypto.createHash("sha256").update(verifier).digest("base64url"),
      resource: origin + "/mcp", state: "browser-test-state" });
    await page.goto(origin + "/oauth/authorize?" + query);
    await page.locator("#consent-view").waitFor({ state: "visible" });
    assert.ok((await page.locator("#consent-client").textContent()).includes("<script>"));
    assert.equal(await page.locator("#consent-client script").count(), 0);
    fs.mkdirSync(path.join(root, "test-results"), { recursive: true });
    await page.screenshot({ path: path.join(root, "test-results/oauth-consent.png"), fullPage: true });
    console.log("OAuth 夹具：登录、持久 Cookie 和授权页通过");
    let callback;
    await page.route("http://127.0.0.1:19999/callback**", async (route) => {
      callback = new URL(route.request().url());
      await route.fulfill({ contentType: "text/plain; charset=utf-8", body: "授权回调已收到" });
    });
    await page.locator("#allow-consent").click({ noWaitAfter: true, timeout: 10000 });
    console.log("已点击授权");
    await page.getByText("授权回调已收到").waitFor({ timeout: 10000 }).catch(async (error) => {
      console.log("回调阶段：", new URL(page.url()).pathname, await page.locator("#toast").textContent({timeout: 1000}).catch(() => ""));
      await page.screenshot({ path: path.join(root, "test-results/oauth-failure.png"), fullPage: true });
      throw error;
    });
    assert.equal(callback.searchParams.get("state"), "browser-test-state");
    const pairResponse = await context.request.post(origin + "/oauth/token", { form: {
      client_id: client.client_id, grant_type: "authorization_code", code: callback.searchParams.get("code"),
      redirect_uri: client.redirect_uris[0], code_verifier: verifier, resource: origin + "/mcp",
    } });
    assert.equal(pairResponse.status(), 200);
    const pair = await pairResponse.json();
    const mcp = await context.request.post(origin + "/mcp", { headers: {
      Authorization: "Bearer " + pair.access_token, Accept: "application/json, text/event-stream",
    }, data: { jsonrpc: "2.0", id: 1, method: "initialize", params: {
      protocolVersion: "2025-11-25", capabilities: {}, clientInfo: { name: "browser-acceptance", version: "1" },
    } } });
    assert.equal(mcp.status(), 200);
    await page.goto(origin + "/console");
    await page.locator("#app-view").waitFor({ state: "visible" });
    await page.locator("[data-view=clients]").click();
    await page.locator("[data-revoke]").waitFor();
    assert.ok((await page.locator("#client-config").textContent()).includes("codex mcp login"));
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: path.join(root, "test-results/oauth-clients-mobile.png"), fullPage: true });
    await page.locator("[data-revoke]").click();
    await page.locator("#grants-list").getByText(/已撤销/).waitFor();
    assert.equal((await context.request.get(origin + "/mcp", { headers: { Authorization: "Bearer " + pair.access_token } })).status(), 401);
    await page.locator("#logout").click();
    await page.locator("#login-view").waitFor({ state: "visible" });
    await page.reload();
    await page.getByRole("heading", { name: "连接你的工作空间" }).waitFor();
    await page.locator("#username").fill("admin");
    await page.locator("#admin-token").fill(password);
    await page.locator("#login-form button[type=submit]").click();
    await page.locator("#app-view").waitFor({ state: "visible" });
    assert.deepEqual(errors, []);
    console.log("OAuth 浏览器验收通过：设置密码、Cookie 登录、授权回调、MCP 初始化、撤销、移动端、退出和重新登录。");
  } finally {
    await browser?.close();
    fixture.kill("SIGTERM");
    await exited;
  }
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
