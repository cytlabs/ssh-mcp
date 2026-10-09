"""针对管理员明确授权目标的低影响真实 SSH 检查。

不进入 unittest/CI 自动执行，不记录真实清单、凭据或远程输出。
直接读取 JSON，不打开或修改产品的 SQLite 数据库。
"""

import argparse
import asyncio
import base64
import re
import secrets
import sys
from dataclasses import replace


class CheckFailed(Exception):
    pass


def require(value, label):
    if not value:
        raise CheckFailed(label)


def cleanup_command(directory):
    # Fail closed before constructing any removal command. Never recursively delete.
    if not re.fullmatch(r"/tmp/ssh-mcp-smoke-[0-9a-f]{32}", directory):
        raise ValueError("不是本脚本生成的测试目录")
    return f"rm -f -- {directory}/probe.txt && rmdir -- {directory}"


async def command(manager, server_id, text, expected_exit=0):
    terminal = await manager.start(server_id, text, pty=False, timeout_seconds=10)
    try:
        await asyncio.wait_for(asyncio.shield(terminal.task), 15)
        result = await manager.read(terminal.id)
        require(result["status"] == "completed", "command did not complete")
        require(result["exit_code"] == expected_exit, "unexpected exit code")
        return result
    finally:
        await manager.close(terminal.id)


async def check_files(manager, server_id):
    directory = "/tmp/ssh-mcp-smoke-" + secrets.token_hex(16)
    # mkdir is exclusive: existing paths cause failure before any file access.
    # If the connection drops during mkdir, report the possible residue without
    # claiming ownership or attempting to remove an unconfirmed directory.
    try:
        await command(manager, server_id, f"umask 077; mkdir -- {directory}")
    except BaseException:
        print(f"目录创建状态未确认，请管理员核实： {directory}", file=sys.stderr)
        raise
    try:
        path = directory + "/probe.txt"
        content = "SSH MCP 文件联调\n"
        await manager.file(server_id, "write", path, content, truncate=True)
        result = await manager.file(server_id, "read", path)
        require(result["data"] == content and result["eof"], "text round trip")
        raw = bytes(range(256))
        await manager.file(server_id, "write", path, base64.b64encode(raw).decode(),
                           encoding="base64", truncate=True)
        result = await manager.file(server_id, "read", path, encoding="base64")
        require(base64.b64decode(result["data"]) == raw, "binary round trip")
        await manager.file(server_id, "delete", path)
        result = await manager.file(server_id, "list", directory)
        require(not result["entries"], "file deletion")
    finally:
        try:
            await command(manager, server_id, cleanup_command(directory))
        except BaseException:
            print(f"清理状态未确认，请管理员核实： {directory}", file=sys.stderr)
            raise
    print("通过：SFTP 文本/二进制读写、删除及临时目录清理")


async def run(args):
    from ssh_mcp.config import load_config
    from ssh_mcp.ssh import SSHManager

    config = load_config(args.config)
    server = config.server(args.server)  # Validate before creating any connection.
    manager = SSHManager(replace(config, servers=(server,), connect_timeout=8, file_timeout=15))
    try:
        result = await command(manager, server.id,
                               "printf SSH_MCP_STDOUT; printf SSH_MCP_STDERR >&2; exit 7", 7)
        require(result["stdout"]["text"] == "SSH_MCP_STDOUT", "stdout")
        require(result["stderr"]["text"] == "SSH_MCP_STDERR", "stderr")
        print("通过：SSH 认证、标准输出/错误及非零退出码")

        result = await command(manager, server.id, "sleep 1; printf SSH_MCP_DELAYED")
        require(result["stdout"]["text"] == "SSH_MCP_DELAYED", "delayed output")
        print("通过：短时异步命令及输出保留")

        # Bound the PTY process lifetime; disable shell history for this process.
        terminal = await manager.start(server.id,
                                       "HISTFILE=/dev/null ENV= BASH_ENV= /bin/sh -s",
                                       pty=True, timeout_seconds=20)
        try:
            await manager.send(terminal.id, "cd /tmp\n")
            await manager.send(terminal.id, "printf '__MCP_CWD__%s__\\n' \"$PWD\"\n")

            async def wait_for_state():
                while True:
                    result = await manager.read(terminal.id)
                    # This marker is absent from the echoed input, avoiding a false pass.
                    if "__MCP_CWD__/tmp__" in result["stdout"]["text"]:
                        return
                    require(result["status"] == "running", "PTY exited before state check")
                    await asyncio.sleep(0.05)

            await asyncio.wait_for(wait_for_state(), 10)
            await manager.send(terminal.id, "exit\n")
        finally:
            await manager.close(terminal.id)
        print("通过：PTY 输入、工作目录保留及会话关闭")
        if args.files:
            await check_files(manager, server.id)
        else:
            print("跳过：远程文件写入（需显式指定 --files）")
    finally:
        await manager.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="私人 JSON 配置路径，不读取 SQLite")
    parser.add_argument("--server", required=True, help="管理员已明确授权的一台服务器 ID")
    parser.add_argument("--files", action="store_true",
                        help="在新建的私有 /tmp 目录中创建、验证并清理一个小文件")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("检查已中断，请核对上方可能出现的清理提示。", file=sys.stderr)
        return 130
    except Exception as exc:
        # External exception strings may include credentials or remote output.
        print(f"失败（{type(exc).__name__}），验收尚未完成。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
