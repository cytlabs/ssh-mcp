"""OAuth HTTP 流程、安全边界与重启持久化；不访问真实服务器。"""
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx

from ssh_mcp.auth import BearerAuth
from ssh_mcp.config import Config
from ssh_mcp.console import Console
from ssh_mcp.identity import AuthError, IdentityStore, digest, password_hash
from ssh_mcp.oauth import COOKIE, OAuth
from ssh_mcp.registry import Registry

ORIGIN = "https://ssh.example.test"
RESOURCE = ORIGIN + "/mcp"
BOOTSTRAP = "bootstrap-fixture-" + "b" * 40
PASSWORD = "测试密码-for-fixture-only"
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
REDIRECT = "http://127.0.0.1:8765/callback"


class OAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "auth.sqlite3"
        self.store = IdentityStore(self.path, RESOURCE)
        config = Config(servers=(), public_url=ORIGIN, auth_mode="oauth")
        self.registry = Registry(config)
        manager = SimpleNamespace(config=config, list_sessions=lambda: [])

        async def mcp(scope, receive, send):
            await Console.respond(send, 200, {"mcp": True})

        console = Console(BearerAuth(mcp, validator=self.store.access_valid,
                                    challenge=f'Bearer resource_metadata="{ORIGIN}/.well-known/oauth-protected-resource/mcp"'.encode()),
                          manager, self.registry, None)
        self.app = OAuth(console, self.store)
        self.setup_token = self.store.setup_link().split("#setup=")[1]
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=ORIGIN)
        self.csrf = ""

    async def asyncTearDown(self):
        await self.client.aclose()
        self.registry.close()
        self.store.close()
        self.tmp.cleanup()

    async def browser(self, path, data, **extra):
        return await self.client.post(path, json=data, headers={"Origin": ORIGIN, "X-CSRF-Token": self.csrf, **extra})

    async def login(self):
        bootstrap = await self.browser("/auth/setup-session", {"setup_token": self.setup_token})
        self.assertEqual(bootstrap.status_code, 200)
        response = await self.browser("/auth/setup", {"username": "admin", "password": PASSWORD, "setup_token": self.setup_token})
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()["csrf"]
        return response

    async def register(self, **values):
        response = await self.client.post("/oauth/register", json={"redirect_uris": [REDIRECT], "client_name": "测试客户端", **values})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def test_account_settings(self):
        await self.login()
        saved = await self.browser("/auth/profile", {"nickname": "  林辰  "})
        self.assertEqual(saved.json()["nickname"], "林辰")
        self.assertEqual(self.store.owner_profile(), ("admin", "林辰"))
        old_session = self.client.cookies.get(COOKIE)
        change = {"username": "ops", "current_password": PASSWORD}
        self.assertEqual((await self.browser("/auth/account", {**change, "current_password": "bad"})).status_code, 403)
        self.assertEqual((await self.browser("/auth/account", change)).status_code, 200)
        self.assertEqual(self.store.owner_username(), "ops")
        self.assertTrue(self.store.session_valid(old_session))
        self.assertEqual((await self.browser("/auth/account", {**change, "new_password": PASSWORD + "2"})).status_code, 200)
        self.assertFalse(self.store.session_valid(old_session))
        self.assertEqual(self.store.owner_profile(), ("ops", "林辰"))
        self.assertEqual((await self.browser("/auth/login", {"username": "ops", "password": PASSWORD})).status_code, 401)
        self.assertEqual((await self.browser("/auth/login", {"username": "ops", "password": PASSWORD + "2"})).status_code, 200)

    async def code(self, client, *, include_resource=True, **values):
        params = {
            "client_id": client["client_id"], "redirect_uri": REDIRECT,
            "response_type": "code", "code_challenge_method": "S256", "code_challenge": CHALLENGE,
            "resource": RESOURCE, "state": "state-fixture", **values}
        if not include_resource:
            params.pop("resource")
        response = await self.client.get("/oauth/authorize", params=params)
        self.assertEqual(response.status_code, 302, response.text)
        handle = parse_qs(urlsplit(response.headers["location"]).query)["authorize"][0]
        info = await self.client.get("/auth/consent", params={"request": handle})
        self.assertEqual(info.status_code, 200, info.text)
        response = await self.browser("/auth/consent", {"request": handle, "approve": True})
        self.assertEqual(response.status_code, 200, response.text)
        parsed = parse_qs(urlsplit(response.json()["redirect"]).query)
        self.assertEqual(parsed["state"], ["state-fixture"])
        self.assertEqual(parsed["iss"], [ORIGIN])
        return parsed["code"][0]

    async def exchange(self, client, code, **values):
        return await self.client.post("/oauth/token", data={"client_id": client["client_id"],
            "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
            "code_verifier": VERIFIER, "resource": RESOURCE, **values})

    async def access(self, token):
        return await self.client.get("/mcp", headers={"Authorization": "Bearer " + token})

    async def test_discovery_and_public_cors(self):
        challenge = await self.client.get("/mcp")
        self.assertEqual(challenge.status_code, 401)
        self.assertIn("resource_metadata", challenge.headers["www-authenticate"])
        for path in ("/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-authorization-server"):
            response = await self.client.get(path, headers={"Origin": "https://client.example"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["access-control-allow-origin"], "*")
            self.assertNotIn("access-control-allow-credentials", response.headers)
        response = await self.client.get("/auth/session", headers={"Host": "evil.example"})
        self.assertEqual(response.status_code, 403)

    async def test_registration_defaults_null_and_empty_scope_without_widening_access(self):
        # 对齐标准客户端的可选字段；未指定权限只授予本服务的固定范围。
        for scope in (None, "", "ssh:access"):
            with self.subTest(scope=scope):
                registered = await self.register(scope=scope)
                self.assertEqual(registered["scope"], "ssh:access")
        for scope in (False, 0, [], "ssh:access other"):
            with self.subTest(invalid_scope=scope):
                response = await self.client.post("/oauth/register", json={
                    "redirect_uris": [REDIRECT], "scope": scope})
                self.assertEqual(response.status_code, 400)

    async def test_authorization_without_resource_still_binds_grant_and_token_to_server(self):
        await self.login()
        client = await self.register()
        code = await self.code(client, include_resource=False)
        rejected = await self.exchange(client, code, resource="https://other.example/mcp")
        self.assertEqual(rejected.status_code, 400)
        response = await self.exchange(client, code)
        self.assertEqual(response.status_code, 200)
        self.assertEqual((await self.access(response.json()["access_token"])).status_code, 200)
        grant = self.store.db.execute("SELECT resource FROM grants").fetchone()
        self.assertEqual(grant["resource"], RESOURCE)

    async def test_public_client_accepts_empty_secret_but_not_confidential_credentials(self):
        await self.login()
        client = await self.register(token_endpoint_auth_method="none")
        code = await self.code(client)
        rejected = await self.exchange(client, code, client_secret="unexpected-secret")
        self.assertEqual(rejected.status_code, 401)
        response = await self.exchange(client, code, client_secret="")
        self.assertEqual(response.status_code, 200)
        revoked = await self.client.post("/oauth/revoke", data={
            "client_id": client["client_id"], "client_secret": "",
            "token": response.json()["refresh_token"]})
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual((await self.access(response.json()["access_token"])).status_code, 401)

    async def test_root_distinguishes_browser_from_authenticated_mcp_requests(self):
        page = await self.client.get("/", headers={"Accept": "text/html"})
        self.assertEqual(page.status_code, 200)
        missing = await self.client.post("/", json={}, headers={
            "Accept": "application/json, text/event-stream"})
        self.assertEqual(missing.status_code, 401)
        self.assertIn("resource_metadata", missing.headers["www-authenticate"])
        stream = await self.client.get("/", headers={"Accept": "text/event-stream"})
        self.assertEqual(stream.status_code, 401)
        await self.login()
        client = await self.register()
        response = await self.exchange(client, await self.code(client))
        headers = {"Authorization": "Bearer " + response.json()["access_token"],
                   "Accept": "application/json, text/event-stream"}
        reply = await self.client.post("/", json={}, headers=headers)
        self.assertEqual(reply.status_code, 200)
        self.assertTrue(reply.json()["mcp"])
        blocked = await self.client.post("/", json={}, headers={
            **headers, "Origin": "https://evil.example"})
        self.assertEqual(blocked.status_code, 403)

    async def test_full_flow_refresh_revoke_and_separate_admin_identity(self):
        login = await self.login()
        cookie = login.headers["set-cookie"]
        for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
            self.assertIn(flag, cookie)
        client = await self.register()
        code = await self.code(client)
        response = await self.exchange(client, code)
        self.assertEqual(response.status_code, 200, response.text)
        pair = response.json()
        self.assertEqual((await self.access(pair["access_token"])).status_code, 200)
        self.assertEqual((await self.access(pair["refresh_token"])).status_code, 401)
        self.assertEqual((await self.access(BOOTSTRAP)).status_code, 401)
        self.client.cookies.clear()
        response = await self.client.get("/admin/state", headers={"Authorization": "Bearer " + pair["access_token"]})
        self.assertEqual(response.status_code, 401)
        refreshed = await self.client.post("/oauth/token", data={"client_id": client["client_id"],
            "grant_type": "refresh_token", "refresh_token": pair["refresh_token"], "resource": RESOURCE})
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        current = refreshed.json()
        self.assertNotEqual(pair["refresh_token"], current["refresh_token"])
        response = await self.client.post("/oauth/revoke", data={"client_id": client["client_id"], "token": current["refresh_token"]})
        self.assertEqual(response.status_code, 200)
        for token in (pair["access_token"], current["access_token"]):
            self.assertEqual((await self.access(token)).status_code, 401)

    async def test_code_and_refresh_replay_revoke_entire_grant(self):
        await self.login()
        client = await self.register()
        for replay_type in ("code", "refresh"):
            code = await self.code(client)
            pair = (await self.exchange(client, code)).json()
            if replay_type == "code":
                replay = await self.exchange(client, code)
            else:
                data = {"client_id": client["client_id"], "grant_type": "refresh_token", "refresh_token": pair["refresh_token"]}
                new = await self.client.post("/oauth/token", data=data)
                self.assertEqual(new.status_code, 200)
                replay = await self.client.post("/oauth/token", data=data)
                self.assertFalse(self.store.access_valid(new.json()["access_token"]))
            self.assertEqual(replay.status_code, 400)
            self.assertFalse(self.store.access_valid(pair["access_token"]))

    async def test_pkce_resource_and_redirect_validation_does_not_consume_code(self):
        await self.login()
        client = await self.register()
        code = await self.code(client)
        for values in ({"code_verifier": "wrong" * 12}, {"resource": "https://other.example/mcp"},
                       {"redirect_uri": "https://evil.example/callback"}):
            self.assertEqual((await self.exchange(client, code, **values)).status_code, 400)
        self.assertEqual((await self.exchange(client, code)).status_code, 200)
        for redirect in ("https://evil.example/callback", "http://127.0.0.1:8765/other", "javascript:alert(1)"):
            response = await self.client.get("/oauth/authorize", params={"client_id": client["client_id"], "redirect_uri": redirect})
            self.assertEqual(response.status_code, 400)
            self.assertNotIn("location", response.headers)
        response = await self.client.get("/oauth/authorize", params={"client_id": client["client_id"],
            "redirect_uri": "http://127.0.0.1:54321/callback", "response_type": "code", "resource": RESOURCE,
            "code_challenge": CHALLENGE, "code_challenge_method": "S256"})
        self.assertEqual(response.status_code, 302)

    async def test_csrf_setup_login_logout_and_consent_binding(self):
        response = await self.client.post("/auth/setup", json={"username": "admin", "password": PASSWORD, "setup_token": self.setup_token})
        self.assertEqual(response.status_code, 403)
        await self.login()
        self.assertEqual((await self.browser("/auth/setup", {"username": "admin", "password": PASSWORD, "setup_token": self.setup_token})).status_code, 409)
        response = await self.client.post("/auth/logout", json={}, headers={"Origin": ORIGIN})
        self.assertEqual(response.status_code, 401)
        response = await self.client.post("/admin/servers", json={}, headers={"Origin": "https://evil.example", "X-CSRF-Token": self.csrf})
        self.assertEqual(response.status_code, 403)
        self.assertEqual((await self.client.get("/admin/state")).status_code, 200)
        client = await self.register()
        handle = self.store.authorize({"client_id": client["client_id"], "redirect_uri": REDIRECT,
            "response_type": "code", "resource": RESOURCE, "code_challenge": CHALLENGE, "code_challenge_method": "S256"})
        # 必须先看到授权详情，且授权请求绑定到该浏览器会话。
        self.assertEqual((await self.browser("/auth/consent", {"request": handle, "approve": True})).status_code, 400)
        self.store.consent_info(handle, self.client.cookies.get(COOKIE))
        other = self.store.browser_session()
        with self.assertRaises(AuthError):
            self.store.consent_info(handle, other)
        denied = await self.browser("/auth/consent", {"request": handle, "approve": False})
        self.assertIn("error=access_denied", denied.json()["redirect"])
        self.assertEqual((await self.browser("/auth/logout", {})).status_code, 200)
        self.assertEqual((await self.client.get("/admin/state")).status_code, 401)
        bad_user = await self.browser("/auth/login", {"username": "other", "password": PASSWORD})
        self.assertEqual(bad_user.status_code, 401)
        bad = await self.browser("/auth/login", {"username": "admin", "password": "wrong"})
        self.assertEqual(bad.status_code, 401)
        self.assertEqual((await self.browser("/auth/login", {"username": "admin", "password": PASSWORD})).status_code, 200)

    async def test_client_authentication_and_registration_validation(self):
        await self.login()
        for method in ("client_secret_basic", "client_secret_post"):
            client = await self.register(token_endpoint_auth_method=method)
            code = await self.code(client)
            self.assertEqual((await self.exchange(client, code)).status_code, 401)
            data = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "code_verifier": VERIFIER}
            if method == "client_secret_basic":
                response = await self.client.post("/oauth/token", data=data,
                    auth=(client["client_id"], client["client_secret"]))
            else:
                response = await self.client.post("/oauth/token", data={**data, "client_id": client["client_id"], "client_secret": client["client_secret"]})
            self.assertEqual(response.status_code, 200, response.text)
        for data in ({"redirect_uris": ["http://example.com"]}, {"redirect_uris": ["https://example.com/#fragment"]},
                     {"redirect_uris": [REDIRECT], "grant_types": [{}]}, []):
            response = await self.client.post("/oauth/register", json=data)
            self.assertEqual(response.status_code, 400, response.text)
        response = await self.client.post("/oauth/token", content="client_id=a&client_id=b", headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(response.status_code, 400)
        response = await self.client.post("/oauth/register", content=b"x" * 16385, headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 413)

    async def test_persistence_expiry_password_reset_and_hashed_storage(self):
        await self.login()
        client = await self.register()
        code = await self.code(client)
        pair = (await self.exchange(client, code)).json()
        other = IdentityStore(self.path, RESOURCE)
        try:
            self.assertTrue(other.access_valid(pair["access_token"]))
            other.resource = "https://changed.example/mcp"
            self.assertFalse(other.access_valid(pair["access_token"]))
            other.resource = RESOURCE
            other.db.execute("UPDATE tokens SET expires=0 WHERE hash=?", (digest(pair["access_token"]),))
            self.assertFalse(other.access_valid(pair["access_token"]))
            other.set_password(password_hash(PASSWORD + "changed"))
            self.assertFalse(self.store.session_valid(self.client.cookies.get(COOKIE)))
            with self.assertRaises(AuthError):
                other.exchange(client["client_id"], {"grant_type": "refresh_token", "refresh_token": pair["refresh_token"]})
        finally:
            other.close()
        raw = self.path.read_bytes()
        for secret in (PASSWORD, pair["access_token"], pair["refresh_token"], code, self.client.cookies.get(COOKIE)):
            self.assertNotIn(secret.encode(), raw)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    async def test_setup_cookie_survives_reload_and_is_invalidated(self):
        self.assertFalse((await self.client.get("/auth/session")).json()["setup_ready"])
        response = await self.browser("/auth/setup-session", {"setup_token": self.setup_token})
        self.assertEqual(response.status_code, 200)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertTrue((await self.client.get("/auth/session")).json()["setup_ready"])
        response = await self.browser("/auth/setup", {"username": "admin", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertFalse((await self.client.get("/auth/session")).json()["setup_ready"])
        self.assertEqual((await self.browser("/auth/setup-session", {"setup_token": self.setup_token})).status_code, 401)

    async def test_rate_limit_does_not_leak_credentials(self):
        for _ in range(10):
            response = await self.browser("/auth/login", {"username": "admin", "password": PASSWORD})
            self.assertEqual(response.status_code, 401)
        response = await self.browser("/auth/login", {"username": "admin", "password": PASSWORD})
        self.assertEqual(response.status_code, 429)
        self.assertNotIn(PASSWORD, response.text)


class SetupTests(unittest.TestCase):
    def test_auto_setup_link_expiry_rotation_and_single_use(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.sqlite3"
            store = IdentityStore(path, RESOURCE)
            self.addCleanup(store.close)
            first = store.setup_link()
            self.assertEqual(store.setup_link(), first)
            self.assertEqual(store.setup_path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(first.split("#setup=")[1].encode(), path.read_bytes())
            second = store.setup_link(renew=True)
            self.assertNotEqual(first, second)
            encoded = password_hash(PASSWORD)
            with self.assertRaises(AuthError):
                store.set_password(encoded, initial=True, setup_token=first.split("#setup=")[1])
            store.db.execute("UPDATE setup SET expires=0")
            with self.assertRaises(AuthError):
                store.set_password(encoded, initial=True, setup_token=second.split("#setup=")[1])
            third = store.setup_link()
            store.set_password(encoded, username="owner", initial=True, setup_token=third.split("#setup=")[1])
            self.assertEqual(store.owner_username(), "owner")
            self.assertFalse(store.setup_path.exists())
            with self.assertRaises(AuthError):
                store.setup_link()
            with self.assertRaises(AuthError):
                store.set_password(encoded, initial=True, setup_token=third.split("#setup=")[1])

    def test_upgrade_existing_password_database_keeps_admin_username(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE owner(id INTEGER PRIMARY KEY, password TEXT)")
                db.execute("INSERT INTO owner VALUES(1,?)", (password_hash(PASSWORD),))
            store = IdentityStore(path, RESOURCE)
            try:
                self.assertEqual(store.owner_username(), "admin")
                self.assertIsNotNone(store.owner_password())
            finally:
                store.close()
