"""单操作者身份存储：密码、浏览器会话和 OAuth 授权，秘密只存哈希。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SCOPE = "ssh:access"
ACCESS_SECONDS = 900
GRANT_SECONDS = 30 * 86400
COOKIE_SECONDS = 8 * 3600


class AuthError(ValueError):
    def __init__(self, code="invalid_request", status=400):
        self.code, self.status = code, status
        super().__init__(code)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str) -> str:
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise AuthError("password_length")
    salt = secrets.token_bytes(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, maxmem=64 << 20)
    return f"scrypt${salt.hex()}${value.hex()}"


def password_matches(password: str, encoded: str) -> bool:
    if not isinstance(password, str) or len(password) > 256:
        return False
    _, salt, expected = encoded.split("$")
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1,
                           maxmem=64 << 20)
    return hmac.compare_digest(value.hex(), expected)


def redirect_allowed(value: str) -> bool:
    try:
        if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\s\\*]", value):
            return False
        url = urlsplit(value)
        return bool(url.hostname and not url.username and not url.password and not url.fragment
                    and (url.port is None or 1 <= url.port <= 65535)
                    and not ({k for k, _ in parse_qsl(url.query)} & {"code", "state", "error", "iss"})
                    and (url.scheme == "https" or (url.scheme == "http" and
                         url.hostname in ("127.0.0.1", "::1", "localhost"))))
    except ValueError:
        return False


def redirect_matches(registered: str, requested: str) -> bool:
    if not redirect_allowed(requested):
        return False
    if registered == requested:
        return True
    a, b = urlsplit(registered), urlsplit(requested)
    # RFC 8252 只允许回环 HTTP 回调改变端口，主机、路径和查询仍必须一致。
    return (a.scheme == b.scheme == "http" and a.hostname == b.hostname
            and a.hostname in ("127.0.0.1", "::1", "localhost")
            and a.path == b.path and a.query == b.query)


def callback(uri: str, **params) -> str:
    url = urlsplit(uri)
    query = parse_qsl(url.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value is not None)
    return urlunsplit(url._replace(query=urlencode(query)))


def auth_database(inventory: Path | None) -> Path | None:
    return inventory.with_name(inventory.stem + ".auth.sqlite3") if inventory else None


class IdentityStore:
    def __init__(self, filename: Path | None, resource: str):
        self.resource = resource
        self.setup_path = filename.with_suffix(".setup-link") if filename else None
        self.lock = threading.RLock()
        if filename:
            filename.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(filename, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
            os.chmod(filename, 0o600)
        self.db = sqlite3.connect(str(filename) if filename else ":memory:",
                                  isolation_level=None, check_same_thread=False, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS owner(id INTEGER PRIMARY KEY CHECK(id=1), password TEXT);
            CREATE TABLE IF NOT EXISTS setup(id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT, expires REAL);
            CREATE TABLE IF NOT EXISTS browser_sessions(hash TEXT PRIMARY KEY, expires REAL);
            CREATE TABLE IF NOT EXISTS clients(
                id TEXT PRIMARY KEY, name TEXT, redirects TEXT, method TEXT,
                secret_hash TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS pending(
                hash TEXT PRIMARY KEY, client_id TEXT, redirect TEXT, challenge TEXT,
                state TEXT, expires REAL, session_hash TEXT);
            CREATE TABLE IF NOT EXISTS grants(
                id TEXT PRIMARY KEY, client_id TEXT, created REAL, resource TEXT, revoked INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS codes(
                hash TEXT PRIMARY KEY, client_id TEXT, redirect TEXT, challenge TEXT,
                grant_id TEXT, expires REAL, used INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS tokens(
                hash TEXT PRIMARY KEY, kind TEXT, grant_id TEXT, client_id TEXT,
                expires REAL, used INTEGER DEFAULT 0);
        """)
        if "username" not in {row[1] for row in self.db.execute("PRAGMA table_info(owner)")}:
            self.db.execute("ALTER TABLE owner ADD COLUMN username TEXT NOT NULL DEFAULT 'admin'")

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def close(self):
        self.db.close()

    def prune(self):
        now = time.time()
        self.db.execute("DELETE FROM browser_sessions WHERE expires<?", (now,))
        self.db.execute("DELETE FROM pending WHERE expires<?", (now,))
        self.db.execute("DELETE FROM codes WHERE expires<?", (now - 86400,))
        self.db.execute("DELETE FROM tokens WHERE expires<?", (now - 86400,))

    def owner_password(self):
        with self.lock:
            row = self.db.execute("SELECT password FROM owner WHERE id=1").fetchone()
            return row[0] if row else None

    def owner_username(self):
        with self.lock:
            row = self.db.execute("SELECT username FROM owner WHERE id=1").fetchone()
            return row[0] if row else None

    def setup_link(self, *, renew=False):
        """仅供服务器管理员读取；不会通过公开 HTTP 返回初始化秘密。"""
        with self.transaction():
            if self.owner_password():
                raise AuthError("already_initialized", 409)
            if self.setup_path and self.setup_path.exists() and not renew:
                saved = self.setup_path.read_text().strip()
                raw = saved.rsplit("#setup=", 1)[-1]
                if self.db.execute("SELECT 1 FROM setup WHERE hash=? AND expires>?",
                                   (digest(raw), time.time())).fetchone():
                    return saved
            raw = secrets.token_urlsafe(32)
            self.db.execute("INSERT OR REPLACE INTO setup VALUES(1,?,?)", (digest(raw), time.time() + 3600))
            link = self.resource.removesuffix("/mcp") + "/console#setup=" + raw
            if self.setup_path:
                temporary = self.setup_path.with_name(self.setup_path.name + "." + secrets.token_hex(6))
                fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w") as output:
                    output.write(link + "\n")
                os.replace(temporary, self.setup_path)
            return link

    def setup_remaining(self, raw):
        with self.lock:
            if not raw or self.owner_password():
                return 0
            row = self.db.execute("SELECT expires FROM setup WHERE hash=?", (digest(raw),)).fetchone()
            return max(0, int(row[0] - time.time())) if row else 0

    def set_password(self, encoded: str, *, username="admin", initial=False, setup_token=""):
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.@+-]{1,128}", username):
            raise AuthError("invalid_username")
        with self.transaction():
            if initial:
                if self.owner_password():
                    raise AuthError("already_initialized", 409)
                if not isinstance(setup_token, str) or not self.db.execute(
                    "SELECT 1 FROM setup WHERE hash=? AND expires>?", (digest(setup_token), time.time())
                ).fetchone():
                    raise AuthError("setup_link_invalid", 401)
            self.db.execute("INSERT OR REPLACE INTO owner(id,password,username) VALUES(1,?,?)", (encoded, username))
            self.db.execute("DELETE FROM setup")
            self.db.execute("DELETE FROM browser_sessions")
            self.db.execute("DELETE FROM pending")
            self.db.execute("UPDATE grants SET revoked=1")
        if self.setup_path:
            self.setup_path.unlink(missing_ok=True)

    def browser_session(self):
        raw = secrets.token_urlsafe(32)
        with self.transaction():
            self.prune()
            if self.db.execute("SELECT count(*) FROM browser_sessions").fetchone()[0] >= 128:
                raise AuthError("too_many_sessions", 429)
            self.db.execute("INSERT INTO browser_sessions VALUES(?,?)",
                            (digest(raw), time.time() + COOKIE_SECONDS))
        return raw

    def session_valid(self, raw):
        with self.lock:
            return bool(raw and self.db.execute(
                "SELECT 1 FROM browser_sessions WHERE hash=? AND expires>?",
                (digest(raw), time.time())).fetchone())

    def logout(self, raw):
        with self.lock:
            self.db.execute("DELETE FROM browser_sessions WHERE hash=?", (digest(raw),))

    def client(self, cid):
        with self.lock:
            return self.db.execute("SELECT * FROM clients WHERE id=?", (cid,)).fetchone()

    def register(self, data):
        redirects = data.get("redirect_uris")
        method = data.get("token_endpoint_auth_method", "none")
        name = data.get("client_name", "未命名客户端")
        if (not isinstance(redirects, list) or not 1 <= len(redirects) <= 10
                or not all(redirect_allowed(v) for v in redirects)
                or method not in ("none", "client_secret_post", "client_secret_basic")
                or not isinstance(name, str) or not 1 <= len(name) <= 120
                or data.get("response_types", ["code"]) != ["code"]
                or not isinstance(data.get("grant_types", []), list)
                or any(v not in ("authorization_code", "refresh_token")
                       for v in data.get("grant_types", ["authorization_code", "refresh_token"]))
                or data.get("scope", SCOPE) != SCOPE):
            raise AuthError("invalid_client_metadata")
        cid, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        with self.transaction():
            if self.db.execute("SELECT count(*) FROM clients").fetchone()[0] >= 1000:
                raise AuthError("registration_limit", 429)
            self.db.execute("INSERT INTO clients VALUES(?,?,?,?,?,?)", (
                cid, name, json.dumps(redirects), method,
                digest(secret) if method != "none" else None, time.time()))
        result = {"client_id": cid, "client_name": name, "redirect_uris": redirects,
                  "token_endpoint_auth_method": method, "scope": SCOPE,
                  "grant_types": ["authorization_code", "refresh_token"],
                  "response_types": ["code"], "client_id_issued_at": int(time.time())}
        if method != "none":
            result.update(client_secret=secret, client_secret_expires_at=0)
        return result

    def authorize(self, params):
        client = self.client(params.get("client_id", ""))
        redirect = params.get("redirect_uri", "")
        if not client or not any(redirect_matches(r, redirect)
                                 for r in json.loads(client["redirects"])):
            raise AuthError("invalid_redirect_uri")
        if (params.get("response_type") != "code" or params.get("code_challenge_method") != "S256"
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.get("code_challenge", ""))):
            raise AuthError("invalid_request")
        if params.get("resource") != self.resource:
            raise AuthError("invalid_target")
        if params.get("scope", SCOPE) != SCOPE:
            raise AuthError("invalid_scope")
        state = params.get("state")
        if state is not None and len(state) > 2048:
            raise AuthError()
        handle = secrets.token_urlsafe(32)
        with self.transaction():
            self.prune()
            if self.db.execute("SELECT count(*) FROM pending").fetchone()[0] >= 256:
                raise AuthError("too_many_requests", 429)
            self.db.execute("INSERT INTO pending VALUES(?,?,?,?,?,?,NULL)", (
                digest(handle), client["id"], redirect, params["code_challenge"], state,
                time.time() + 600))
        return handle

    def pending(self, handle, browser, *, bind=False):
        if not self.session_valid(browser):
            raise AuthError("login_required", 401)
        row = self.db.execute("SELECT * FROM pending WHERE hash=? AND expires>?",
                              (digest(handle), time.time())).fetchone()
        if not row or (row["session_hash"] and row["session_hash"] != digest(browser)):
            raise AuthError("authorization_expired")
        if bind and not row["session_hash"]:
            self.db.execute("UPDATE pending SET session_hash=? WHERE hash=?",
                            (digest(browser), digest(handle)))
        return row

    def consent_info(self, handle, browser):
        with self.transaction():
            row = self.pending(handle, browser, bind=True)
            client = self.client(row["client_id"])
            return {"client_name": client["name"], "redirect_uri": row["redirect"],
                    "resource": self.resource, "scope": SCOPE}

    def consent(self, handle, browser, approve, issuer):
        with self.transaction():
            row = self.pending(handle, browser)
            if row["session_hash"] != digest(browser):
                raise AuthError("consent_not_viewed")
            self.db.execute("DELETE FROM pending WHERE hash=?", (digest(handle),))
            params = {"state": row["state"], "iss": issuer}
            if approve:
                grant, code = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
                self.db.execute("INSERT INTO grants VALUES(?,?,?,?,0)",
                                (grant, row["client_id"], time.time(), self.resource))
                self.db.execute("INSERT INTO codes VALUES(?,?,?,?,?,?,0)", (
                    digest(code), row["client_id"], row["redirect"], row["challenge"],
                    grant, time.time() + 120))
                params["code"] = code
            else:
                params["error"] = "access_denied"
            return callback(row["redirect"], **params)

    def issue(self, grant_id, cid):
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        grant = self.db.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()
        self.db.executemany("INSERT INTO tokens VALUES(?,?,?,?,?,0)", [
            (digest(access), "access", grant_id, cid, time.time() + ACCESS_SECONDS),
            (digest(refresh), "refresh", grant_id, cid, grant["created"] + GRANT_SECONDS),
        ])
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer",
                "expires_in": ACCESS_SECONDS, "scope": SCOPE}

    def exchange(self, cid, data):
        if data.get("resource", self.resource) != self.resource:
            raise AuthError("invalid_target")
        result = None
        with self.transaction():
            if data.get("grant_type") == "authorization_code":
                row = self.db.execute("SELECT * FROM codes WHERE hash=? AND client_id=?",
                                      (digest(data.get("code", "")), cid)).fetchone()
                verifier = data.get("code_verifier", "")
                if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
                    raise AuthError("invalid_grant")
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                if (not row or row["expires"] <= time.time()
                        or data.get("redirect_uri") != row["redirect"]
                        or not hmac.compare_digest(challenge.decode().rstrip("="), row["challenge"])):
                    raise AuthError("invalid_grant")
                table = "codes"
            elif data.get("grant_type") == "refresh_token":
                row = self.db.execute("SELECT * FROM tokens WHERE hash=? AND client_id=? AND kind='refresh'",
                                      (digest(data.get("refresh_token", "")), cid)).fetchone()
                if not row or row["expires"] <= time.time():
                    raise AuthError("invalid_grant")
                if data.get("scope", SCOPE) != SCOPE:
                    raise AuthError("invalid_scope")
                table = "tokens"
            else:
                raise AuthError("unsupported_grant_type")
            grant = self.db.execute("SELECT * FROM grants WHERE id=?", (row["grant_id"],)).fetchone()
            if (not grant or grant["revoked"] or grant["resource"] != self.resource
                    or grant["created"] + GRANT_SECONDS <= time.time()):
                raise AuthError("invalid_grant")
            if row["used"]:
                # 提交撤销后再报错，不能因异常回滚撤销。
                self.db.execute("UPDATE grants SET revoked=1 WHERE id=?", (row["grant_id"],))
            else:
                self.db.execute(f"UPDATE {table} SET used=1 WHERE hash=?", (row["hash"],))
                result = self.issue(row["grant_id"], cid)
        if result is None:
            raise AuthError("invalid_grant")
        return result

    def access_valid(self, raw):
        with self.lock:
            return bool(self.db.execute("""SELECT 1 FROM tokens t JOIN grants g ON g.id=t.grant_id
                WHERE t.hash=? AND t.kind='access' AND t.expires>? AND g.revoked=0 AND g.resource=? AND g.created>?""",
                                        (digest(raw), time.time(), self.resource,
                                         time.time() - GRANT_SECONDS)).fetchone())

    def revoke_token(self, raw, cid):
        with self.transaction():
            self.db.execute("""UPDATE grants SET revoked=1 WHERE id IN
                (SELECT grant_id FROM tokens WHERE hash=? AND client_id=?)""", (digest(raw), cid))

    def grants(self):
        with self.lock:
            return [dict(row) for row in self.db.execute("""SELECT g.id,c.name AS client_name,
                g.created,g.revoked FROM grants g JOIN clients c ON c.id=g.client_id
                WHERE g.created>? ORDER BY g.created DESC LIMIT 200""", (time.time() - GRANT_SECONDS,))]

    def revoke_grant(self, grant):
        with self.lock:
            self.db.execute("UPDATE grants SET revoked=1 WHERE id=?", (grant,))
