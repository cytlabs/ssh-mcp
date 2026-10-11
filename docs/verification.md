# 验证记录

最近更新：2026-10-11。版本：`0.1.0a1`（开发预览，未发布正式版本）。

## 2026-10-11：生产部署与真实协议、控制台联调

部署应用基于主分支 `e30260d`，运行版本 `0.1.0a1`。独立 systemd 进程和 Python 3.12 环境、
SQLite、独立 MCP/管理员 Token、普通 SSH 目标账户及服务端专用密钥已配置。
应用只监听回环地址，由现有 Nginx 的独立 HTTPS 端口代理；可信 IP 证书已核验，
已有续期定时器最近执行成功，其任务包含 Nginx 重载。用户放行云安全组后，公网访问通过。

Docker 基础镜像拉取失败，服务器 Python 镜像源亦缺少部分锁定版本；本次采用原生部署，
在可联网的构建环境下载目标 Python 3.12 wheel，经 `uv.lock` 导出的版本和哈希校验后离线安装。
未改变运行依赖版本；生产环境只安装运行依赖与项目 wheel。容器构建仍以既有 CI 为证据。

| 检查 | 本次结果 |
| --- | --- |
| 公开 HTTPS | 从开发主机直连控制台返回 200，TLS 证书验证通过；匿名/错误 Token 的 MCP 请求返回 401 |
| 官方 MCP SDK → HTTPS → SSH | 初始化、清单无凭据字段、标准输出/错误、非零退出码、PTY 状态保留、会话关闭通过 |
| 远程文件与 Shell 校验 | 独立随机临时目录内完成中文创建/修改、Shell 校验、二进制上传下载及清理 |
| 长任务与重新连接 | 30 秒命令超过单次 25 秒等待上限，另一 MCP 连接能够找回会话并读取完成结果 |
| 控制台真实浏览器 | Chromium 经公网入口完成登录/刷新/退出、真实 SSH 终端、桌面/手机布局；无页面脚本错误 |
| 认证边界 | MCP Token 不能访问管理 API；管理员 Token 不能调用 MCP；错误 Host/Origin 被拒绝 |
| 持久化与运维 | 无运行会话时备份 SQLite/配置，仅重启本服务；重启后清单、认证及 SSH 连接正常；已启用开机启动 |
| 现有业务复查 | 原网站返回 200，原受保护 MCP 入口返回 401；原代理路由保留 |
| 本地代码验证 | Python 47 项通过，含真实回环集成测试及新增 HTTPS URL 校验；Ruff、wheel 资源、DOM 和桌面/手机夹具测试通过 |

本次联调脚本见 `scripts/smoke_ssh.py`、`scripts/smoke_http.py`，没有把生产地址、Token、
SSH 私钥或线上截图提交到仓库。部署实例配置、备份位置和回滚步骤保存在操作者私人交付记录。

Python 3.10 完整测试退出时仍出现 `BaseSubprocessTransport` 的 `Event loop is closed` 警告，
测试退出码为 0；单独以 [Issue #8](https://github.com/cytlabs/ssh-mcp/issues/8) 跟踪，未隐藏异常。

**尚未完成真实 AI 客户端的对话式验收。** SDK 和管理控制台结果不替代该验收，因此
[Issue #1](https://github.com/cytlabs/ssh-mcp/issues/1) 保持打开。ChatGPT OAuth 仍待实现（#2）。

## 2026-10-11：DOM 测试稳定性修复

主分支 `dad8c51` 的 [首次 CI](https://github.com/cytlabs/ssh-mcp/actions/runs/37889275394/attempts/1)
在 DOM 登录错误提示等待处超时，其余依赖步骤连锁失败；
[第二次运行](https://github.com/cytlabs/ssh-mcp/actions/runs/37889275394/attempts/2) 全部通过。
重跑没有修改代码，不能据此认为偶发问题已经修复，见 [Issue #6](https://github.com/cytlabs/ssh-mcp/issues/6)。

本轮增加明确的夹具就绪信号、独立启动/请求/页面时限、有限状态诊断和失败后跳过依赖步骤。
正常及延迟 3 秒启动的 DOM 流程共 18 项通过，另有 6 项桥接异常与取消测试通过。
本地使用已有 jsdom 安装，并非重新执行锁文件安装；完整锁定依赖与浏览器检查仍以本次 CI 为准。
提交 `bc2694e` 的 [PR CI](https://github.com/cytlabs/ssh-mcp/actions/runs/38118471762)
及 [分支 CI](https://github.com/cytlabs/ssh-mcp/actions/runs/38118453365) 均通过全部五个任务。
锁定安装后的前端测试 24 项通过、无跳过，桌面/手机浏览器流程通过；三版本 Python、构建、
审计及容器检查通过。原偶发超时的原因未被唯一确定；本轮已消除启动就绪缺口并补充诊断，
如再出现超时，应根据新状态信息继续定位，不能用自动重试掩盖。
本地 Python 35 项通过、集成模块跳过，原因是该环境未安装运行依赖。
只读部署检查脚本通过 Shell 语法检查，尚未在生产主机执行；未进行生产部署或真实客户端验收。

## 依赖锁定后验证（PR #5）

提交 `632d7c70` 的 [CI](https://github.com/cytlabs/ssh-mcp/actions/runs/37889056073) 五个任务全部通过：Python 3.10/3.12/3.13 各 45 项测试、Ruff、非隔离打包、wheel 控制台资源检查、Python 依赖审计，以及 Docker 构建、DOM/桌面/手机浏览器流程与 npm 审计。

`uv.lock` 与 `package-lock.json` 已提交；应用基础镜像固定摘要，CI 上传各 Python 版本安装包和构建记录。详见 [可复现安装与构建](reproducible-builds.md)。本轮没有部署生产服务器，也没有完成 OAuth 或真实 AI 客户端验收。

本轮本地 45 项 Python 测试、DOM 9 项、打包与审计通过。Python 测试退出时出现 subprocess 事件循环清理警告，未导致测试失败；本地 Chromium 下载失败且无 Docker，相关验证采用上述 CI 结果。

## 早期 GitHub CI 验证

基线提交：[035ce343](https://github.com/cytlabs/ssh-mcp/commit/035ce343d30821660957325051b4783593dbe0b2)。
[CI 第 3 次运行](https://github.com/cytlabs/ssh-mcp/actions/runs/37884474129) 的五个任务全部通过。
后续提交以其对应的 [Actions 结果](https://github.com/cytlabs/ssh-mcp/actions) 为准，不自动沿用基线结论。

| 检查 | 结果与范围 |
| --- | --- |
| Python 3.10 / 3.12 / 3.13 | 每个版本 45 项测试通过，集成模块未跳过 |
| Ruff 与 Python 编译 | 三个 Python 版本均通过 |
| wheel / 源码包构建 | 三个 Python 版本均通过 |
| pip-audit | 三个 Python 版本均通过，未发现已知依赖漏洞；本项目尚未发布 PyPI，项目本体不在漏洞库中 |
| Docker | 镜像构建及容器内版本命令通过 |
| 前端 DOM → 管理 API → SQLite | 8 个业务流程子测试通过，计入父测试共 9 项；SSH 使用模拟夹具 |
| Chromium 桌面/手机流程 | 登录、增删改、连接检查、会话、接入配置、退出及窄屏布局脚本通过；SSH 使用模拟夹具 |
| 浏览器截图 | 已作为 `console-screenshots` 产物上传到该次 CI；未据此宣称生产视觉验收完成 |

Python 3.12 CI 的实际主要依赖：AsyncSSH 2.24.1、MCP SDK 1.30.0、Uvicorn 0.54.0、
Ruff 0.16.10、pip-audit 2.10.1；完整安装日志在对应任务中。
这是一份已运行记录，不是依赖锁文件。后续锁文件和验证结果见上方 PR #5 记录。

## 真实协议测试覆盖

`tests/test_integration.py` 的 10 个场景使用临时密钥、密码、回环 SSH/SFTP、
真实 POSIX 子进程/PTY，以及官方 MCP 客户端，现已在 CI 执行：

- 密码与私钥认证、标准输出/错误、非零退出码。
- 延迟命令、命令超时、持久 PTY 状态和独立会话。
- SFTP UTF-8 边界、二进制分块、文件信息/列表及删除。
- 主机密钥改变后的拒绝行为。
- 大量输出的容量上限、会话容量与空闲回收。
- 底层错误的敏感内容不进入工具返回。
- HTTP MCP 初始化、工具发现、命令/文件操作、认证及非法 Host 拒绝。
- 网页添加的服务器能够被 MCP 立即发现，返回不包含凭据引用。
- stdio MCP 工具发现。

生命周期单元测试另覆盖并发容量预留、连接失败释放、请求取消、输入/EOF、
关闭先于监视任务启动、超时，以及空闲与完成结果回收。
这些单元测试使用模拟传输，不能替代上述真实协议测试。

## 本地检查与 CI 修复记录

早期受限开发环境通过 35 项 Python 测试；由于本地未安装运行依赖，集成模块明确跳过。
本地还通过 DOM 流程、脚本语法、Markdown 本地链接、配置 YAML 和 Git 差异格式检查。
本地无法创建监听 socket 或启动 Chromium，相关真实验证已转移到正常联网的 GitHub 托管运行器。

第一轮 CI 发现测试辅助脚本的函数默认参数触发 Ruff B008，已修复。
第二轮发现 Python 3.10 运行器预装 `setuptools 79.0.1` 被依赖审计标记；
CI 现显式安装修复版本（要求 `>=83.0.0`），第三轮审计通过。未忽略该告警。

## 尚未完成的客户端验收

SSH 权限问题已解决，生产部署和真实协议、控制台检查结果见本文最新记录。
剩余工作是通过已部署公开 HTTPS 入口，使用真实 AI 客户端完成
[对话式验收步骤](clients.md#acceptance-walkthrough)。
该项仍由 [Issue #1](https://github.com/cytlabs/ssh-mcp/issues/1) 跟踪，不能仅依据 SDK 测试关闭。

ChatGPT 所需的 OAuth 接入尚未实现，见 [Issue #2](https://github.com/cytlabs/ssh-mcp/issues/2)。
Bearer 客户端验收通过也不能关闭 OAuth 待办。
源码已提交 GitHub；未发布 PyPI 安装包、正式镜像或 Release。
首次正式发布准备见 [Issue #4](https://github.com/cytlabs/ssh-mcp/issues/4)。

## 2026-10-11：OAuth 与命令返回值

本轮新增原生 OAuth（发现、DCR、S256 PKCE、浏览器同意、刷新轮换与撤销），
中文密码初始化/登录页、HttpOnly Cookie、授权管理和密码重设 CLI。

- Python 后端测试增加到 56 项：原 47 项加 8 项 OAuth 安全流程测试及 1 项 OAuth→MCP→真实回环 SSH 集成测试。
- OAuth 命令集成测试显式轮询最终状态，验证 stdout、stderr、非零退出码以及撤销后拒绝 MCP 请求。
- 原 DOM 24 项、桌面/手机 Chromium 控制台检查通过。
- 新 HTTPS Chromium 流程通过：首次设置、Cookie 刷新保持、显式同意、回调、OAuth Token 换取、MCP 初始化、授权撤销、手机布局、退出和重新登录。
- Ruff、wheel 构建及静态资源校验通过。Python 3.10 的既有退出清理警告仍由 #8 跟踪。
- 升级前公开 HTTPS MCP 实际执行低影响命令，得到 stdout、stderr、退出码 7 和 completed 状态；目标使用普通 SSH 账户。

本轮浏览器使用临时自签名 HTTPS 夹具（仅测试客户端信任该证书）；生产入口仍要求有效可信证书。
协议和浏览器自动化不替代 Codex/ChatGPT 的真实 AI 对话验收。生产首次密码设置应由管理员完成。

新增 `npm run test:oauth-browser` 已在本机通过，尚未接入 GitHub Actions 的 console 作业：当前 GitHub OAuth 凭据没有修改 workflow 的权限。现有 CI 继续运行后端（包含新 OAuth 测试）、原控制台、容器与构建审计。
