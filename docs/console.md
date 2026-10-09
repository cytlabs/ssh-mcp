# 管理控制台与 SQLite

前端与 Python 服务一起发布，在 `/console` 访问，无需单独部署或安装 Node.js。
界面为原生 HTML/CSS/JavaScript，不加载第三方 CDN。Node.js 仅用于开发测试。

## 启动

安装 Python 依赖后，在服务端分别设置两个不同的随机 Token：

```sh
export SSH_MCP_TOKEN="$(ssh-mcp generate-token)"
export SSH_MCP_ADMIN_TOKEN="$(ssh-mcp generate-token)"
ssh-mcp serve --config config.json --database data/ssh-mcp.sqlite3
```

本机访问 `http://127.0.0.1:8000/console`；远程访问必须通过已部署的 HTTPS 入口。
在页面中输入 `SSH_MCP_ADMIN_TOKEN`。这个值只供人工管理使用，不要交给 AI。
AI 客户端仍使用 `SSH_MCP_TOKEN` 连接 `/mcp`。两个 Token 相同会导致启动失败。

不设置管理员 Token 时，MCP 原有接口仍可使用，管理接口返回配置提示。
页面外壳可以在未登录时加载，但服务器数据和操作均要求管理员认证。

默认登录只保留在页面内存中。勾选「在此标签页内保持登录」后，Token 存在
`sessionStorage`，刷新时会重新验证。退出会清除 Token、服务器信息和终端输出。
这不是 HttpOnly Cookie 登录或多用户账户系统。

## 页面能力

| 页面 | 功能 |
| --- | --- |
| 服务器 | 查看、搜索、认证类型筛选、添加、编辑、移除、测试 SSH 登录 |
| 终端会话 | 创建非 PTY Shell、查看现有 MCP 会话输出、逐行发送命令、关闭会话 |
| MCP 接入 | 复制 Codex、Cursor、Claude Code 的地址与配置；明确 ChatGPT OAuth 的待支持状态 |
| 操作记录 | 查看最近 50 条管理操作，SQLite 最多保留 1,000 条 |

连接状态默认显示「未检测」。只有真实测试返回成功后才显示「可连接」，不把已配置
等同于在线。测试只执行 SSH 登录与关闭，不执行远程命令。

新增服务器填写的是服务端已有的私钥路径或密码环境变量名称，不是私钥/密码内容。
页面不会返回密钥内容、环境变量的值或服务端认证 Token。已核验的 `known_hosts`
文件仍由管理员准备。新增的环境变量需要由服务进程环境提供；若刚修改环境，需重启服务。
建议使用绝对文件路径；网页提交的相对路径以数据库目录为基准。

终端输出以纯文本显示，移除常见 ANSI 控制序列，客户端最多保留最近 100,000 个字符。
它提供逐行 Shell 操作，不是 xterm 全屏终端模拟器。vim/top 等全屏交互请使用支持 PTY
的 MCP 客户端。会话与 AI 客户端共享；关闭会话会释放连接和服务端缓冲输出。

## 持久化规则

- 使用 Python 标准库 SQLite，不需要 MySQL 或单独数据库服务。
- 默认位置是配置文件同目录下的 `data/ssh-mcp.sqlite3`，可用 `--database` 指定。
- 第一次启动数据库时，从 JSON 的 `servers` 导入。之后数据库成为服务器列表的来源。
  修改 JSON 不会覆盖网页保存的服务器，也不会把已删除的条目重新导入。
- HTTP 监听地址、公开 URL、资源限制等运行设置仍在 JSON 中，修改后重启生效。
- 网页增删改立即更新当前 HTTP 服务和 MCP 工具的服务器列表；不需要重启。
- 现有 SSH 会话继续使用创建时的连接。仍有运行会话的服务器不能删除，先关闭会话。
- 编辑请求带配置版本号，冲突时返回 409，不覆盖其他窗口的修改。刷新后重新编辑。
- 一个运行实例使用一个数据库。单独启动的 stdio 进程只在启动时读取库存，不做跨进程实时同步。
- 数据库保存服务器元数据、凭据引用及管理操作记录，不保存命令正文、输出或 SSH 密码。
- 数据库文件权限为 `0600`，自动创建的数据目录为 `0700`。仍需确保部署账户的文件隔离。

`ssh-mcp check` 与 `ssh-mcp list-servers` 会读取默认或指定的现有数据库；数据库不存在
时仅检查/列出 JSON，不会为了检查而新建数据库。使用自定义路径时应给所有命令传入
相同的 `--database`。

## 部署与备份

Docker 模板将数据库保存到独立的 `ssh_mcp_data` 数据卷（容器内 `/data`）；配置和密钥
仍只读挂载。不要用 `docker compose down -v` 卸载需要保留的数据卷。
systemd 模板使用 `/var/lib/ssh-mcp/inventory.sqlite3`，由 `StateDirectory` 创建可写目录。

备份时停止服务，再复制数据库文件，并另外安全备份运行配置、密钥和环境变量配置。
恢复到同一版本后校验权限，再启动服务。数据库不包含会话，备份不会恢复正在运行的终端。

## 开发验证

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
npm install
npm run test:ui
npx playwright install --with-deps chromium
npm run test:browser
```

前端开发测试已核对 Node.js 24.18.0；测试依赖版本与 Node 范围见 `package.json`。
DOM 测试通过标准输入输出连接真实管理接口与临时 SQLite，只有 SSH 部分使用模拟夹具。
浏览器脚本在回环地址启动同一夹具，检查桌面、手机交互并保存截图到 `test-results/`。
可单独运行 `PYTHONPATH=src python3 tests/preview_console.py` 查看**测试夹具**；
它不连接真实服务器，也不是生产启动方式。夹具 Token 仅用于测试，写在测试源码中。

本地 DOM/API/SQLite 测试已通过；GitHub Actions 中的 Chromium 桌面/手机流程也已通过并上传截图。
本地端口监听和浏览器启动仍受环境限制，线上真实 SSH 控制台流程尚待部署验收。
具体范围见 [验证记录](verification.md)，不能把模拟 SSH 的浏览器流程当作真实服务器验收。
