# SSH MCP 中文说明

项目默认首页现已统一使用中文，请阅读 [README](README.md)。

- [部署说明](docs/deployment.md)
- [管理控制台与 SQLite](docs/console.md)
- [MCP 客户端接入](docs/clients.md)
- [工具说明](docs/tools.md)
- [验证记录](docs/verification.md)

保留此文件以兼容已有链接，后续内容统一维护在默认首页。
## SSH 命令审计

在服务环境中设置 `SSH_MCP_COMMAND_AUDIT_DB=/var/lib/ssh-mcp/commands.sqlite3` 并重启服务即可启用。目录须已存在且仅允许服务账号和授权管理员访问。容器部署请将目录挂载到持久卷。未设置时沿用现有日志行为。

在审计库中运行以下查询，可按时间查看目标服务器、会话和命令。

```sql
SELECT timestamp, server_id, session_id, event, content
FROM command_audit ORDER BY id DESC LIMIT 100;
```

时间使用 UTC。`command` 保存发送给 SSH 的命令，`shell_input` 按会话保存交互输入片段，可能包含密码和控制字符。审计在发送前写入，写入失败会阻止本次发送。记录表示发送尝试，远端执行结果仍通过 `read_output` 查看。
