"""Deterministic process-lifecycle tests; these do not assert SSH interoperability."""

import asyncio
import contextlib
import importlib.util
import sys
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from ssh_mcp.config import Config, Server

# Load the production manager under a separate name, stubbing only the external
# transport module. Real SSH/MCP interoperability lives in test_integration.py.
spec = importlib.util.spec_from_file_location(
    "ssh_mcp._lifecycle_under_test",
    Path(__file__).resolve().parents[1] / "src/ssh_mcp/ssh.py",
)
manager_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = manager_module
with patch.dict(sys.modules, {"asyncssh": types.SimpleNamespace(Error=OSError)}):
    spec.loader.exec_module(manager_module)
SSHManager = manager_module.SSHManager


class Reader:
    def __init__(self):
        self.queue = asyncio.Queue()

    async def read(self, size):
        return await self.queue.get()


class Input:
    def __init__(self):
        self.text = ""
        self.eof = False

    def write(self, data):
        self.text += data

    async def drain(self):
        await asyncio.sleep(0)

    def write_eof(self):
        self.eof = True


class Process:
    def __init__(self):
        self.stdout, self.stderr, self.stdin = Reader(), Reader(), Input()
        self.done = asyncio.Event()
        self.exit_status = None
        self.exit_signal = None
        self.closed = False
        self.killed = False

    async def wait_closed(self):
        await self.done.wait()

    def finish(self, code=0):
        self.exit_status = code
        self.stdout.queue.put_nowait("")
        self.stderr.queue.put_nowait("")
        self.done.set()

    def kill(self):
        self.killed = True
        self.close()

    def terminate(self):
        self.close()

    def close(self):
        self.closed = True
        self.done.set()


class Connection:
    def __init__(self):
        self.process = Process()
        self.closed = False

    async def create_process(self, *args, **kwargs):
        return self.process

    def close(self):
        self.closed = True
        self.process.close()

    async def wait_closed(self):
        pass


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = Config(servers=(Server(id="test", host="unused", username="test",
                                           known_hosts=Path("unused"), password_env="UNUSED"),),
                             buffer_chars=1024)
        self.manager = SSHManager(self.config)
        self.connection = Connection()
        self.manager.connect = AsyncMock(return_value=self.connection)

    async def asyncTearDown(self):
        await self.manager.shutdown()

    async def test_stream_completion_replay_and_exit(self):
        terminal = await self.manager.start("test", "fake-command", pty=False)
        self.connection.process.stdout.queue.put_nowait("hello")
        self.connection.process.stderr.queue.put_nowait("problem")
        self.connection.process.finish(9)
        await terminal.task
        result = await self.manager.read(terminal.id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["exit_code"], 9)
        self.assertEqual(result["stdout"]["text"], "hello")
        self.assertEqual(result["stderr"]["text"], "problem")
        self.assertEqual((await self.manager.read(terminal.id, 5, 7))["stdout"]["text"], "")
        self.assertTrue(self.connection.closed)

    async def test_poll_cancellation_does_not_kill_process(self):
        terminal = await self.manager.start("test", "fake-command", pty=False)
        poll = asyncio.create_task(self.manager.read(terminal.id, wait_seconds=25))
        await asyncio.sleep(0)
        poll.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await poll
        self.assertEqual(terminal.status, "running")
        self.assertFalse(self.connection.closed)
        self.connection.process.finish()
        await terminal.task

    async def test_close_before_monitor_first_runs_releases_connection(self):
        terminal = await self.manager.start("test")
        await self.manager.close(terminal.id)
        self.assertTrue(self.connection.closed)
        self.assertNotIn(terminal.id, self.manager.terminals)
        self.assertEqual((await self.manager.close(terminal.id))["status"], "already_closed")

    async def test_timeout_kills_and_retains_result(self):
        terminal = await self.manager.start("test", "fake-command", timeout_seconds=1)
        await terminal.task
        self.assertTrue(self.connection.process.killed)
        self.assertTrue(self.connection.closed)
        self.assertEqual((await self.manager.read(terminal.id))["status"], "timed_out")

    async def test_send_and_eof(self):
        terminal = await self.manager.start("test")
        result = await self.manager.send(terminal.id, "echo ok\n", eof=True)
        self.assertEqual(result["accepted_chars"], 8)
        self.assertEqual(self.connection.process.stdin.text, "echo ok\n")
        self.assertTrue(self.connection.process.stdin.eof)

    async def test_concurrent_pending_connections_reserve_capacity(self):
        self.manager.config = replace(self.config, max_sessions=1)
        entered, release = asyncio.Event(), asyncio.Event()

        async def connect(_):
            entered.set()
            await release.wait()
            return self.connection

        self.manager.connect = connect
        creation = asyncio.create_task(self.manager.start("test"))
        await entered.wait()
        with self.assertRaisesRegex(ValueError, "Session limit"):
            await self.manager.start("test")
        release.set()
        await creation
        self.assertEqual(self.manager.pending, 0)

    async def test_failed_connection_releases_slot(self):
        self.manager.connect = AsyncMock(side_effect=OSError("unavailable"))
        with self.assertRaises(OSError):
            await self.manager.start("test")
        self.assertEqual(self.manager.pending, 0)
        self.assertFalse(self.manager.terminals)

    async def test_expired_shell_and_completed_output_are_reaped(self):
        self.manager.config = replace(self.config, idle_timeout=1, retention_seconds=1)
        terminal = await self.manager.start("test")
        terminal.last_access -= 10
        reaper = asyncio.create_task(self.manager.reap())
        try:
            await asyncio.sleep(1.1)
            self.assertNotIn(terminal.id, self.manager.terminals)
            self.assertTrue(self.connection.closed)
            self.connection = Connection()
            self.manager.connect = AsyncMock(return_value=self.connection)
            terminal = await self.manager.start("test", "fake-command")
            self.connection.process.finish()
            await terminal.task
            terminal.finished_at -= 10
            await asyncio.sleep(1.1)
            self.assertNotIn(terminal.id, self.manager.terminals)
        finally:
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper
