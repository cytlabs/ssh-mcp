"""HTTP 认证与请求体大小限制。"""

import hmac
from contextvars import ContextVar

operator_name = ContextVar("operator_name", default=None)
operator_nickname = ContextVar("operator_nickname", default="")


class BearerAuth:
    def __init__(self, app, token: str = "", max_body: int = 2_097_152, *,
                 validator=None, authorize=None, challenge=b"Bearer", oauth_username=None):
        self.oauth_username = oauth_username
        self.app = app
        self.token = token.encode("ascii")
        self.max_body = max_body
        self.validator, self.authorize, self.challenge = validator, authorize, challenge

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        values = [value for key, value in headers if key.lower() == b"authorization"]
        supplied = values[0].split(b" ", 1) if len(values) == 1 else []
        valid = (len(supplied) == 2 and supplied[0].lower() == b"bearer"
                 and len(supplied[1]) <= 4096
                 and ((bool(self.token) and hmac.compare_digest(supplied[1], self.token))
                      or (self.validator and supplied[1].isascii()
                          and self.validator(supplied[1].decode("ascii")))))
        if self.authorize:
            valid = self.authorize(scope)
        if not valid:
            return await self.reject(send, 401, b"Unauthorized", [(b"www-authenticate", self.challenge)])
        # Bound actual bytes, including chunked bodies. Never trust Content-Length alone.
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > self.max_body:
                return await self.reject(send, 413, b"Request too large")
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        shared = bool(self.token and len(supplied) == 2 and hmac.compare_digest(supplied[1], self.token))
        name, nickname = ("共享 MCP Token", "") if shared else (
            self.oauth_username() if self.oauth_username else (None, ""))
        marker = operator_name.set(name)
        nick_marker = operator_nickname.set(nickname)
        try:
            await self.app(scope, replay, send)
        finally:
            operator_name.reset(marker)
            operator_nickname.reset(nick_marker)

    @staticmethod
    async def reject(send, status, body, headers=None):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain"),
                                (b"cache-control", b"no-store"), *(headers or [])]})
        await send({"type": "http.response.body", "body": body})
