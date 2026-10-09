# 贡献指南

SSH MCP 为 AI 客户端提供通用 SSH 连接、命令、终端和文件能力。
贡献应围绕这些能力及客户端互通展开；不引入业务专用工具或内置 Agent 框架。
项目文档、Issue、PR 说明和提交说明使用中文。协议字段、代码标识符及标准文件名沿用现有约定。

## 开发环境

使用 Linux/macOS、Python 3.10+ 和 uv 0.12.23。集成测试需要 POSIX Shell 与 PTY，CI 在 Linux 上运行。

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install uv==0.12.23
uv sync --locked --extra dev --group build
ruff check .
SSH_MCP_REQUIRE_INTEGRATION=1 python -m unittest discover -s tests -v
python -m build --no-isolation
python scripts/check_wheel.py
pip-audit
```

自动测试不能使用生产 SSH 目标。集成夹具生成临时主机密钥、用户密钥和密码，
通过回环地址运行真实加密 SSH/SFTP、子进程和 HTTP MCP 客户端。
生命周期单元测试另用模拟传输验证并发、取消和超时，不能单独证明真实互通。
需要测试管理员授权的服务器时，使用独立的 [低影响 SSH 检查](docs/live-ssh-check.md)。
该脚本不进入自动测试或 CI，默认不写远程文件。

## 前端测试

正式前端不需要构建；Node.js 只用于开发测试。版本要求见 `package.json`，
本地已核对 Node.js 24.18.0。

```sh
npm ci
npm run test:ui
npx playwright install --with-deps chromium
npm run test:browser
```

UI 测试使用临时 SQLite 和模拟 SSH。浏览器截图保存到被 Git 忽略的 `test-results/`。
真实 SSH 协议验证由 Python 集成测试负责。详见 [管理控制台](docs/console.md)。

## 修改与评审

1. 说明用户遇到的问题、触发条件和修改后的行为。
2. 保持工具名称及调用约定稳定；不兼容变更要说明迁移方法。
3. 认证、生命周期或文件操作的变更应配有能够证明行为的测试。
4. 同步相关文档及 `CHANGELOG.md`，明确仍未完成的内容。
5. 只报告实际执行的检查，不能把跳过的集成测试记为通过。

不要提交真实服务器清单、凭据、私钥、`.env` 或私人命令输出。
示例地址使用保留的示例地址；日志和错误不能泄露凭据、输入正文或底层异常中的敏感信息。
配置样例和部署模板也是产品的一部分，需审查其默认值。
新增依赖应有明确用途，许可证应允许本项目按 MIT 发布。

## 版本发布

首个正式版本前，完成 `ROADMAP.md` 中的发布条件，记录实际测试的依赖版本，
通过安装包、容器及真实客户端验收，并核实漏洞报告渠道和软件包名称。
只有完成验证的提交才能打版本标签。公开源码不代表已经发布稳定版本。

所有贡献遵循本仓库的 MIT 许可证。讨论应围绕具体问题和可复现证据展开。

## 依赖与构建记录

见 [可复现安装与构建](docs/reproducible-builds.md)。正常安装使用 `uv sync --locked` 和 `npm ci`，不要自动更新锁文件。
