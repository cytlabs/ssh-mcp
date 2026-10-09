"""Opt-in checks of the production SSH implementation against an operator's target.

Not collected by unittest/CI. No inventory, credentials or remote output is logged.
Uses JSON inventory directly, without opening or changing the product's SQLite DB.
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
        raise ValueError("Not a smoke-test directory")
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
        print(f"Directory creation unconfirmed; operator may inspect: {directory}", file=sys.stderr)
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
            print(f"Cleanup unconfirmed; operator may inspect: {directory}", file=sys.stderr)
            raise
    print("PASS SFTP text/binary read, write, delete and temporary-directory cleanup")


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
        print("PASS SSH authentication, stdout, stderr and nonzero exit code")

        result = await command(manager, server.id, "sleep 1; printf SSH_MCP_DELAYED")
        require(result["stdout"]["text"] == "SSH_MCP_DELAYED", "delayed output")
        print("PASS short asynchronous command and retained output")

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
        print("PASS PTY input, retained working directory and session closure")
        if args.files:
            await check_files(manager, server.id)
        else:
            print("SKIP file writes (enable explicitly with --files)")
    finally:
        await manager.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Private JSON inventory (not SQLite)")
    parser.add_argument("--server", required=True, help="One explicitly authorized server ID")
    parser.add_argument("--files", action="store_true",
                        help="Create, verify and remove one small file in a new private /tmp directory")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("Interrupted; review any cleanup notice above.", file=sys.stderr)
        return 130
    except Exception as exc:
        # External exception strings may include credentials or remote output.
        print(f"FAIL ({type(exc).__name__}); acceptance incomplete.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
