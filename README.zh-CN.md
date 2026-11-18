# SSH MCP 中文说明

项目默认首页现已统一使用中文，请阅读 [README](README.md)。

- [部署说明](docs/deployment.md)
- [管理控制台与 SQLite](docs/console.md)
- [MCP 客户端接入](docs/clients.md)
- [工具说明](docs/tools.md)
- [验证记录](docs/verification.md)

保留此文件以兼容已有链接，后续内容统一维护在默认首页。
## SSH 命令审计

设置 `SSH_MCP_COMMAND_AUDIT_DB` 为仅服务账户可写的数据库路径并重启。容器可使用持久卷中的 `/data/commands.sqlite3`。留空关闭本功能。

| 环境变量 | 开启审计库后的默认值 | 用途 |
| --- | --- | --- |
| `SSH_MCP_AUDIT_COMMAND_TEXT` | `1` | 保存发送的命令正文。设为 `0` 仅记录元数据。 |
| `SSH_MCP_AUDIT_SHELL_INPUT` | `0` | 交互输入仅记元数据。设为 `1` 会记录原始输入，可能包含密码和令牌。 |
| `SSH_MCP_AUDIT_RETENTION_DAYS` | 留空 | 设置 1 到 3650 天后，服务启动时及其后每小时清空过期记录的正文。原有记录的操作者、会话、事件和时间继续保留。留空沿用已有正文存储。 |

新建审计文件仅对服务账户开放。历史部署若需保留交互原文，可显式开启交互输入选项。正文清理作用于当前数据库，已有备份和导出文件应按各自保留期限管理。

在网页“命令审计”中查看记录，或在数据库执行以下查询。审计在发送前写入，写入失败会阻止本次发送。命令执行结果通过 `read_output` 获取。

```sql
SELECT timestamp, server_id, session_id, event, content
FROM command_audit ORDER BY id DESC LIMIT 100;
```
