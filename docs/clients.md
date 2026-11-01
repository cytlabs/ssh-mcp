# MCP 客户端接入

以下示例使用 `https://ssh-mcp.example.com/mcp`，请替换为实际部署入口。
推荐 `http.auth_mode: "oauth"`：管理员先在 HTTPS 控制台设置密码，AI 客户端添加 MCP URL，
打开浏览器登录并确认授权。客户端自动保存访问及刷新凭据；无需复制服务器 Token。
OAuth 授权最长 30 天，可在控制台「MCP 接入」撤销。权限覆盖所有已配置目标。

这些配置示例不代表已经完成各客户端的最终用户验收。可用性也受客户端版本和组织策略影响，
实际完成范围见 [验证记录](verification.md)。

## Codex：浏览器授权（推荐）

```sh
codex mcp add ssh_mcp --url https://ssh-mcp.example.com/mcp
codex mcp login ssh_mcp
```

如果同名条目已配置固定请求头或 `bearer_token_env_var`，先移除该认证设置，再运行登录命令。
无本机浏览器时，可使用 `codex mcp login ssh_mcp --no-browser`，按 CLI 提示完成授权回调。
完成后重新加载 MCP 工具，让 AI「查看可用服务器」。参考 [Codex MCP 文档](https://learn.chatgpt.com/docs/extend/mcp)。

## ChatGPT、Cursor、Claude 的 OAuth 接入

在支持远程 MCP 和 OAuth 的客户端设置中添加公开 HTTPS `/mcp` URL，选择 OAuth，
跟随发现端点完成注册、登录和授权。回调地址由客户端提供，无需把 SSH 私钥或管理员密码交给 AI。
如果客户端要求手动 client_id/secret，而不能使用动态注册，该流程尚需专门验证，不要填入静态 MCP Token 冒充 OAuth 客户端密钥。

服务支持动态注册和公共/机密客户端，不实现客户端 ID 元数据文档（CIMD）。
Codex 可在需要时使用 `--oauth-client-registration DCR`；不宣称所有客户端都支持相同发现方式。
参考 [MCP 授权规范](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)、
[OpenAI 自定义 MCP 服务说明](https://developers.openai.com/api/docs/guides/custom-mcp-server)。

## 静态 Token 兼容模式

以下示例仅用于固定 Token 自动化或旧客户端。设置服务端 `SSH_MCP_TOKEN` 才会开启该兼容入口；
在 OAuth 模式下该环境变量可留空。凭据不能放进对话，管理员 Token 不能用于 MCP。

## Codex：远程 HTTP

在 Codex 配置中设置 URL，并从环境变量读取 Bearer Token：

```toml
[mcp_servers.ssh]
url = "https://ssh-mcp.example.com/mcp"
bearer_token_env_var = "SSH_MCP_TOKEN"
startup_timeout_sec = 20
tool_timeout_sec = 90
```

通过环境或秘密存储向 Codex 进程提供 `SSH_MCP_TOKEN`，重启或重新加载客户端，
确认工具列表包含 `list_servers`。
参考：[OpenAI 官方 MCP 配置](https://developers.openai.com/codex/mcp)。

## Claude Code：远程 HTTP

在 `.mcp.json` 添加 HTTP 项，Token 引用由客户端展开：

```json
{
  "mcpServers": {
    "ssh": {
      "type": "http",
      "url": "https://ssh-mcp.example.com/mcp",
      "headers": {"Authorization": "Bearer ${SSH_MCP_TOKEN}"}
    }
  }
}
```

启动 Claude Code 前加载环境变量，然后用 `/mcp` 检查。
此示例专用于 Claude Code，不代表 Claude Desktop 或 claude.ai 具有相同配置入口。
参考：[Claude Code MCP 及环境变量展开](https://code.claude.com/docs/en/mcp)。

## Cursor：远程 HTTP

在用户 MCP 配置 `~/.cursor/mcp.json` 中添加以下内容，使用 Cursor 的环境变量插值：

```json
{
  "mcpServers": {
    "ssh": {
      "url": "https://ssh-mcp.example.com/mcp",
      "headers": {"Authorization": "Bearer ${env:SSH_MCP_TOKEN}"}
    }
  }
}
```

确认 Cursor 进程获得该环境变量，再检查 MCP 工具列表。
从图形界面启动的应用可能与终端具有不同环境。
参考：[Cursor MCP 配置](https://cursor.com/docs/mcp)。

## 本地 stdio：由客户端启动服务进程

使用可执行文件和配置文件的绝对路径：

```json
{
  "mcpServers": {
    "ssh": {
      "command": "/opt/ssh-mcp/.venv/bin/ssh-mcp",
      "args": ["serve", "--transport", "stdio", "--config", "/etc/ssh-mcp/config.json"]
    }
  }
}
```

此模式的服务进程在本机运行，凭据由其环境和本地文件提供。
标准输出专用于 MCP 协议，日志写标准错误。没有本地进程环境的 AI 客户端应使用远程 HTTP。

<a id="acceptance-walkthrough"></a>

## 真实客户端验收步骤

优先使用管理员配置的临时目标。客户端连接后依次验证：

1. 要求“查看可用服务器”，确认别名正确且没有返回登录凭据。
2. 要求测试服务器执行 `printf hello; printf error >&2; exit 7`，检查两个输出流和退出码；必要时轮询。
3. 创建持久终端，先切换目录，再用下一次输入执行 `pwd`，确认状态保留。
4. 在独立临时目录创建文本文件，读回、修改，并运行针对该文件的测试。
5. 执行超过单次 MCP 请求时长的命令，重新连接客户端，用 `list_sessions` 找回会话并按游标读取。
6. 关闭会话、清理临时文件，只保存经过脱敏的验证结果。

这些操作必须通过真实公开 HTTPS 入口完成。SDK 集成测试不能替代实际客户端流程。
