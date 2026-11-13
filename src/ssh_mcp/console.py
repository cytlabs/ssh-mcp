"""同源管理台；管理员凭据与 MCP 工具权限分离。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from datetime import date, datetime, timezone

from . import __version__
from .auth import BearerAuth
from .command_audit import command_history
from .config import ConfigError
from .errors import InputError
from .registry import Conflict

ASSETS = Path(__file__).parent / "static"
SECURITY_HEADERS = [
    (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"), (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"default-src 'none'; script-src 'self'; style-src 'self'; "
     b"connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"),
]


class Console:
    def __init__(self, mcp_app, manager, registry, admin_token: str | None):
        self.mcp_app, self.manager, self.registry = mcp_app, manager, registry
        self.admin_app = BearerAuth(self.api, admin_token, max_body=65536) if admin_token else None
        self.probes = asyncio.Semaphore(4)
        self.checks = {}
        self.username = lambda: None

    def trusted(self, scope) -> bool:
        headers = scope.get("headers", [])
        hosts = [v.decode("latin1") for k, v in headers if k.lower() == b"host"]
        origins = [v.decode("latin1") for k, v in headers if k.lower() == b"origin"]
        if len(hosts) != 1 or len(origins) > 1:
            return False
        public = self.manager.config.public_url.rstrip("/")
        try:
            host = urlsplit("http://" + hosts[0])
            if host.username or host.password or host.path or host.query or host.fragment:
                return False
            local = host.hostname in ("localhost", "127.0.0.1", "::1")
            if not (local or hosts[0] == urlsplit(public).netloc):
                return False
            return not origins or origins[0] == public or (
                local and origins[0] == f"{scope.get('scheme', 'http')}://{hosts[0]}"
            )
        except ValueError:
            return False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.mcp_app(scope, receive, send)
        path = scope["path"]
        if path == "/":
            accept = b",".join(value.lower() for key, value in scope.get("headers", [])
                               if key.lower() == b"accept")
            protocol_request = scope["method"] in ("POST", "DELETE", "OPTIONS") or (
                scope["method"] == "GET"
                and any(value in accept for value in (b"application/json", b"text/event-stream"))
            )
            if protocol_request:
                if not self.trusted(scope):
                    return await self.respond(send, 403, {"error": "请求来源不受信任"})
                # 与 OpenViking 的根地址分流一致，保留 MCP 的认证挑战和请求体。
                mcp_scope = {**scope, "path": "/mcp", "raw_path": b"/mcp"}
                return await self.mcp_app(mcp_scope, receive, send)
        if path == "/auth/session" and scope["method"] == "GET":
            return await self.respond(send, 200, {"mode": "token"})
        if path not in ("/", "/console", "/console/") and not path.startswith(("/console/", "/admin/")):
            return await self.mcp_app(scope, receive, send)
        if not self.trusted(scope):
            return await self.respond(send, 403, {"error": "请求来源不受信任"})
        if path.startswith("/admin/"):
            if not self.admin_app:
                return await self.respond(send, 503, {"error": "请在服务端设置独立的 SSH_MCP_ADMIN_TOKEN 后重启"})
            return await self.admin_app(scope, receive, send)
        if scope["method"] != "GET":
            return await self.respond(send, 405, {"error": "Method not allowed"})
        names = {"/": "index.html", "/console": "index.html", "/console/": "index.html",
                 "/console/app.js": "app.js", "/console/style.css": "style.css",
                 "/console/logo.svg": "logo.svg"}
        name = names.get(path)
        if not name:
            return await self.respond(send, 404, {"error": "Not found"})
        content_type = {"html": "text/html", "js": "text/javascript", "css": "text/css", "svg": "image/svg+xml"}[name.split(".")[-1]]
        await self.respond(send, 200, (ASSETS / name).read_bytes(), content_type)

    async def api(self, scope, receive, send):
        try:
            raw = bytearray()
            while True:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    return
                raw.extend(msg.get("body", b""))
                if not msg.get("more_body"):
                    break
            body = json.loads(raw) if raw else {}
            if not isinstance(body, dict):
                raise InputError("请求内容必须为对象")
            result = await self.dispatch(scope["method"], scope["path"], body, scope.get("query_string", b""))
            await self.respond(send, 200, result)
        except Conflict:
            await self.respond(send, 409, {"error": "配置已变化、ID 重复或仍有运行中的会话。请刷新并检查后重试。"})
        except (ConfigError, InputError, ValueError, KeyError, TypeError):
            await self.respond(send, 400, {"error": "请检查必填字段、服务器 ID、端口、凭据引用及会话状态。"})
        except Exception:
            # Never serialize arbitrary SSH/SQLite exceptions or credential paths.
            await self.respond(send, 502, {"error": "操作未完成。请检查服务端配置、文件权限或 SSH 连接。"})

    async def test_connection(self, server):
        async with self.probes:
            started = time.monotonic()
            try:
                connection = await self.manager.connect(server)
                connection.close()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(connection.wait_closed(), 3)
                result = {"ok": True, "latency_ms": round((time.monotonic() - started) * 1000)}
            except Exception:
                result = {"ok": False, "message": "连接失败：请检查网络、凭据和主机密钥。"}
            if server in self.manager.config.servers:
                self.checks[server.id] = {**result, "checked_at": datetime.now(timezone.utc).isoformat()}
                self.registry.record("connection.test", server.id, "ok" if result["ok"] else "failed")
            return result

    async def monitor_connections(self):
        while True:
            started = time.monotonic()
            await asyncio.gather(*(self.test_connection(s) for s in self.manager.config.servers),
                                 return_exceptions=True)
            await asyncio.sleep(max(0, 300 - (time.monotonic() - started)))

    async def dispatch(self, method: str, path: str, body: dict, query: bytes = b"") -> dict:
        parts = path.strip("/").split("/")
        if method == "GET" and path == "/admin/state":
            return {**self.registry.snapshot(), "version": __version__,
                    "mcp_url": self.manager.config.public_url.rstrip("/") + "/mcp",
                    "auth_mode": self.manager.config.auth_mode,
                    "username": self.username(), "checks": self.checks,
                    "sessions": self.manager.list_sessions(), "activity": self.registry.history()}
        if method == "GET" and path == "/admin/command-audit":
            options = parse_qs(query.decode(), max_num_fields=4)
            before = int(options.get("before", [2**63 - 1])[0])
            if not 0 < before < 2**63:
                raise InputError("Invalid cursor")
            return await asyncio.to_thread(command_history, before, options.get("search", [""])[0],
                                           options.get("start", [""])[0], options.get("end", [""])[0])
        if method == "GET" and path == "/admin/activity":
            options = parse_qs(query.decode("utf-8"), keep_blank_values=True, max_num_fields=12)
            if any(len(values) != 1 for values in options.values()):
                raise InputError("Duplicate query parameters")
            def option(key, default=""):
                return options.get(key, [default])[0]
            page = int(option("page", "1"))
            size = int(option("size", "10"))
            search = option("search").strip()
            event = option("event", "all")
            outcome = option("outcome", "all")
            start, end = option("start"), option("end")
            if not (1 <= page <= 10000 and size in (10, 20, 50) and len(search) <= 120):
                raise InputError("Invalid pagination or search")
            if event not in ("all", "server", "connection", "session") or outcome not in ("all", "ok", "failed"):
                raise InputError("Invalid activity filters")
            if (start and date.fromisoformat(start).isoformat() != start) or (end and date.fromisoformat(end).isoformat() != end):
                raise InputError("Invalid dates")
            if start and end and start > end:
                raise InputError("Invalid date range")
            return self.registry.search_history(page=page, size=size, search=search,
                                                event=event, outcome=outcome, start=start, end=end)
        if method == "POST" and path == "/admin/servers":
            data = body["server"]
            self.registry.change(body["revision"], data["id"], data, create=True)
            self.manager.config = self.registry.config(self.manager.config)
            return {"ok": True}
        if len(parts) == 3 and parts[:2] == ["admin", "servers"] and method in ("PUT", "DELETE"):
            sid = parts[2]
            if method == "DELETE" and any(t["server_id"] == sid and t["status"] == "running"
                                          for t in self.manager.list_sessions()):
                raise Conflict("Close active sessions first")
            self.registry.change(body["revision"], sid, body["server"] if method == "PUT" else None)
            self.checks.pop(sid, None)
            self.manager.config = self.registry.config(self.manager.config)
            return {"ok": True}
        if len(parts) == 4 and parts[:2] == ["admin", "servers"] and parts[3] == "test" and method == "POST":
            server = self.manager.config.server(parts[2])
            return await self.test_connection(server)
        if path == "/admin/sessions" and method == "POST":
            terminal = await self.manager.start(body["server_id"], pty=False)
            self.registry.record("session.create", terminal.server_id)
            return {"session_id": terminal.id}
        if len(parts) == 3 and parts[:2] == ["admin", "sessions"] and method == "DELETE":
            result = await self.manager.close(parts[2])
            self.registry.record("session.close", "session")
            return result
        if len(parts) == 4 and parts[:2] == ["admin", "sessions"] and method == "POST":
            if parts[3] == "read":
                return await self.manager.read(parts[2], body.get("stdout_cursor", 0),
                                               body.get("stderr_cursor", 0), max_chars=32768)
            if parts[3] == "input":
                if not isinstance(body.get("data"), str):
                    raise InputError("data must be text")
                result = await self.manager.send(parts[2], body["data"])
                self.registry.record("session.input", "session")
                return result
        raise InputError("Unknown operation")

    @staticmethod
    async def respond(send, status: int, value, content_type="application/json"):
        data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [*SECURITY_HEADERS, (b"content-type", (content_type + "; charset=utf-8").encode())]})
        await send({"type": "http.response.body", "body": data})
