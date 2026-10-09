import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ssh_mcp.auth import BearerAuth
from ssh_mcp.config import Config, ConfigError
from ssh_mcp.console import Console
from ssh_mcp.registry import Conflict, Registry

ADMIN = "console-test-admin-" + "a" * 40
MCP = "console-test-mcp-" + "m" * 40


def server_data(sid="staging"):
    return {"id": sid, "host": "192.0.2.10", "username": "ops", "port": 22,
            "description": "测试环境", "known_hosts": "/etc/ssh-mcp/known_hosts",
            "password_env": "STAGING_SSH_PASSWORD"}


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "db.sqlite3"
        self.registry = Registry(Config(servers=()), self.path)
        self.addCleanup(lambda: self.registry.close())

    def test_persistence_and_no_reimport_after_delete(self):
        self.registry.change(1, "staging", server_data(), create=True)
        config = self.registry.config(Config(servers=()))
        second = Registry(config, self.path)
        try:
            self.assertEqual(second.snapshot()["servers"][0]["id"], "staging")
            second.change(2, "staging", None)
        finally:
            second.close()
        third = Registry(config, self.path)
        try:
            self.assertEqual(third.snapshot()["servers"], [])
            self.assertEqual(third.snapshot()["revision"], 3)
        finally:
            third.close()

    def test_stale_writes_are_rejected_without_losing_data(self):
        self.registry.change(1, "staging", server_data(), create=True)
        with self.assertRaises(Conflict):
            self.registry.change(1, "staging", {**server_data(), "host": "wrong.invalid"})
        self.assertEqual(self.registry.snapshot()["servers"][0]["host"], "192.0.2.10")
        self.assertEqual(len(self.registry.history()), 1)

    def test_invalid_credentials_rejected_and_permissions_private(self):
        with self.assertRaises(ConfigError):
            self.registry.change(1, "staging", {**server_data(), "password": "secret"}, create=True)
        self.assertEqual(self.registry.snapshot(), {"revision": 1, "servers": []})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_update_id_immutable_and_duplicate_rejected(self):
        self.registry.change(1, "staging", server_data(), create=True)
        with self.assertRaises(Conflict):
            self.registry.change(2, "staging", server_data(), create=True)
        with self.assertRaises(ValueError):
            self.registry.change(2, "staging", server_data("renamed"))
        self.assertEqual(self.registry.snapshot()["revision"], 2)


class ConsoleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        config = Config(servers=())
        self.registry = Registry(config)
        self.manager = SimpleNamespace(config=config, list_sessions=lambda: [],
                                       connect=AsyncMock(), close=AsyncMock(return_value={"status": "closed"}),
                                       start=AsyncMock(return_value=SimpleNamespace(id="session-test", server_id="staging")),
                                       send=AsyncMock(return_value={"accepted_chars": 5}),
                                       read=AsyncMock(return_value={"status": "running"}))
        connection = SimpleNamespace(close=lambda: None, wait_closed=AsyncMock())
        self.manager.connect.return_value = connection

        async def mcp(scope, receive, send):
            await Console.respond(send, 200, {"mcp": True})

        self.app = Console(BearerAuth(mcp, MCP), self.manager, self.registry, ADMIN)

    async def asyncTearDown(self):
        self.registry.close()

    async def request(self, path, method="GET", body=None, token=ADMIN, headers=None, raw=None):
        sent = []
        scope = {"type": "http", "scheme": "http", "path": path, "method": method,
                 "headers": [(b"host", b"localhost:8000"), *(([(b"authorization", f"Bearer {token}".encode())]) if token else []), *(headers or [])]}
        consumed = False

        async def receive():
            nonlocal consumed
            if consumed:
                return {"type": "http.disconnect"}
            consumed = True
            return {"type": "http.request", "body": raw if raw is not None else json.dumps(body or {}).encode()}

        async def send(message):
            sent.append(message)

        await self.app(scope, receive, send)
        result = b"".join(m.get("body", b"") for m in sent)
        return sent[0]["status"], result, dict(sent[0]["headers"])

    async def test_admin_mcp_tokens_are_separate(self):
        for token in (None, MCP):
            self.assertEqual((await self.request("/admin/state", token=token))[0], 401)
        self.assertEqual((await self.request("/mcp", token=ADMIN))[0], 401)
        self.assertEqual((await self.request("/mcp", token=MCP))[0], 200)
        self.assertEqual((await self.request("/admin/state"))[0], 200)

    async def test_static_shell_is_public_but_has_no_inventory(self):
        status, body, headers = await self.request("/console", token=None)
        self.assertEqual(status, 200)
        self.assertIn("服务器控制台".encode(), body)
        self.assertIn(b"frame-ancestors 'none'", headers[b"content-security-policy"])
        self.assertNotIn(ADMIN.encode(), body)
        self.assertEqual((await self.request("/console/../../config.json", token=None))[0], 404)

    async def test_origin_and_duplicate_host_rejected(self):
        for headers in ([(b"origin", b"https://evil.invalid")], [(b"host", b"evil.invalid")]):
            self.assertEqual((await self.request("/admin/state", headers=headers))[0], 403)

    async def test_create_edit_delete_updates_live_manager(self):
        self.assertEqual((await self.request("/admin/servers", "POST", {"revision":1, "server":server_data()}))[0], 200)
        self.assertEqual(self.manager.config.server("staging").host, "192.0.2.10")
        data = {**server_data(), "description": "edited"}
        self.assertEqual((await self.request("/admin/servers/staging", "PUT", {"revision":2,"server":data}))[0], 200)
        self.assertEqual(self.manager.config.server("staging").description, "edited")
        self.assertEqual((await self.request("/admin/servers/staging", "DELETE", {"revision":3}))[0], 200)
        self.assertEqual(self.manager.config.servers, ())

    async def test_stale_revision_and_active_session_delete_rejected(self):
        await self.request("/admin/servers", "POST", {"revision":1,"server":server_data()})
        self.assertEqual((await self.request("/admin/servers/staging", "DELETE", {"revision":1}))[0], 409)
        self.manager.list_sessions = lambda: [{"server_id":"staging", "status":"running"}]
        self.assertEqual((await self.request("/admin/servers/staging", "DELETE", {"revision":2}))[0], 409)

    async def test_probe_never_returns_library_secret(self):
        await self.request("/admin/servers", "POST", {"revision":1,"server":server_data()})
        self.manager.connect.side_effect = ValueError("test-private-secret-do-not-return")
        status, data, _ = await self.request("/admin/servers/staging/test", "POST")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(data)["ok"])
        self.assertNotIn(b"test-private-secret", data)
        self.assertEqual(self.registry.history()[0]["outcome"], "failed")

    async def test_body_validation_limits_and_audit_excludes_input(self):
        self.assertEqual((await self.request("/admin/state", raw=b"{bad-json"))[0], 400)
        self.assertEqual((await self.request("/admin/state", raw=b"x" * 65537))[0], 413)
        await self.request("/admin/sessions/test/input", "POST", {"data":"secret-command"})
        self.manager.send.assert_awaited_once_with("test", "secret-command")
        self.assertNotIn("secret-command", str(self.registry.history()))

    async def test_missing_admin_setup_is_explicit(self):
        self.app.admin_app = None
        self.assertEqual((await self.request("/admin/state"))[0], 503)
