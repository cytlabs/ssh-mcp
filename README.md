# Portlane

**让 AI 安全、统一地访问你的远程服务器。**

Portlane 是一个自托管、MIT 开源的 SSH MCP 服务。Codex、Claude Code、Cursor 等兼容 MCP 的 AI 客户端可以通过它访问你已配置的服务器，执行 Shell 命令、保持远程会话、读写文件，而不需要在每个客户端复制 SSH 私钥。

**设计原则：** AI 客户端负责理解任务和执行规划；Portlane 负责 MCP → SSH/SFTP 连接、凭据隔离与管理。Web 控制台集中展示运行情况，管理服务器、操作记录和客户端授权。

> **项目状态：** `0.1.0a1` 开发预览。源码和自动化测试已建立，生产 HTTPS/SSH 协议联调已有记录；不同 AI 客户端的完整人工验收仍在进行。不要将其视作经过全面安全审计的多用户生产平台。

## 功能

- **远程接入：** 多服务器；SSH 私钥/密码环境变量；已核验的 `known_hosts`；任意 Shell、PTY、长任务读取、SFTP。
- **MCP：** Streamable HTTP（可通过 HTTPS 公开）和本地 stdio；OAuth 浏览器授权与可选的静态 Bearer Token。
- **控制台：** 概览、服务器管理、操作记录、MCP 接入；搜索、过滤、分页；浅色与深色主题。
- **存储：** SQLite 服务器清单、管理员操作记录、OAuth 身份及授权。网页不保存 SSH 密码或私钥正文。

不提供多用户 RBAC、命令白名单、逐命令审批或永久命令审计。所有已授权客户端共享相同服务器权限，实际执行权限取决于远程 SSH 账户。参见 [安全说明](SECURITY.md)。

## 快速开始

要求 Python 3.10+、可访问目标机器 SSH 端口的网络，以及可信 HTTPS 入口（用于浏览器 OAuth）。

```sh
git clone https://github.com/cytlabs/ssh-mcp.git
cd ssh-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install uv==0.12.23
uv sync --locked
cp config.example.json config.json
mkdir -p secrets
chmod 700 secrets
```

编辑 `config.json`，**删除示例服务器或替换为真实且明确授权的服务器**；确认 `known_hosts` 内的主机公钥可信。SSH 私钥保留在服务端文件中，密码通过环境变量名称引用，不粘贴进控制台。

```sh
uv run --no-sync ssh-mcp check --config config.json
uv run --no-sync ssh-mcp serve --config config.json
```

应用默认监听 `127.0.0.1:8000`。远程访问请配置可信代理和 HTTPS，参见 [部署指南](docs/deployment.md)。**不要直接把本地明文端口暴露到公网。**

### 初始化管理账号

示例配置使用 `http.auth_mode: "oauth"`。第一次启动会生成一次性初始化链接，存放在身份数据库旁的受保护文件中；使用该链接创建用户名和密码。之后通过 `/console` 登录。

控制台管理只保留四个页面：**概览、服务器、操作记录、MCP 接入**。Agent 可通过 MCP 工具使用 Shell、持久会话和文件操作。

### 接入 AI 客户端

将部署后的公开 HTTPS MCP URL（如 `https://ssh-mcp.example.com/mcp`）添加到受支持客户端。OAuth 流程由浏览器确认授权；具体支持情况以客户端版本和实测为准。

Codex CLI 示例：

```sh
codex mcp add ssh_mcp --url https://ssh-mcp.example.com/mcp
codex mcp login ssh_mcp
```

重新加载 MCP 后，可让 Agent 调用 `list_servers` 查看已配置的主机。更多客户端示例与静态 Token 兼容方式见 [MCP 接入指南](docs/clients.md)。

## 文档

| 主题 | 文档 |
| --- | --- |
| 安装与 HTTPS 部署 | [部署指南](docs/deployment.md) |
| 控制台、账号与分页 | [控制台说明](docs/console.md) |
| Codex / Claude Code / Cursor 接入 | [客户端接入](docs/clients.md) |
| 常见问题 | [FAQ](docs/faq.md) |
| 架构和产品边界 | [架构设计](docs/architecture.md) |
| 安全与漏洞反馈 | [SECURITY](SECURITY.md) |
| 参与开发 | [贡献指南](CONTRIBUTING.md) |
| 产品计划和已知问题 | [ROADMAP](ROADMAP.md) |
| 实际验证范围 | [验证记录](docs/verification.md) |
| 变更记录 | [CHANGELOG](CHANGELOG.md) |

## 开发与测试

正式运行时控制台无需 Node.js 或前端构建；Node.js、jsdom 和 Playwright 仅用于开发验证。

```sh
uv sync --locked --extra dev --group build
uv run --no-sync ruff check .
uv run --no-sync python -m unittest discover -s tests -v

npm ci
npm run test:ui
npx playwright install --with-deps chromium
npm run test:browser
PYTHON=.venv/bin/python npm run test:oauth-browser
```

自动测试使用临时 SQLite、独立测试凭据和回环 SSH/HTTP 夹具，**不会连接真实生产服务器**。涉及实际部署的联调请先阅读 [低影响检查指南](docs/live-ssh-check.md)。

## 参与和许可

欢迎提交可以复现的问题、文档修订和有测试的改进。涉及 SSH 凭据、认证、授权的内容请先阅读 [贡献指南](CONTRIBUTING.md) 和 [安全说明](SECURITY.md)。不要在公开 Issue/PR 中发布私钥、Token、生产地址或未脱敏日志。

采用 [MIT License](LICENSE)。源代码公开不等于已经完成正式版本发布或安全验收。
