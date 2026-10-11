"""单操作者 OAuth 授权服务与浏览器登录；不向客户端转交 SSH 凭据。"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import time
from collections import defaultdict, deque
from http.cookies import CookieError, SimpleCookie
from urllib.parse import parse_qsl, unquote_plus

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from .auth import BearerAuth
from .identity import COOKIE_SECONDS, SCOPE, AuthError, digest, password_hash, password_matches

COOKIE = "__Host-ssh-mcp-session"
SETUP_COOKIE = "__Host-ssh-mcp-setup"
PUBLIC = {"/oauth/token", "/oauth/register", "/oauth/revoke",
          "/.well-known/oauth-authorization-server",
          "/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"}


def pairs(raw):
    result = {}
    for key, value in parse_qsl(raw, keep_blank_values=True, max_num_fields=30):
        if key in result:
            raise AuthError()
        result[key] = value
    return result


class OAuth:
    def __init__(self, console, store):
        self.app, self.store = console, store
        self.origin = store.resource.removesuffix("/mcp")
        self.limits = defaultdict(deque)
        self.hashers = asyncio.Semaphore(2)
        console.admin_app = BearerAuth(console.api, max_body=65536, authorize=self.browser_authorized)

    def cookie(self, scope, name=COOKIE):
        values = [v for k, v in scope.get("headers", []) if k.lower() == b"cookie"]
        if len(values) != 1:
            return ""
        try:
            jar = SimpleCookie()
            jar.load(values[0].decode("latin1"))
            return jar[name].value if name in jar else ""
        except CookieError:
            return ""

    def same_origin(self, scope):
        origins = [v for k, v in scope.get("headers", []) if k.lower() == b"origin"]
        return origins == [self.origin.encode()]

    def browser_authorized(self, scope):
        raw = self.cookie(scope)
        if not self.store.session_valid(raw):
            return False
        if scope["method"] in ("GET", "HEAD"):
            return True
        csrf = [v for k, v in scope.get("headers", []) if k.lower() == b"x-csrf-token"]
        return self.same_origin(scope) and csrf == [digest(raw + ":csrf").encode()]

    def rate(self, bucket, maximum, period=60):
        now = time.monotonic()
        queue = self.limits[bucket]
        while queue and queue[0] <= now - period:
            queue.popleft()
        if len(queue) >= maximum:
            raise AuthError("too_many_requests", 429)
        queue.append(now)

    async def body(self, request, *, form=False):
        expected = "application/x-www-form-urlencoded" if form else "application/json"
        if request.headers.get("content-type", "").split(";", 1)[0].strip() != expected:
            raise AuthError("invalid_request", 415)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 16384:
                raise AuthError("request_too_large", 413)
        if form:
            return pairs(raw.decode())
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise AuthError()
        return value

    def client_auth(self, request, data):
        headers = request.headers.getlist("authorization")
        cid, secret, method = data.get("client_id", ""), data.get("client_secret"), "none"
        if len(headers) > 1:
            raise AuthError("invalid_client", 401)
        if headers:
            if secret is not None:
                raise AuthError("invalid_client", 401)
            try:
                scheme, value = headers[0].split(" ", 1)
                if scheme.lower() != "basic":
                    raise ValueError()
                basic_id, basic_secret = base64.b64decode(value, validate=True).decode().split(":", 1)
                basic_id, secret = unquote_plus(basic_id), unquote_plus(basic_secret)
                if cid and cid != basic_id:
                    raise ValueError()
                cid, method = basic_id, "client_secret_basic"
            except (ValueError, UnicodeError):
                raise AuthError("invalid_client", 401) from None
        elif secret is not None:
            method = "client_secret_post"
        client = self.store.client(cid)
        if (not client or client["method"] != method
                or (method != "none" and not hmac.compare_digest(digest(secret), client["secret_hash"]))):
            raise AuthError("invalid_client", 401)
        return cid

    def session_response(self, raw):
        response = JSONResponse({"authenticated": True, "csrf": digest(raw + ":csrf"), "mode": "oauth"})
        response.set_cookie(COOKIE, raw, max_age=COOKIE_SECONDS, httponly=True, secure=True,
                            samesite="lax", path="/")
        return response

    async def dispatch(self, request):
        path, method, scope = request.url.path, request.method, request.scope
        if method == "GET" and path == "/.well-known/oauth-authorization-server":
            return JSONResponse({
                "issuer": self.origin, "authorization_endpoint": self.origin + "/oauth/authorize",
                "token_endpoint": self.origin + "/oauth/token",
                "registration_endpoint": self.origin + "/oauth/register",
                "revocation_endpoint": self.origin + "/oauth/revoke",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"], "scopes_supported": [SCOPE],
                "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
                "revocation_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
                "authorization_response_iss_parameter_supported": True,
            })
        if method == "GET" and path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
            return JSONResponse({"resource": self.store.resource, "authorization_servers": [self.origin],
                                 "scopes_supported": [SCOPE], "bearer_methods_supported": ["header"]})
        if path in PUBLIC and method == "OPTIONS":
            return JSONResponse({})
        if path == "/oauth/register" and method == "POST":
            self.rate("register", 10)
            return JSONResponse(self.store.register(await self.body(request)), status_code=201)
        if path == "/oauth/authorize" and method == "GET":
            self.rate("authorize", 60)
            handle = self.store.authorize(pairs(scope.get("query_string", b"").decode()))
            return RedirectResponse("/console?authorize=" + handle, status_code=302)
        if path in ("/oauth/token", "/oauth/revoke") and method == "POST":
            self.rate("token", 120)
            data = await self.body(request, form=True)
            cid = self.client_auth(request, data)
            if path.endswith("/revoke"):
                if not data.get("token"):
                    raise AuthError()
                self.store.revoke_token(data["token"], cid)
                return JSONResponse({})
            return JSONResponse(self.store.exchange(cid, data))
        if path == "/auth/session" and method == "GET":
            raw = self.cookie(scope)
            authenticated = self.store.session_valid(raw)
            return JSONResponse({"mode": "oauth", "initialized": bool(self.store.owner_password()),
                                 "authenticated": authenticated,
                                 "setup_ready": bool(self.store.setup_remaining(self.cookie(scope, SETUP_COOKIE))),
                                 "csrf": digest(raw + ":csrf") if authenticated else None})
        if path == "/auth/setup-session" and method == "POST":
            if not self.same_origin(scope):
                raise AuthError("untrusted_origin", 403)
            self.rate("setup-session", 20)
            data = await self.body(request)
            raw = data.get("setup_token", "")
            remaining = self.store.setup_remaining(raw) if isinstance(raw, str) else 0
            if not remaining:
                raise AuthError("setup_link_invalid", 401)
            response = JSONResponse({"setup_ready": True})
            response.set_cookie(SETUP_COOKIE, raw, max_age=remaining, httponly=True,
                                secure=True, samesite="lax", path="/")
            return response
        if path in ("/auth/setup", "/auth/login") and method == "POST":
            if not self.same_origin(scope):
                raise AuthError("untrusted_origin", 403)
            self.rate("login", 10)
            data = await self.body(request)
            password = data.get("password", "")
            if not isinstance(password, str) or len(password) > 256:
                raise AuthError()
            async with self.hashers:
                if path.endswith("/setup"):
                    if self.store.owner_password():
                        raise AuthError("already_initialized", 409)
                    encoded = await asyncio.to_thread(password_hash, password)
                    self.store.set_password(encoded, initial=True, username=data.get("username", ""),
                                            setup_token=self.cookie(scope, SETUP_COOKIE))
                else:
                    encoded = self.store.owner_password()
                    if not encoded or not await asyncio.to_thread(password_matches, password, encoded):
                        raise AuthError("invalid_credentials", 401)
                    if (self.store.owner_password() != encoded
                            or data.get("username") != self.store.owner_username()):
                        raise AuthError("invalid_credentials", 401)
            response = self.session_response(self.store.browser_session())
            response.delete_cookie(SETUP_COOKIE, secure=True, httponly=True, samesite="lax")
            return response
        if path.startswith("/auth/"):
            if not self.browser_authorized(scope):
                raise AuthError("login_required", 401)
            if path == "/auth/grants" and method == "GET":
                return JSONResponse({"grants": self.store.grants()})
            if path == "/auth/consent" and method == "GET":
                params = pairs(scope.get("query_string", b"").decode())
                return JSONResponse(self.store.consent_info(params.get("request", ""), self.cookie(scope)))
            if method == "POST":
                data = await self.body(request)
                if path == "/auth/logout":
                    self.store.logout(self.cookie(scope))
                    response = JSONResponse({"ok": True})
                    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="lax")
                    return response
                if path == "/auth/consent":
                    if type(data.get("approve")) is not bool or not isinstance(data.get("request"), str):
                        raise AuthError()
                    return JSONResponse({"redirect": self.store.consent(
                        data["request"], self.cookie(scope), data["approve"], self.origin)})
                if path == "/auth/revoke":
                    if not isinstance(data.get("grant_id"), str):
                        raise AuthError()
                    self.store.revoke_grant(data["grant_id"])
                    return JSONResponse({"ok": True})
        raise AuthError("not_found", 404)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(("/oauth/", "/auth/", "/.well-known/")):
            return await self.app(scope, receive, send)
        # 公共 OAuth 端点允许跨源非 Cookie 请求；浏览器管理接口仍限制来源。
        public = scope["path"] in PUBLIC
        checked_scope = {**scope, "headers": [(k, v) for k, v in scope["headers"]
                                              if not (public and k.lower() == b"origin")]}
        if not self.app.trusted(checked_scope):
            response = JSONResponse({"error": "untrusted_origin"}, status_code=403)
        else:
            try:
                response = await self.dispatch(Request(scope, receive))
            except AuthError as error:
                response = JSONResponse({"error": error.code}, status_code=error.status)
            except (ValueError, TypeError, UnicodeError):
                response = JSONResponse({"error": "invalid_request"}, status_code=400)
        response.headers.update({"Cache-Control": "no-store", "Pragma": "no-cache",
                                 "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                                 "X-Frame-Options": "DENY"})
        if public:
            response.headers.update({"Access-Control-Allow-Origin": "*",
                                     "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                                     "Access-Control-Allow-Headers": "Authorization, Content-Type"})
        await response(scope, receive, send)
