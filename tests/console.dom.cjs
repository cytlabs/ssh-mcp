// Real UI + real Python admin/SQLite handlers. SSH is a test fixture; no browser rendering.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const readline = require("node:readline");
const { JSDOM } = require(process.env.JSDOM_MODULE || "jsdom");
const root = path.resolve(__dirname, "..");
const admin = "browser-fixture-only-not-a-real-secret-" + "x".repeat(32);

test(
  "console UI → admin API → SQLite workflow",
  { timeout: 30000 },
  async (t) => {
    const backend = spawn(
      process.env.PYTHON || "python3",
      ["tests/preview_console.py", "--stdio"],
      {
        cwd: root,
        env: { ...process.env, PYTHONPATH: path.join(root, "src") },
        stdio: ["pipe", "pipe", "pipe"],
      },
    );
    let next = 0,
      stderr = "";
    const pending = new Map();
    backend.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    readline.createInterface({ input: backend.stdout }).on("line", (line) => {
      const result = JSON.parse(line),
        request = pending.get(result.id);
      if (request) {
        pending.delete(result.id);
        request.resolve({
          ok: result.status < 400,
          status: result.status,
          json: async () => JSON.parse(result.body),
        });
      }
    });
    backend.on("exit", () => {
      pending.forEach((p) => p.reject(new Error(stderr || "Backend exited")));
      pending.clear();
    });
    const dom = new JSDOM(
      fs.readFileSync(path.join(root, "src/ssh_mcp/static/index.html"), "utf8"),
      {
        url: "http://localhost:8765/console",
        runScripts: "outside-only",
        pretendToBeVisual: true,
      },
    );
    t.after(() => {
      dom.window.close();
      backend.stdin.end();
      backend.kill();
    });
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
    w.fetch = (url, options = {}) =>
      new Promise((resolve, reject) => {
        const id = ++next;
        pending.set(id, { resolve, reject });
        backend.stdin.write(
          JSON.stringify({
            id,
            path: url,
            method: options.method,
            headers: options.headers,
            body: options.body,
          }) + "\n",
        );
        options.signal?.addEventListener(
          "abort",
          () => {
            pending.delete(id);
            reject(new w.DOMException("Aborted", "AbortError"));
          },
          { once: true },
        );
      });
    const errors = [];
    w.addEventListener("error", (event) => errors.push(event.error));
    w.eval(
      fs.readFileSync(path.join(root, "src/ssh_mcp/static/app.js"), "utf8"),
    );
    const $ = (s) => doc.querySelector(s);
    const wait = async (predicate) => {
      for (let i = 0; i < 200; i++) {
        if (predicate()) return;
        await new Promise((r) => setTimeout(r, 10));
      }
      throw new Error(
        "UI condition timed out: " + predicate.toString() + "\n" + stderr,
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

    await t.test(
      "login rejects the wrong token and accepts admin; keeps requested tab session",
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
    await t.test("search and empty result recover", async () => {
      $("#server-search").value = "missing";
      $("#server-search").dispatchEvent(new w.Event("input"));
      assert.match($("#server-rows").textContent, /没有匹配/);
      click("[data-action=clear-search]");
      assert.equal(doc.querySelectorAll(".server-row").length, 3);
    });
    await t.test(
      "create server saves through SQLite and treats HTML as text",
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
    await t.test("edit and test connection use backend handlers", async () => {
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
    await t.test("session creation, input, output, and closure", async () => {
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
    await t.test(
      "client configuration includes endpoint and no admin credential",
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
    await t.test(
      "audit records persist, deletion has explicit confirmation",
      async () => {
        click("[data-view=activity]");
        await new Promise((r) => setTimeout(r, 20));
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
    await t.test(
      "logout clears stored auth, inventory, sessions and dialog state",
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
