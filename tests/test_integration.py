"""Real SSH/SFTP + HTTP MCP round trips. Never touches an operator's servers."""
# ruff: noqa: E402 -- optional dependencies deliberately checked before imports

import asyncio
import base64
import contextlib
import importlib.util
import json
import os
import secrets
import socket
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

if any(importlib.util.find_spec(name) is None for name in ("asyncssh", "mcp", "uvicorn")):
    if os.environ.get("SSH_MCP_REQUIRE_INTEGRATION") == "1":
        raise RuntimeError("Integration dependencies missing; install the project first")
    raise unittest.SkipTest("Integration requires installed asyncssh, mcp and uvicorn")

import asyncssh
import httpx
import uvicorn
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from ssh_mcp.config import Config, Server
from ssh_mcp.server import create_http_app, create_server
from ssh_mcp.ssh import SSHManager


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.password = secrets.token_urlsafe(32)
        self.host_key = asyncssh.generate_private_key("ssh-ed25519")
        self.client_key = asyncssh.generate_private_key("ssh-ed25519")
        self.client_key.write_private_key(self.root / "identity")
        password, public_key = self.password, self.client_key.convert_to_public()

        class Auth(asyncssh.SSHServer):
            def begin_auth(self, username):
                return True

            def password_auth_supported(self):
                return True

            def public_key_auth_supported(self):
                return True

            def validate_password(self, username, value):
                return username == "tester" and value == password

            def validate_public_key(self, username, key):
                return username == "tester" and key == public_key

        self.children = set()
        self.ssh_server = await asyncssh.create_server(
            Auth, "127.0.0.1", 0, server_host_keys=[self.host_key],
            process_factory=self.run_process,
            sftp_factory=lambda channel: asyncssh.SFTPServer(channel, chroot=str(self.root)),
        )
        port = self.ssh_server.get_port()
        known_hosts = self.root / "known_hosts"
        known_hosts.write_text(f"[127.0.0.1]:{port} " + self.host_key.export_public_key().decode())
        self.env = patch.dict(os.environ, {"TEST_SSH_PASSWORD": self.password,
                                           "SSH_MCP_TOKEN": secrets.token_urlsafe(48),
                                           "SSH_MCP_ADMIN_TOKEN": secrets.token_urlsafe(48)})
        self.env.start()
        common = {"host": "127.0.0.1", "username": "tester", "port": port,
                  "known_hosts": known_hosts}
        self.config = Config(servers=(
            Server(id="password", password_env="TEST_SSH_PASSWORD", **common),
            Server(id="key", private_key=self.root / "identity", **common),
        ), buffer_chars=4096)
        self.manager = SSHManager(self.config)

    async def asyncTearDown(self):
        await self.manager.shutdown()
        self.ssh_server.close()
        await self.ssh_server.wait_closed()
        for child in self.children:
            if child.returncode is None:
                child.kill()
            await child.wait()
        self.env.stop()
        self.temp.cleanup()

    async def run_process(self, remote):
        # Real local subprocesses behind a real encrypted SSH transport.
        master = slave = None
        if remote.term_type:
            import pty
            master, slave = pty.openpty()
            os.set_blocking(master, False)
            local = await asyncio.create_subprocess_exec(
                "/bin/sh", "-i", stdin=slave, stdout=slave, stderr=slave,
                cwd=self.root, start_new_session=True,
            )
            os.close(slave)
        else:
            local = await asyncio.create_subprocess_exec(
                "/bin/sh", "-c", remote.command or "/bin/sh",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=self.root,
            )
        self.children.add(local)

        async def to_remote(reader, writer):
            while chunk := await reader.read(4096):
                writer.write(chunk.decode("utf-8", errors="replace"))

        async def from_remote():
            try:
                while data := await remote.stdin.read(4096):
                    if master is not None:
                        os.write(master, data.encode())
                    else:
                        local.stdin.write(data.encode())
                        await local.stdin.drain()
            except asyncssh.SignalReceived:
                if local.returncode is None:
                    local.terminate()
            finally:
                if master is None:
                    local.stdin.close()

        async def from_pty():
            loop = asyncio.get_running_loop()
            while True:
                ready = loop.create_future()

                def readable(event=ready):
                    if not event.done():
                        event.set_result(None)

                loop.add_reader(master, readable)
                try:
                    await ready
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        return
                    if not chunk:
                        return
                    remote.stdout.write(chunk.decode("utf-8", errors="replace"))
                finally:
                    loop.remove_reader(master)

        tasks = [asyncio.create_task(from_remote())]
        tasks.extend([asyncio.create_task(from_pty())] if master is not None else [
            asyncio.create_task(to_remote(local.stdout, remote.stdout)),
            asyncio.create_task(to_remote(local.stderr, remote.stderr)),
        ])
        try:
            await local.wait()
            await asyncio.gather(*tasks[1:])
            remote.exit(local.returncode)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if local.returncode is None:
                local.kill()
                await local.wait()
            if master is not None:
                os.close(master)

    async def wait_done(self, terminal):
        await asyncio.wait_for(asyncio.shield(terminal.task), 10)
        return await self.manager.read(terminal.id)

    async def test_exec_password_and_key_stdout_stderr_exit(self):
        for server_id in ("password", "key"):
            terminal = await self.manager.start(server_id, "printf hello; printf error >&2; exit 7",
                                                pty=False)
            result = await self.wait_done(terminal)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["stdout"]["text"], "hello")
            self.assertEqual(result["stderr"]["text"], "error")
            self.assertEqual(result["exit_code"], 7)

    async def test_long_command_and_timeout(self):
        terminal = await self.manager.start("key", "sleep 1; echo finished", pty=False)
        self.assertEqual((await self.manager.read(terminal.id))["status"], "running")
        self.assertIn("finished", (await self.wait_done(terminal))["stdout"]["text"])
        timeout = await self.manager.start("key", "sleep 2", pty=False, timeout_seconds=1)
        self.assertEqual((await self.wait_done(timeout))["status"], "timed_out")

    async def test_persistent_pty_and_independent_sessions(self):
        first = await self.manager.start("password")
        second = await self.manager.start("key")
        await self.manager.send(first.id, "cd /tmp; export SSH_MCP_TEST=kept\n")
        await self.manager.send(first.id, "printf '__STATE_%s_%s__\\n' \"$PWD\" \"$SSH_MCP_TEST\"\n")
        await self.manager.send(second.id, "printf '__OTHER_%s__\\n' \"${SSH_MCP_TEST-empty}\"\n")
        for terminal, expected in ((first, "__STATE_/tmp_kept__"), (second, "__OTHER_empty__")):
            async def read_until(target=terminal, marker=expected):
                while marker not in (await self.manager.read(target.id))["stdout"]["text"]:
                    await asyncio.sleep(0.05)
            await asyncio.wait_for(read_until(), 5)
        await self.manager.close(first.id)
        self.assertEqual((await self.manager.close(first.id))["status"], "already_closed")

    async def test_sftp_text_binary_chunks_and_delete(self):
        content = "你好" * 100
        await self.manager.file("key", "write", "/text.txt", content, truncate=True)
        result = await self.manager.file("key", "read", "/text.txt", length=7)
        self.assertEqual(result["data"], "你好")
        self.assertEqual(result["next_offset"], 6)
        self.assertFalse(result["eof"])
        raw = bytes(range(256)) * 10
        for offset in range(0, len(raw), 256):
            await self.manager.file("password", "write", "/binary.bin",
                                    base64.b64encode(raw[offset:offset + 256]).decode(),
                                    "base64", offset, truncate=(offset == 0))
        downloaded, offset = b"", 0
        while True:
            chunk = await self.manager.file("key", "read", "/binary.bin", encoding="base64",
                                            offset=offset, length=500)
            downloaded += base64.b64decode(chunk["data"])
            offset = chunk["next_offset"]
            if chunk["eof"]:
                break
        self.assertEqual(downloaded, raw)
        self.assertEqual((await self.manager.file("key", "stat", "/binary.bin"))["size"], len(raw))
        self.assertIn("binary.bin", [e["name"] for e in
                                    (await self.manager.file("key", "list", "/"))["entries"]])
        await self.manager.file("key", "delete", "/binary.bin")
        with self.assertRaises(asyncssh.SFTPNoSuchFile):
            await self.manager.file("key", "read", "/binary.bin")

    async def test_host_key_mismatch_fails_closed(self):
        bad = self.root / "bad_hosts"
        bad.write_text("[127.0.0.1]:" + str(self.ssh_server.get_port()) + " " +
                       asyncssh.generate_private_key("ssh-ed25519").export_public_key().decode())
        server = replace(self.config.servers[0], known_hosts=bad)
        with self.assertRaises(asyncssh.HostKeyNotVerifiable):
            await self.manager.connect(server)

    async def test_output_flood_bounded_and_session_limit(self):
        terminal = await self.manager.start("key", "head -c 20000 /dev/zero | tr '\\0' x", pty=False)
        result = await self.wait_done(terminal)
        self.assertLessEqual(len(result["stdout"]["text"]), 4096)
        self.assertGreater(result["stdout"]["dropped_chars"], 0)
        self.manager.config = replace(self.config, max_sessions=1)
        with self.assertRaises(ValueError):
            await self.manager.start("key")

    async def test_idle_reaper(self):
        self.manager.config = replace(self.config, idle_timeout=1)
        terminal = await self.manager.start("key")
        reaper = asyncio.create_task(self.manager.reap())
        try:
            await asyncio.sleep(2.2)
            self.assertNotIn(terminal.id, self.manager.terminals)
        finally:
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper

    async def test_mcp_errors_are_sanitized(self):
        mcp, manager = create_server(self.config)
        try:
            # Library ValueError messages must never be returned as configuration details.
            from unittest.mock import AsyncMock
            with patch.object(manager, "start", AsyncMock(side_effect=ValueError(self.password))):
                with self.assertRaises(Exception) as raised:
                    await mcp.call_tool("execute_command", {"server_id": "key", "command": "true"})
                self.assertNotIn(self.password, str(raised.exception))
        finally:
            await manager.shutdown()

    async def test_http_mcp_end_to_end(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        app = create_http_app(self.config)
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="on"))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        url = f"http://127.0.0.1:{port}/mcp"
        try:
            async def ready():
                while not server.started:
                    if task.done():
                        await task
                    await asyncio.sleep(0.02)
            await asyncio.wait_for(ready(), 10)
            async with httpx.AsyncClient(trust_env=False) as http:
                self.assertEqual((await http.post(url, json={})).status_code, 401)
                headers = {"Authorization": "Bearer " + os.environ["SSH_MCP_TOKEN"]}
                admin_headers = {"Authorization": "Bearer " + os.environ["SSH_MCP_ADMIN_TOKEN"]}
                admin_url = f"http://127.0.0.1:{port}/admin"
                self.assertEqual((await http.get(admin_url + "/state", headers=headers)).status_code, 401)
                snapshot = (await http.get(admin_url + "/state", headers=admin_headers)).json()
                extra = {**snapshot["servers"][0], "id": "from-console"}
                saved = await http.post(admin_url + "/servers", headers=admin_headers,
                                        json={"revision": snapshot["revision"], "server": extra})
                self.assertEqual(saved.status_code, 200)
                self.assertEqual((await http.post(url, headers={**headers, "Host": "evil.invalid"},
                                                  json={})).status_code, 421)
                # Official MCP client performs initialize, discovery and tools/call over HTTP.
                def factory(headers=None, timeout=None, auth=None):
                    return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth, trust_env=False)
                async with streamablehttp_client(url, headers=headers, httpx_client_factory=factory) as streams:
                    async with ClientSession(streams[0], streams[1]) as client:
                        await client.initialize()
                        names = {tool.name for tool in (await client.list_tools()).tools}
                        self.assertIn("transfer_file", names)
                        listed = await client.call_tool("list_servers", {})
                        self.assertNotIn(self.password, listed.model_dump_json())
                        self.assertIn("from-console", listed.model_dump_json())
                        self.assertNotIn("private_key", listed.model_dump_json())
                        self.assertNotIn("password_env", listed.model_dump_json())
                        result = await client.call_tool("execute_command", {
                            "server_id": "key", "command": "printf mcp-ok", "wait_seconds": 1,
                        })
                        self.assertFalse(result.isError)
                        body = json.loads(result.content[0].text)
                        sid = body["session_id"]
                        for _ in range(10):
                            if body["status"] != "running":
                                break
                            result = await client.call_tool("read_output", {"session_id": sid,
                                                                            "wait_seconds": 1})
                            body = json.loads(result.content[0].text)
                        self.assertEqual(body["stdout"]["text"], "mcp-ok")
                        self.assertEqual(body["exit_code"], 0)
                        written = await client.call_tool("write_file", {
                            "server_id": "key", "path": "/mcp.txt", "data": "from-mcp", "truncate": True,
                        })
                        self.assertFalse(written.isError)
                        read = await client.call_tool("read_file", {"server_id": "key", "path": "/mcp.txt"})
                        self.assertIn("from-mcp", read.content[0].text)
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 10)
            sock.close()

    async def test_stdio_mcp_discovery(self):
        import sys
        config_path = self.root / "stdio.json"
        config_path.write_text(json.dumps({"servers": []}))
        params = StdioServerParameters(command=sys.executable, args=["-m", "ssh_mcp", "serve",
                                     "--transport", "stdio", "--config", str(config_path)],
                                     env={"PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                self.assertIn("execute_command", {t.name for t in (await client.list_tools()).tools})
