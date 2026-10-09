# MCP 客户端接入

以下示例使用 `https://ssh-mcp.example.com/mcp`，请替换为实际部署入口。
MCP Token 保存到客户端的环境变量或秘密配置中，不放进对话。
客户端不需要 SSH 密码或私钥，但 MCP Token 本身拥有操作所有已配置目标的权限，应妥善保管。

这些是根据供应商文档核对的配置示例，不代表已经完成各客户端的最终用户验收。
可用性也受客户端版本和组织策略影响，实际完成范围见 [验证记录](verification.md)。

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

## ChatGPT：OAuth 接入尚待实现

已核对的 ChatGPT 自定义 MCP 配置提供 OAuth 相关或无认证模式；
OAuth 客户端凭据与服务自己的 Bearer API Token 并不是同一种凭据。
SSH MCP `0.1.0a1` 尚未实现 OAuth 授权服务器或交互式授权同意流程。
不要为了接入而选择无认证模式。
参考：[OpenAI 自定义 MCP 服务说明](https://developers.openai.com/api/docs/guides/custom-mcp-server)。

后续网关需提供 OAuth 发现、授权码与 PKCE、重定向 URI 校验、授权同意、
面向指定服务的访问 Token 及撤销能力。内部 Bearer Token 应只保留在网关服务端，
同时禁止客户端绕过网关访问后端。目前仓库没有提供或宣称测试过这样的网关。
该项在 [路线图](../ROADMAP.md) 中以 `MCP-002` 跟踪。

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
