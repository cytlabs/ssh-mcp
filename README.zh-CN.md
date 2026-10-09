# SSH MCP

**让 AI 通过 MCP 使用真实的 SSH 终端，登录凭证由服务端保管。**

[English](README.md) · [部署说明](docs/deployment.md) · [管理控制台](docs/console.md) · [客户端接入](docs/clients.md)

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
- 带 Bearer Token 鉴权的 Streamable HTTP，以及本地 stdio。
- 配置校验 CLI、会话回收、输出容量限制及不记录命令正文的操作日志。
- 内置中文管理控制台：服务器增删改、连接测试、终端会话、MCP 接入与操作记录。
- SQLite 持久化服务器列表和管理操作记录，无需额外数据库服务。

已通过本地基础测试及页面到管理接口、SQLite 的 DOM 流程测试。真实浏览器视觉检查、SSH/MCP 集成测试及 Docker 构建尚未执行；
真实云端部署和客户端操作验收尚未完成。详情见 [验证记录](docs/verification.md)。

## 快速启动

准备 Python 3.10+、pip/venv，以及可访问目标服务器 SSH 端口的网络。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
cp config.example.json config.json
mkdir -p secrets
chmod 700 secrets
```

修改 `config.json` 中的服务器，删除不使用的示例条目。私钥放在服务端文件中，
密码通过 `password_env` 引用服务端环境变量。`known_hosts` 必须包含核验过的主机公钥。

```sh
export SSH_MCP_TOKEN="$(ssh-mcp generate-token)"
export SSH_MCP_ADMIN_TOKEN="$(ssh-mcp generate-token)"
ssh-mcp check --config config.json
ssh-mcp serve --config config.json
```

默认只监听 `127.0.0.1:8000`，MCP 路径为 `/mcp`。
远程使用时，按 [部署说明](docs/deployment.md) 配置 HTTPS 入口。

浏览器打开 `/console`，使用独立的管理员 Token 登录。首次启动将 JSON 中的服务器
导入 SQLite，以后通过页面维护并立即生效。配置和记录在重启后保留，SSH 会话不恢复。
Token 区别、数据库位置和备份方式见 [管理控制台说明](docs/console.md)。

## 使用方式

用户说“查看我有哪些服务器”，AI 调用 `list_servers`。
用户说“看看测试服务器上的 Docker 容器”，AI 选择服务器并执行 `docker ps -a`。
用户说“修改项目然后运行测试”，AI 使用通用终端和文件工具自主完成。

长任务返回 `session_id`，AI 通过 `read_output` 获取后续输出。
需要保留目录和环境变量时，先调用 `create_session`，再用 `send_input` 连续操作。
文件上传下载直接在 MCP 请求中携带分块内容，不要求 AI 能访问自己的本地磁盘。

## 第一版的边界

- 一个服务实例对应一个可信操作者；持有同一 Token 的客户端共享服务器和会话。
- 会话跨 MCP 请求保留；服务重启后不恢复。需要更长生命周期时，AI 可自行使用 tmux 等工具。
- 输出缓冲有容量上限，超出后会明确报告丢弃的字符数。
- 超时会请求终止进程并关闭 SSH 通道，但不能保证结束已脱离终端的子进程。
- Codex、Cursor、Claude Code 等带认证请求头的客户端有接入示例，尚未逐一实机验收。
- ChatGPT 的 OAuth 接入需要额外的 OAuth 网关或后续原生 OAuth 支持，当前不宣称直接兼容。

项目按独立开源产品维护，采用 [MIT 许可证](LICENSE)。
参见 [产品路线图](ROADMAP.md)、[贡献指南](CONTRIBUTING.md) 和 [安全边界](SECURITY.md)。
