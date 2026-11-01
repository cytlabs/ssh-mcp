# Web 管理控制台

Portlane 的控制台位于 `/console`，跟随 Python 服务一起分发，提供概览、服务器管理、操作记录和 MCP 接入。

## 界面

- **概览**：已配置服务器数量、当前服务实例中的活跃 SSH 会话数量、最近保存的管理记录，以及服务器和操作摘要。不把未检测的服务器标为在线。
- **服务器**：按名称、主机地址、备注搜索；按认证方式和最近测试状态过滤；每页 10/20/50 条；查看详情、添加、编辑、删除和 SSH 登录测试。连接状态是当前网页内最近一次手动测试结果，不是定时监控。
- **操作记录**：按关键字、类型、结果、日期查询；后端从 SQLite 最近保留的最多 1,000 条管理记录里分页检索。记录只包含时间、事件、目标与结果，**不保存命令正文、标准输出或凭据**。
- **MCP 接入**：查看 MCP URL、复制客户端配置（静态 Token 模式）或 OAuth 授权接入说明、查看和撤销 OAuth 客户端授权。

顶部主题按钮切换**浅色 / 深色**模式。默认遵循系统设置；用户选择保存在浏览器本地，不影响服务器和客户端。

## 登录与身份

推荐 `http.auth_mode: "oauth"`。首次部署自动生成一次性初始化链接，保存在身份数据库旁 `ssh-mcp.auth.setup-link`，权限 `0600`。使用链接创建管理员用户名及 12–256 字符的密码；链接 1 小时有效且只可使用一次。

成功登录后，浏览器使用 `Secure`、`HttpOnly`、`SameSite=Lax` Cookie 保存最多 8 小时的会话。首次初始化和 OAuth 控制台都要求 HTTPS。未初始化时普通 `/console` 显示明确提示，不能直接注册抢占管理员账号。

若遗失链接，以服务账户运行：

```sh
ssh-mcp setup-link --config /etc/ssh-mcp/config.json --database /var/lib/ssh-mcp/inventory.sqlite3
```

忘记密码时在服务器端重设：

```sh
ssh-mcp set-admin-password --username admin --config /etc/ssh-mcp/config.json --database /var/lib/ssh-mcp/inventory.sqlite3
```

重设密码将撤销浏览器登录和 OAuth 授权，但不会轮换独立静态 MCP Token。旧配置未开启 OAuth 时，仍可使用独立管理员 Token；该模式可选在当前标签页维持登录状态。

## 凭据与连接安全

管理员只填写服务端已有的私钥路径、密码环境变量名称和经过核验的 `known_hosts` 文件。控制台不上传 SSH 密码或私钥正文。SSH 登录测试仅建立并关闭 SSH 连接，不执行远程命令。

OAuth 或静态 MCP 凭据并不能限制每条 SSH 命令。所有获授权客户端共享配置中的服务器权限，请优先使用权限最小化的远程账户。进一步参见 [安全说明](../SECURITY.md)。

## 数据与分页

服务器清单保存在 SQLite 中，最多 128 台。页面上的服务器搜索与分页在已授权取得的服务器清单内进行。

操作记录最多保留最新 1,000 条。为保证查询和页数一致，`GET /admin/activity` 在服务端过滤和分页，支持：

| 参数 | 范围 |
| --- | --- |
| `page` | 从 1 开始 |
| `size` | 10、20 或 50 |
| `search` | 目标或事件关键字，最多 120 字符 |
| `event` | `all` / `server` / `connection` / `session` |
| `outcome` | `all` / `ok` / `failed` |
| `start`、`end` | 可选 ISO 日期 `YYYY-MM-DD` |

该接口仍要求管理员认证，不是可公开查询的日志 API。管理事件包括网页操作以及记录到 SQLite 的连接测试；它不构成 MCP 命令审计。

## 存储与备份

- 清单默认路径：配置文件目录下 `data/ssh-mcp.sqlite3`（也可使用 `--database`）。
- OAuth 身份库在同目录的 `ssh-mcp.auth.sqlite3`；自定义清单路径时使用相应 `<数据库名>.auth.sqlite3`。
- 首次启动从 JSON 导入服务器，之后以 SQLite 为准。界面保存的更改立即影响当前 HTTP/MCP 实例；外部独立 stdio 进程不会自动同步。
- 服务器仍有运行会话时不能删除。会话不在 SQLite 内持久化，服务重启不会恢复它们。
- 停止服务后同时备份清单、身份库、密钥文件和环境配置。恢复备份后按 [安全说明](../SECURITY.md) 考虑撤销历史授权。

## 开发者验证

```sh
npm ci
npm run test:ui
npx playwright install --with-deps chromium
npm run test:browser
PYTHON=.venv/bin/python npm run test:oauth-browser
```

浏览器用例通过独立回环服务和测试 SQLite 运行，SSH 行为为夹具；这些结果不能代替真实服务器验收。完整测试范围见 [验证记录](verification.md)。
