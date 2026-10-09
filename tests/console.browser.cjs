// Run in an environment which permits localhost listeners and Chromium.
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const { spawn } = require("node:child_process");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const root = path.resolve(__dirname, "..");
const admin = "browser-fixture-only-not-a-real-secret-" + "x".repeat(32);

(async () => {
  const fixture = spawn(
    process.env.PYTHON || "python3",
    ["tests/preview_console.py", "--port", "8765"],
    {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "src") },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let browser,
    stderr = "";
  fixture.stderr.on("data", (data) => {
    stderr += data;
  });
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error("Fixture startup timeout: " + stderr)),
        10000,
      );
      fixture.stdout.once("data", () => {
        clearTimeout(timer);
        resolve();
      });
      fixture.once("exit", (code) => {
        clearTimeout(timer);
        reject(new Error(`Fixture exited ${code}: ${stderr}`));
      });
    });
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 1440, height: 960 },
    });
    const page = await context.newPage(),
      errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("http://127.0.0.1:8765/console");
    await page.locator("#admin-token").fill(admin);
    await page.locator("#remember").check();
    await page.locator("#login-form button[type=submit]").click();
    await page.locator("#app-view").waitFor({ state: "visible" });
    assert.equal(await page.locator(".server-row").count(), 3);
    await page.reload();
    await page.locator("#app-view").waitFor({ state: "visible" });
    await page.locator("#server-search").fill("no-match");
    await page.getByText("没有匹配的服务器", { exact: true }).waitFor();
    await page.getByRole("button", { name: "清除筛选" }).click();
    await page
      .getByRole("button", { name: "＋ 添加服务器", exact: true })
      .click();
    await page.locator("#server-form [name=id]").fill("browser-added");
    await page.locator("#server-form [name=host]").fill("192.0.2.50");
    await page.locator("#server-form [name=username]").fill("ops");
    await page.locator("#server-form [name=credential]").fill("/etc/key");
    await page
      .locator("#server-form [name=known_hosts]")
      .fill("/etc/known_hosts");
    await page.getByRole("button", { name: "保存服务器" }).click();
    await page.locator("#server-dialog").waitFor({ state: "hidden" });
    await page.locator("[data-action=test][data-id=browser-added]").click();
    await page.locator(".badge.ok").waitFor();
    fs.mkdirSync(path.join(root, "test-results"), { recursive: true });
    await page.screenshot({
      path: path.join(root, "test-results/console-desktop.png"),
      fullPage: true,
    });
    await page.locator("[data-action=open-session]").click();
    await page.locator("#terminal-input").fill("echo hello");
    await page.locator("#terminal-input").press("Enter");
    await page.waitForFunction(() =>
      document
        .querySelector("#terminal-output")
        .textContent.includes("fixture: input received"),
    );
    await page.locator("[data-action=close-session]").click();
    await page.locator("#confirm-dialog button[value=confirm]").click();
    await page.locator("#terminal-input").waitFor({ state: "hidden" });
    await page.locator("[data-view=clients]").click();
    await page.locator("#client-config").waitFor();
    assert.ok(
      !(await page.locator("#client-config").textContent()).includes(admin),
    );
    await page.locator("[data-action=client][data-id=ChatGPT]").click();
    await page
      .getByText("ChatGPT 的 OAuth 接入尚未实现", { exact: true })
      .waitFor();
    await page.locator("[data-view=servers]").click();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({
      path: path.join(root, "test-results/console-mobile.png"),
      fullPage: true,
    });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      "Page has horizontal overflow",
    );
    await page.locator("[data-action=delete]").click();
    await page.locator("#confirm-dialog button[value=confirm]").click();
    await page
      .locator("[data-action=select][data-id=browser-added]")
      .waitFor({ state: "hidden" });
    await page.locator("#logout").click();
    await page.reload();
    await page.locator("#login-view").waitFor({ state: "visible" });
    assert.equal(
      await page.evaluate(() =>
        sessionStorage.getItem("ssh-mcp.console.admin"),
      ),
      null,
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS: desktop/mobile, login persistence, server CRUD, fixture SSH probe, sessions, clients, logout.",
    );
  } finally {
    if (browser) await browser.close();
    fixture.kill();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
