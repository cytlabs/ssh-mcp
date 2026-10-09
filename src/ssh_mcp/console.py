"""Same-origin operator console; admin credentials never authorize MCP requests."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .auth import BearerAuth
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
                 "/console/app.js": "app.js", "/console/style.css": "style.css"}
        name = names.get(path)
        if not name:
            return await self.respond(send, 404, {"error": "Not found"})
        content_type = {"html": "text/html", "js": "text/javascript", "css": "text/css"}[name.split(".")[-1]]
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
            result = await self.dispatch(scope["method"], scope["path"], body)
            await self.respond(send, 200, result)
        except Conflict:
            await self.respond(send, 409, {"error": "配置已变化、ID 重复或仍有运行中的会话。请刷新并检查后重试。"})
        except (ConfigError, InputError, ValueError, KeyError, TypeError):
            await self.respond(send, 400, {"error": "请检查必填字段、服务器 ID、端口、凭据引用及会话状态。"})
        except Exception:
            # Never serialize arbitrary SSH/SQLite exceptions or credential paths.
            await self.respond(send, 502, {"error": "操作未完成。请检查服务端配置、文件权限或 SSH 连接。"})

    async def dispatch(self, method: str, path: str, body: dict) -> dict:
        parts = path.strip("/").split("/")
        if method == "GET" and path == "/admin/state":
            return {**self.registry.snapshot(), "version": __version__,
                    "mcp_url": self.manager.config.public_url.rstrip("/") + "/mcp",
                    "sessions": self.manager.list_sessions(), "activity": self.registry.history()}
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
            self.manager.config = self.registry.config(self.manager.config)
            return {"ok": True}
        if len(parts) == 4 and parts[:2] == ["admin", "servers"] and parts[3] == "test" and method == "POST":
            server = self.manager.config.server(parts[2])
            started = time.monotonic()
            async with self.probes:
                try:
                    connection = await self.manager.connect(server)
                    connection.close()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(connection.wait_closed(), 3)
                except Exception:
                    self.registry.record("connection.test", server.id, "failed")
                    return {"ok": False, "message": "连接失败：请检查网络、凭据和已核验的主机密钥。"}
            self.registry.record("connection.test", server.id)
            return {"ok": True, "latency_ms": round((time.monotonic() - started) * 1000)}
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
