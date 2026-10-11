# SSH MCP

**让 AI 通过 MCP 使用真实的 SSH 终端，登录凭证由服务端保管。**

[部署说明](docs/deployment.md) · [管理控制台](docs/console.md) · [客户端接入](docs/clients.md)

SSH MCP 是一个独立部署的通用连接工具。即使 AI 客户端没有本地 SSH 环境，
也能通过远程 MCP 选择服务器、执行 Shell 命令、保留终端会话和传输文件。

MCP 负责连接与执行，任务理解和规划由 AI 客户端完成。
不封装 Docker、Nginx 等业务工具，不设置命令白名单；操作权限由远程 SSH 账户决定。

## 当前版本

`0.1.0a1`，处于开发预览阶段，尚未发布。

已实现源码：

- 多服务器配置，SSH 密钥与密码认证，严格校验目标主机密钥。
- 任意 Shell 命令、标准输出、错误输出、退出状态、超时及长任务轮询。
- 持久 Shell、PTY、连续输入、窗口调整和独立会话。
- SFTP 文件读写、删除、目录查询，以及 Base64 分块上传下载。
- OAuth 浏览器授权的 Streamable HTTP、可选静态 Bearer Token，以及本地 stdio。
- 配置校验 CLI、会话回收、输出容量限制及不记录命令正文的操作日志。
- 内置中文管理控制台：服务器增删改、连接测试、终端会话、MCP 接入与操作记录。
- SQLite 持久化服务器列表和管理操作记录，无需额外数据库服务。

GitHub Actions 已运行真实回环 SSH/SFTP、HTTP/stdio MCP 集成测试，以及桌面/手机浏览器流程和 Docker 构建。
已完成生产部署及公开 HTTPS/MCP/SSH 联调；真实 AI 客户端对话验收仍待完成。详细结果、依赖审计状态与运行链接见 [验证记录](docs/verification.md)。

## 快速启动

准备 Python 3.10+、pip/venv，以及可访问目标服务器 SSH 端口的网络。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install uv==0.12.23
uv sync --locked --extra dev --group build
cp config.example.json config.json
mkdir -p secrets
chmod 700 secrets
```

修改 `config.json` 中的服务器，删除不使用的示例条目。私钥放在服务端文件中，
密码通过 `password_env` 引用服务端环境变量。`known_hosts` 必须包含核验过的主机公钥。

```sh
ssh-mcp check --config config.json
ssh-mcp serve --config config.json
```

默认只监听 `127.0.0.1:8000`，MCP 路径为 `/mcp`。
远程使用时，按 [部署说明](docs/deployment.md) 配置 HTTPS 入口。

首次启动自动生成一次性初始化链接，保存在身份数据库旁的 `*.auth.setup-link` 文件（仅服务账户可读）。
通过该链接创建用户名和密码，以后直接打开 HTTPS `/console` 登录，无需填写 Token。
AI 客户端填写 MCP URL 并在浏览器授权，无需设置 Token 环境变量。首次启动将 JSON 中的服务器
导入 SQLite，以后通过页面维护并立即生效。配置和记录在重启后保留，SSH 会话不恢复。
认证区别、数据库位置和备份方式见 [管理控制台说明](docs/console.md)。

## 使用方式

用户说“查看我有哪些服务器”，AI 调用 `list_servers`。
用户说“看看测试服务器上的 Docker 容器”，AI 选择服务器并执行 `docker ps -a`。
用户说“修改项目然后运行测试”，AI 使用通用终端和文件工具自主完成。

长任务返回 `session_id`，AI 通过 `read_output` 获取后续输出。
需要保留目录和环境变量时，先调用 `create_session`，再用 `send_input` 连续操作。
文件上传下载直接在 MCP 请求中携带分块内容，不要求 AI 能访问自己的本地磁盘。

## 第一版的边界

- 一个服务实例对应一个可信操作者；获授权的客户端共享全部服务器和会话。
- 会话跨 MCP 请求保留；服务重启后不恢复。需要更长生命周期时，AI 可自行使用 tmux 等工具。
- 输出缓冲有容量上限，超出后会明确报告丢弃的字符数。
- 超时会请求终止进程并关闭 SSH 通道，但不能保证结束已脱离终端的子进程。
- 已实现 OAuth 发现、动态客户端注册、PKCE、同意、刷新和撤销；客户端覆盖仍需逐一实机验收。
- ChatGPT 等客户端的最终可用性取决于客户端版本、组织策略及接入验收，不以协议测试代替。

项目按独立开源产品维护，采用 [MIT 许可证](LICENSE)。
参见 [产品路线图](ROADMAP.md)、[贡献指南](CONTRIBUTING.md) 和 [安全边界](SECURITY.md)。

## 开发与验证

```sh
python -m pip install uv==0.12.23
uv sync --locked --extra dev --group build
ruff check .
SSH_MCP_REQUIRE_INTEGRATION=1 python -m unittest discover -s tests -v
python -m build --no-isolation
python scripts/check_wheel.py
pip-audit
```

自动测试使用临时凭据和本机回环 SSH/SFTP 服务，不读取真实配置或连接生产服务器。
手动联调使用 [低影响 SSH 检查](docs/live-ssh-check.md)，仅针对管理员明确授权的目标。
前端测试、开发环境和提交流程见 [贡献指南](CONTRIBUTING.md)。
项目文档、功能说明、Issue/PR 模板和提交说明以中文为主。
