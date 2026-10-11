"""通过已授权的公开 HTTPS MCP 入口进行低影响联调；不输出凭据或远程正文。"""

import argparse
import asyncio
import base64
import json
import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from smoke_ssh import CheckFailed, cleanup_command, require


def validate_url(value):
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path != "/mcp"):
        raise ValueError("URL 必须是无凭据、查询参数和片段的 HTTPS /mcp 地址")
    # Accessing port also rejects malformed authorities.
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError("无效端口")
    return value


@asynccontextmanager
async def connect(url, token):
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"},
                                 timeout=httpx.Timeout(60, connect=15)) as client:
        async with streamable_http_client(url, http_client=client) as streams:
            async with ClientSession(streams[0], streams[1]) as session:
                await session.initialize()
                yield session


async def call(session, name, **arguments):
    result = await session.call_tool(name, arguments)
    require(not result.isError, f"工具失败：{name}")
    if result.structuredContent is not None:
        return result.structuredContent
    return json.loads(next(item.text for item in result.content if item.type == "text"))


async def command(session, server, text, expected_exit=0, timeout=15):
    result = await call(session, "execute_command", server_id=server, command=text,
                        timeout_seconds=timeout, wait_seconds=1)
    sid = result["session_id"]
    try:
        while result["status"] == "running":
            result = await call(session, "read_output", session_id=sid, wait_seconds=2)
        require(result["status"] == "completed", "命令未完成")
        require(result["exit_code"] == expected_exit, "退出码不符")
        return result
    finally:
        await call(session, "close_session", session_id=sid)


async def files(session, server):
    directory = "/tmp/ssh-mcp-smoke-" + secrets.token_hex(16)
    try:
        await command(session, server, f"umask 077; mkdir -- {directory}")
    except BaseException:
        print(f"目录创建状态未确认，请核实：{directory}", file=sys.stderr)
        raise
    try:
        path = directory + "/probe.txt"
        content = "SSH MCP 中文文件联调\n"
        await call(session, "write_file", server_id=server, path=path, data=content, truncate=True)
        result = await call(session, "read_file", server_id=server, path=path)
        require(result["data"] == content, "中文文件读回不符")
        content = "修改完成\n"
        await call(session, "write_file", server_id=server, path=path, data=content, truncate=True)
        await command(session, server, f"test $(wc -l < {path}) -eq 1 && test $(wc -c < {path}) -eq 13")
        raw = bytes(range(256))
        await call(session, "transfer_file", server_id=server, direction="upload", remote_path=path,
                   data_base64=base64.b64encode(raw).decode(), truncate=True)
        result = await call(session, "transfer_file", server_id=server, direction="download",
                            remote_path=path)
        require(base64.b64decode(result["data"]) == raw, "二进制传输不符")
        await call(session, "delete_file", server_id=server, path=path)
        result = await call(session, "list_files", server_id=server, path=directory)
        require(not result["entries"], "文件未删除")
    finally:
        try:
            await command(session, server, cleanup_command(directory))
        except BaseException:
            print(f"清理状态未确认，请核实：{directory}", file=sys.stderr)
            raise
    print("通过：中文文件创建/修改、Shell 校验、二进制上传下载与清理")


async def run(args):
    import httpx

    token = os.environ.get(args.token_env, "")
    require(len(token) >= 32, "缺少有效 MCP Token 环境变量")
    async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
        for headers in ({}, {"Authorization": "Bearer invalid"}):
            response = await client.post(args.url, json={}, headers=headers)
            require(response.status_code == 401, "匿名或错误 Token 未被拒绝")
    print("通过：公开 HTTPS 信任链、匿名及错误 Token 拒绝")
    async with connect(args.url, token) as session:
        result = await call(session, "list_servers")
        require(any(s["id"] == args.server for s in result["servers"]), "目标不在清单中")
        allowed = {"id", "host", "port", "username", "description"}
        require(all(set(s) <= allowed for s in result["servers"]), "清单包含非公开字段")
        result = await command(session, args.server, "printf out; printf err >&2; exit 7", 7)
        require(result["stdout"]["text"] == "out" and result["stderr"]["text"] == "err", "输出不符")
        print("通过：MCP 初始化、服务器清单、标准输出/错误与非零退出码")
        terminal = await call(session, "create_session", server_id=args.server, pty=True)
        sid = terminal["session_id"]
        try:
            await call(session, "send_input", session_id=sid, data="unset HISTFILE; cd /tmp\n")
            await call(session, "send_input", session_id=sid, data="printf '__MCP_CWD__%s__\\n' \"$PWD\"\n")
            for _ in range(30):
                result = await call(session, "read_output", session_id=sid, wait_seconds=1)
                if "__MCP_CWD__/tmp__" in result["stdout"]["text"]:
                    break
            else:
                raise CheckFailed("PTY 工作目录未保留")
        finally:
            await call(session, "close_session", session_id=sid)
        print("通过：持久 PTY、连续输入、工作目录保留与关闭")
        if args.files:
            await files(session, args.server)
        result = await call(session, "execute_command", server_id=args.server,
                            command="sleep 30; printf MCP_DELAYED", timeout_seconds=45, wait_seconds=0)
        sid = result["session_id"]
        # Reconnect while a command outlives the maximum 25-second tool wait.
        try:
            async with connect(args.url, token) as other:
                listing = await call(other, "list_sessions")
                require(any(s["session_id"] == sid for s in listing["sessions"]), "无法找回会话")
                while result["status"] == "running":
                    result = await call(other, "read_output", session_id=sid, wait_seconds=5)
                require(result["exit_code"] == 0 and result["stdout"]["text"] == "MCP_DELAYED",
                        "异步命令失败")
        finally:
            await call(session, "close_session", session_id=sid)
        print("通过：超过单次等待上限的异步命令、重新连接与会话找回")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, type=validate_url)
    parser.add_argument("--server", required=True, help="明确授权的目标 ID")
    parser.add_argument("--token-env", default="SSH_MCP_TOKEN")
    parser.add_argument("--files", action="store_true", help="在新建临时目录中写入、校验并清理文件")
    args = parser.parse_args()
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(asyncio.wait_for(run(args), timeout=150))
    except KeyboardInterrupt:
        print("检查已中断，请检查临时目录和会话。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"失败（{type(exc).__name__}），验收尚未完成；请检查临时目录和会话。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
