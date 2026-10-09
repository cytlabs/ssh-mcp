# 验证记录

日期：2026-10-09。版本：`0.1.0a1`（开发预览，未发布正式版本）。

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

当前受限开发环境已通过 35 项 Python 测试；由于本地未安装运行依赖，集成模块明确跳过。
本地还通过 DOM 流程、脚本语法、Markdown 本地链接、配置 YAML 和 Git 差异格式检查。
本地无法创建监听 socket 或启动 Chromium，相关真实验证已转移到正常联网的 GitHub 托管运行器。

第一轮 CI 发现测试辅助脚本的函数默认参数触发 Ruff B008，已修复。
第二轮发现 Python 3.10 运行器预装 `setuptools 79.0.1` 被依赖审计标记；
CI 现显式安装修复版本（要求 `>=83.0.0`），第三轮审计通过。未忽略该告警。

## 尚未完成的生产验收

已尝试连接操作者授权的生产目标，但本地 socket 创建立即返回 `Operation not permitted`，
沙箱外执行申请也被会话策略拒绝。连接没有建立，未执行远程命令或修改服务器。
[低影响 SSH 联调脚本](live-ssh-check.md) 已准备，其清理范围单元测试已通过，但未在真实生产目标运行。

没有部署公开云端入口，也没有完成真实 AI 客户端验收。需要经部署后的 HTTPS 入口执行
[客户端验收步骤](clients.md#acceptance-walkthrough)，记录版本、结果和限制，不提交凭据或私人输出。
该项由 [Issue #1](https://github.com/cytlabs/ssh-mcp/issues/1) 跟踪。

ChatGPT 所需的 OAuth 接入尚未实现，见 [Issue #2](https://github.com/cytlabs/ssh-mcp/issues/2)。
Bearer 客户端验收通过也不能关闭 OAuth 待办。
源码已提交 GitHub；未发布 PyPI 安装包、正式镜像或 Release。
首次正式发布准备见 [Issue #4](https://github.com/cytlabs/ssh-mcp/issues/4)。
