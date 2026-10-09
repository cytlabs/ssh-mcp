"""SSH processes outlive individual MCP requests; state belongs to this worker."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

import asyncssh

from .buffer import OutputBuffer
from .config import Config, Server, integer
from .errors import InputError


@dataclass
class Terminal:
    id: str
    server_id: str
    connection: asyncssh.SSHClientConnection
    process: asyncssh.SSHClientProcess
    stdout: OutputBuffer
    stderr: OutputBuffer
    kind: str
    status: str = "running"
    last_access: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    task: asyncio.Task | None = None
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    input_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    exit_code: int | None = None
    exit_signal: str | None = None


class SSHManager:
    def __init__(self, config: Config):
        self.config = config
        self.terminals: dict[str, Terminal] = {}
        self.pending = 0
        self.lock = asyncio.Lock()
        self.file_slots = asyncio.Semaphore(config.max_sessions)
        self.stopping = False

    async def connect(self, server: Server) -> asyncssh.SSHClientConnection:
        # No ambient ssh_config, agent, default identity, or keyboard-interactive auth.
        return await asyncio.wait_for(asyncssh.connect(
            server.host, port=server.port, username=server.username,
            known_hosts=str(server.known_hosts), config=None, agent_path=None,
            client_keys=[str(server.private_key)] if server.private_key else [],
            preferred_auth="publickey,password", kbdint_auth=False,
            connect_timeout=self.config.connect_timeout,
            login_timeout=self.config.connect_timeout,
            keepalive_interval=30, keepalive_count_max=3,
            **server.credentials(),
        ), self.config.connect_timeout)

    async def start(self, server_id: str, command: str | None = None,
                    pty: bool = True, cols: int = 120, rows: int = 40,
                    timeout_seconds: int = 3600) -> Terminal:
        server = self.config.server(server_id)
        integer(cols, "cols", 1, 1000)
        integer(rows, "rows", 1, 1000)
        integer(timeout_seconds, "timeout_seconds", 1, 604800)
        if command is not None and (not command or len(command) > 131072 or "\x00" in command):
            raise InputError("command must contain 1–131072 characters without NUL")
        async with self.lock:
            if self.stopping:
                raise InputError("Server is shutting down")
            if len(self.terminals) + self.pending >= self.config.max_sessions:
                raise InputError("Session limit reached; close completed sessions first")
            self.pending += 1
        connection = None
        try:
            connection = await self.connect(server)
            process = await asyncio.wait_for(connection.create_process(
                command, term_type="xterm-256color" if pty else None,
                term_size=(cols, rows), encoding="utf-8", errors="replace",
            ), self.config.connect_timeout)
            terminal = Terminal(
                id=uuid.uuid4().hex, server_id=server_id, connection=connection,
                process=process, stdout=OutputBuffer(self.config.buffer_chars),
                stderr=OutputBuffer(self.config.buffer_chars),
                kind="command" if command is not None else "shell",
            )
            if self.stopping:
                raise InputError("Server is shutting down")
            self.terminals[terminal.id] = terminal
            terminal.task = asyncio.create_task(self._monitor(
                terminal, timeout_seconds if command is not None else None,
            ))
            return terminal
        except BaseException:
            if connection:
                connection.close()
            raise
        finally:
            async with self.lock:
                self.pending -= 1

    async def _pump(self, stream, buffer: OutputBuffer, changed: asyncio.Event) -> None:
        while True:
            chunk = await stream.read(16384)
            if not chunk:
                return
            buffer.append(chunk)
            changed.set()

    async def _monitor(self, terminal: Terminal, timeout: int | None) -> None:
        pumps = [asyncio.create_task(self._pump(terminal.process.stdout, terminal.stdout,
                                                terminal.changed)),
                 asyncio.create_task(self._pump(terminal.process.stderr, terminal.stderr,
                                                terminal.changed))]
        try:
            # wait_closed does not collect output; the bounded pumps above do that.
            await asyncio.wait_for(terminal.process.wait_closed(), timeout)
            await asyncio.gather(*pumps)
            terminal.exit_code = terminal.process.exit_status
            signal = terminal.process.exit_signal
            terminal.exit_signal = signal[0] if signal else None
            if terminal.status == "running":
                terminal.status = "completed" if terminal.exit_code is not None else "disconnected"
        except asyncio.TimeoutError:
            terminal.status = "timed_out"
            with contextlib.suppress(asyncssh.Error, OSError):
                terminal.process.kill()
        except asyncio.CancelledError:
            if terminal.status == "running":
                terminal.status = "closed"
            raise
        except Exception:
            terminal.status = "disconnected"
        finally:
            for pump in pumps:
                if not pump.done():
                    pump.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            terminal.process.close()
            terminal.connection.close()
            with contextlib.suppress(asyncio.TimeoutError, asyncssh.Error, OSError):
                await asyncio.wait_for(terminal.connection.wait_closed(), 3)
            terminal.finished_at = time.monotonic()
            terminal.changed.set()

    def get(self, session_id: str) -> Terminal:
        terminal = self.terminals.get(session_id)
        if terminal is None:
            raise InputError("Unknown or expired session_id")
        terminal.last_access = time.monotonic()
        return terminal

    async def read(self, session_id: str, stdout_cursor: int = 0, stderr_cursor: int = 0,
                   max_chars: int = 32768, wait_seconds: int = 0) -> dict:
        integer(max_chars, "max_chars", 1, 131072)
        integer(wait_seconds, "wait_seconds", 0, 25)
        terminal = self.get(session_id)
        # Check cursors before waiting. Clearing is synchronous with checking the buffers.
        out = terminal.stdout.read(stdout_cursor, max_chars)
        err = terminal.stderr.read(stderr_cursor, max_chars)
        if wait_seconds and not out["text"] and not err["text"] and terminal.status == "running":
            terminal.changed.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(terminal.changed.wait(), wait_seconds)
        return {
            "session_id": session_id, "server_id": terminal.server_id,
            "kind": terminal.kind, "status": terminal.status,
            "stdout": terminal.stdout.read(stdout_cursor, max_chars),
            "stderr": terminal.stderr.read(stderr_cursor, max_chars),
            "exit_code": terminal.exit_code, "exit_signal": terminal.exit_signal,
        }

    async def send(self, session_id: str, data: str, eof: bool = False) -> dict:
        if len(data) > 131072:
            raise InputError("Input exceeds 131072 characters")
        terminal = self.get(session_id)
        if terminal.status != "running":
            raise InputError("Session is no longer running")
        async with terminal.input_lock:
            terminal.process.stdin.write(data)
            await asyncio.wait_for(terminal.process.stdin.drain(), 10)
            if eof:
                terminal.process.stdin.write_eof()
        return {"session_id": session_id, "accepted_chars": len(data), "eof": eof}

    async def close(self, session_id: str, status: str = "closed") -> dict:
        terminal = self.terminals.pop(session_id, None)
        if terminal is None:
            return {"session_id": session_id, "status": "already_closed"}
        terminal.status = status
        if terminal.task and not terminal.task.done():
            with contextlib.suppress(asyncssh.Error, OSError):
                terminal.process.terminate()
            terminal.process.close()
            terminal.connection.close()
            terminal.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await terminal.task
            with contextlib.suppress(asyncio.TimeoutError, asyncssh.Error, OSError):
                await asyncio.wait_for(terminal.connection.wait_closed(), 3)
        return {"session_id": session_id, "status": status}

    def list_sessions(self) -> list[dict]:
        return [{"session_id": t.id, "server_id": t.server_id, "kind": t.kind,
                 "status": t.status} for t in self.terminals.values()]

    async def reap(self) -> None:
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            for sid, terminal in list(self.terminals.items()):
                if terminal.finished_at is not None:
                    if now - terminal.finished_at >= self.config.retention_seconds:
                        await self.close(sid, "expired")
                elif terminal.kind == "shell" and now - terminal.last_access >= self.config.idle_timeout:
                    await self.close(sid, "expired")

    async def shutdown(self) -> None:
        self.stopping = True
        await asyncio.gather(*(self.close(sid) for sid in list(self.terminals)))

    async def file(self, server_id: str, action: Literal["read", "write", "delete", "list", "stat"],
                   path: str, data: str = "", encoding: Literal["utf-8", "base64"] = "utf-8",
                   offset: int = 0, length: int = 65536, truncate: bool = False) -> dict:
        if not path or "\x00" in path or len(path) > 4096:
            raise InputError("path must contain 1–4096 characters without NUL")
        integer(offset, "offset", 0, 2**53 - 1)
        integer(length, "length", 1, self.config.max_file_chunk)
        if encoding not in ("utf-8", "base64") or action not in ("read", "write", "delete", "list", "stat"):
            raise InputError("Invalid file action or encoding")
        if len(data) > self.config.max_file_chunk * 4:
            raise InputError("File chunk too large")
        try:
            content = base64.b64decode(data, validate=True) if encoding == "base64" else data.encode()
        except (ValueError, binascii.Error):
            raise InputError("Invalid base64 content") from None
        if len(content) > self.config.max_file_chunk:
            raise InputError("File chunk too large")
        if truncate and offset != 0:
            raise InputError("truncate requires offset=0")
        async with self.file_slots:
            return await asyncio.wait_for(self._file(
                self.config.server(server_id), action, path, content, encoding,
                offset, length, truncate,
            ), self.config.file_timeout)

    async def _file(self, server, action, path, content, encoding, offset, length, truncate):
        connection = await self.connect(server)
        try:
            async with connection.start_sftp_client() as sftp:
                if action == "read":
                    async with sftp.open(path, "rb") as f:
                        await f.seek(offset)
                        raw = await f.read(length + 1)
                    eof = len(raw) <= length
                    raw = raw[:length]
                    if encoding == "utf-8":
                        # Avoid splitting a UTF-8 character at the end of a full chunk.
                        try:
                            text = raw.decode("utf-8")
                        except UnicodeDecodeError as exc:
                            if not eof and exc.reason == "unexpected end of data" and exc.start > 0:
                                raw = raw[:exc.start]
                                text = raw.decode("utf-8")
                            else:
                                raise InputError("Not a complete UTF-8 chunk; use base64") from None
                    else:
                        text = base64.b64encode(raw).decode("ascii")
                    return {"data": text, "encoding": encoding, "bytes": len(raw),
                            "next_offset": offset + len(raw), "eof": eof}
                if action == "write":
                    flags = asyncssh.FXF_WRITE | asyncssh.FXF_CREAT
                    if truncate:
                        flags |= asyncssh.FXF_TRUNC
                    async with sftp.open(path, flags, encoding=None) as f:
                        await f.seek(offset)
                        await f.write(content)
                    return {"bytes_written": len(content), "next_offset": offset + len(content)}
                if action == "delete":
                    await sftp.remove(path)
                    return {"deleted": True}
                if action == "stat":
                    attrs = await sftp.stat(path)
                    return {"size": attrs.size, "permissions": attrs.permissions,
                            "mtime": attrs.mtime, "type": attrs.type}
                entries = []
                async for entry in sftp.scandir(path):
                    if entry.filename in (".", ".."):
                        continue
                    if len(entries) >= 1000:
                        return {"entries": entries, "truncated": True}
                    entries.append({"name": entry.filename, "size": entry.attrs.size,
                                    "type": entry.attrs.type})
                return {"entries": entries, "truncated": False}
        finally:
            connection.close()
            with contextlib.suppress(asyncio.TimeoutError, asyncssh.Error, OSError):
                await asyncio.wait_for(connection.wait_closed(), 3)
