// 真实页面脚本与 Python 管理 API / SQLite；SSH 为模拟夹具，不验证浏览器渲染。
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { startBridge } = require("./console.bridge.cjs");
const { JSDOM } = require(process.env.JSDOM_MODULE || "jsdom");
const root = path.resolve(__dirname, "..");
const admin = "browser-fixture-only-not-a-real-secret-" + "x".repeat(32);

for (const startupDelay of [0, 3000]) test(
  `控制台 → 管理 API → SQLite（启动延迟 ${startupDelay}ms）`,
  { timeout: 90000 },
  async (t) => {
    const bridge = startBridge(
      process.env.PYTHON || "python3",
      ["tests/preview_console.py", "--stdio", "--startup-delay-ms", String(startupDelay)],
      { cwd: root, env: { ...process.env, PYTHONPATH: path.join(root, "src") } },
    );
    let dom;
    t.after(async () => {
      dom?.window.close();
      await bridge.close();
    });
    await bridge.ready;
    dom = new JSDOM(
      fs.readFileSync(path.join(root, "src/ssh_mcp/static/index.html"), "utf8"),
      {
        url: "http://localhost:8765/console",
        runScripts: "outside-only",
        pretendToBeVisual: true,
      },
    );
    const w = dom.window,
      doc = w.document;
    w.HTMLDialogElement.prototype.showModal = function () {
      this.open = true;
    };
    w.HTMLDialogElement.prototype.close = function (value) {
      this.open = false;
      if (value !== undefined) this.returnValue = value;
      this.dispatchEvent(new w.Event("close"));
    };
    w.fetch = (url, options) => bridge.fetch(url, options);
    const errors = [];
    w.addEventListener("error", (event) => errors.push(event.error));
    w.eval(
      fs.readFileSync(path.join(root, "src/ssh_mcp/static/app.js"), "utf8"),
    );
    const $ = (s) => doc.querySelector(s);
    const wait = async (predicate) => {
      const deadline = performance.now() + 8000;
      while (performance.now() < deadline) {
        bridge.assertHealthy();
        if (errors.length) throw new Error("页面脚本发生异常");
        if (predicate()) return;
        await new Promise((r) => setTimeout(r, 10));
      }
      throw new Error(
        "页面等待超时: " + predicate.toString() + "; " + bridge.snapshot(),
      );
    };
    const click = (selector) => {
      assert.ok($(selector), selector);
      $(selector).click();
    };
    const submit = (selector) => {
      const form = $(selector);
      form.dispatchEvent(
        new w.SubmitEvent("submit", {
          bubbles: true,
          cancelable: true,
          submitter:
            form.querySelector("button[type=submit]") ||
            form.querySelector("button"),
        }),
      );
    };
    const setField = (name, value) => {
      $("#server-form").elements[name].value = value;
    };

    // 这是一个有序的用户旅程。前置步骤失败后，保留首个错误，跳过依赖步骤。
    let failed = false;
    const step = (name, run) => t.test(name, {
      skip: failed ? "前置步骤失败" : false,
    }, async () => {
      try { await run(); }
      catch (error) { failed = true; throw error; }
    });

    await step(
      "登录拒绝错误 Token，接受管理员 Token 并按选择保留会话",
      async () => {
        $("#admin-token").value = "wrong".repeat(10);
        submit("#login-form");
        await wait(() => $("#login-error").textContent.includes("Token"));
        $("#admin-token").value = admin;
        $("#remember").checked = true;
        submit("#login-form");
        await wait(() => !$("#app-view").hidden);
        assert.equal(doc.querySelectorAll(".server-row").length, 3);
        assert.equal(w.sessionStorage.getItem("ssh-mcp.console.admin"), admin);
        assert.equal($("#admin-token").value, "");
      },
    );
    await step("搜索和空结果恢复", async () => {
      $("#server-search").value = "missing";
      $("#server-search").dispatchEvent(new w.Event("input"));
      assert.match($("#server-rows").textContent, /没有匹配/);
      click("[data-action=clear-search]");
      assert.equal(doc.querySelectorAll(".server-row").length, 3);
    });
    await step(
      "创建服务器保存到 SQLite，HTML 按文本展示",
      async () => {
        click("#add-server");
        for (const [k, v] of Object.entries({
          id: "browser-added",
          host: "192.0.2.50",
          username: "ops",
          description: "<img src=x onerror=alert(1)>",
          credential: "/etc/key",
          known_hosts: "/etc/known_hosts",
        }))
          setField(k, v);
        submit("#server-form");
        await wait(
          () =>
            !$("#server-dialog").open &&
            doc.querySelectorAll(".server-row").length === 4,
        );
        assert.equal($("#page-content img"), null);
        assert.match($("#server-detail").textContent, /browser-added/);
        click("#refresh");
        await wait(() => !$("#refresh").disabled);
        assert.ok(
          doc.querySelector("[data-action=select][data-id=browser-added]"),
        );
      },
    );
    await step("编辑与连接检查调用真实管理处理器", async () => {
      click("[data-action=edit]");
      setField("description", "已编辑");
      submit("#server-form");
      await wait(
        () =>
          !$("#server-dialog").open &&
          $("#server-detail").textContent.includes("已编辑"),
      );
      click("[data-action=test][data-id=browser-added]");
      await wait(() => $("#server-rows").textContent.includes("可连接"));
    });
    await step("会话创建、输入、输出和关闭", async () => {
      click("[data-action=open-session]");
      await wait(() => !!$("#terminal-input"));
      $("#terminal-input").value = "echo hello";
      submit("#terminal-form");
      await wait(() =>
        $("#terminal-output").textContent.includes("fixture: input received"),
      );
      click("[data-action=close-session]");
      await wait(() => $("#confirm-dialog").open);
      $("#confirm-dialog").close("confirm");
      await wait(() => !$("#terminal-input"));
    });
    await step(
      "客户端配置包含入口且不含管理员凭据",
      async () => {
        click("[data-view=clients]");
        assert.match($("#client-config").textContent, /bearer_token_env_var/);
        assert.ok(!$("#client-config").textContent.includes(admin));
        click("[data-action=client][data-id=Cursor]");
        assert.match($("#client-config").textContent, /env:SSH_MCP_TOKEN/);
        click("[data-action=client][data-id=ChatGPT]");
        assert.match($("#page-content").textContent, /尚未实现/);
      },
    );
    await step(
      "审计记录持久化，删除需要明确确认",
      async () => {
        click("[data-view=activity]");
        await wait(() => $("#page-content").textContent.includes("创建会话"));
        click("#refresh");
        await wait(() => !$("#refresh").disabled);
        assert.match($("#page-content").textContent, /创建会话/);
        assert.ok(!$("#page-content").textContent.includes("echo hello"));
        click("[data-view=servers]");
        click("[data-action=select][data-id=browser-added]");
        click("[data-action=delete]");
        await wait(() => $("#confirm-dialog").open);
        $("#confirm-dialog").close("confirm");
        await wait(
          () =>
            !doc.querySelector("[data-action=select][data-id=browser-added]"),
        );
      },
    );
    await step(
      "退出清除认证、清单、会话和对话框状态",
      async () => {
        click("#logout");
        assert.ok($("#app-view").hidden);
        assert.equal($("#page-content").textContent, "");
        assert.equal(w.sessionStorage.getItem("ssh-mcp.console.admin"), null);
        assert.deepEqual(errors, []);
      },
    );
  },
);
