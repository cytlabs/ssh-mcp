"""Static bearer auth for header-capable clients; not an OAuth authorization server."""

import hmac


class BearerAuth:
    def __init__(self, app, token: str, max_body: int = 2_097_152):
        self.app = app
        self.token = token.encode("ascii")
        self.max_body = max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        values = [value for key, value in headers if key.lower() == b"authorization"]
        supplied = values[0].split(b" ", 1) if len(values) == 1 else []
        valid = (len(supplied) == 2 and supplied[0].lower() == b"bearer"
                 and hmac.compare_digest(supplied[1], self.token))
        if not valid:
            return await self.reject(send, 401, b"Unauthorized", [(b"www-authenticate", b"Bearer")])
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

        await self.app(scope, replay, send)

    @staticmethod
    async def reject(send, status, body, headers=None):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain"),
                                (b"cache-control", b"no-store"), *(headers or [])]})
        await send({"type": "http.response.body", "body": body})
