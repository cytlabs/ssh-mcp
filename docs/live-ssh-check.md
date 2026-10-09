# 低影响真实 SSH 联调

仅用于管理员明确授权的服务器。此脚本独立于临时回环集成测试，不进入 CI 或 unittest 自动发现。
优先选择测试服务器；已有业务的生产目标必须在操作者授权范围内执行。

## 准备与执行

在 **MCP 主机**安装项目依赖，按 [部署说明](deployment.md) 准备私人 JSON 配置。
脚本直接读取该 JSON，不读取或修改控制台 SQLite 清单。
明确指定 SSH 身份和已经核验的 `known_hosts`。
本机 `ssh` 能连接可能依赖 SSH Agent 或用户配置，而本产品要求显式配置凭据，不隐式继承二者。
不要关闭主机密钥校验，也不要把密钥、密码和真实服务器清单放进 Git。

在仓库根目录执行：

```sh
PYTHONPATH=src python3 scripts/smoke_ssh.py --config config.json --server staging
# 已授权文件操作时，增加以下选项：
PYTHONPATH=src python3 scripts/smoke_ssh.py --config config.json --server staging --files
```

默认检查认证、标准输出/错误、退出码 7、一秒延迟命令、PTY 输入及工作目录保留。
只创建测试 Shell 进程，并修改该 Shell 的工作目录。
目标需要 POSIX Shell 及常规的 `sleep`、`mkdir`、`rm`、`rmdir` 命令；文件检查还需要 SFTP。
脚本不在远程安装软件。

## 文件操作与清理范围

`--files` 排他创建随机目录 `/tmp/ssh-mcp-smoke-<32 位十六进制字符>`，权限为 `0700`。
随后写入、读取一个小型文本/二进制测试文件，删除该文件并移除空目录。
目录确认创建成功后，清理逻辑放在 `finally` 中，使用精确文件名和 `rmdir`，
不用通配符或递归删除，并拒绝不符合完整命名规则的清理路径。

断网或进程被强制终止可能留下临时目录；脚本会在能够检测到时报告路径，人工清理前应核实。
不会读取应用文件、查询环境变量、重启服务、修改系统配置或执行压力测试。
SSH 登录审计以及管理员配置的 Shell 启动脚本仍会正常触发。

## 结果含义

输出只包含检查标签、异常类型及可能的临时目录清理提示，不包含凭据或远程命令完整输出。
非零退出码表示验收尚未完成。运行环境必须允许 SSH 出站连接。
本地立即出现 `socket: Operation not permitted` 代表当前执行环境限制，不能据此判断远程服务器故障。

此脚本验证项目实际 SSH/SFTP 实现，不验证 MCP HTTP、HTTPS、OAuth 或 AI 客户端行为。
这些仍需通过 [真实客户端验收](clients.md#acceptance-walkthrough) 完成。
实际结果记入 [验证记录](verification.md)，私人目标信息不要写入公开仓库。
