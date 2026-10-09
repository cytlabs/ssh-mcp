"""Disposable browser-test fixture: real console/SQLite, simulated SSH only.

Never load user configuration or bind a public interface. Not a production server.
"""

import argparse
import asyncio
import json
import sys
import tempfile
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

from ssh_mcp.config import parse_config
from ssh_mcp.console import Console
from ssh_mcp.registry import Registry

ADMIN_TOKEN = "browser-fixture-only-not-a-real-secret-" + "x" * 32


class FixtureManager:
    def __init__(self, config):
        self.config, self.sessions, self.output = config, {}, {}

    def list_sessions(self):
        return list(self.sessions.values())

    async def connect(self, server):
        async def wait_closed():
            pass
        await asyncio.sleep(0.05)
        return SimpleNamespace(close=lambda: None, wait_closed=wait_closed)

    async def start(self, server_id, pty=False):
        self.config.server(server_id)
        sid = uuid.uuid4().hex
        self.sessions[sid] = {"session_id": sid, "server_id": server_id, "status": "running", "kind": "shell"}
        self.output[sid] = "[浏览器测试夹具 · SSH 输出为模拟数据]\n"
        return SimpleNamespace(id=sid, server_id=server_id)

    async def send(self, sid, data):
        self.output[sid] += "$ " + data + "fixture: input received\n"
        return {"accepted_chars": len(data)}

    async def read(self, sid, stdout_cursor=0, stderr_cursor=0, max_chars=32768):
        text = self.output[sid]
        return {**self.sessions[sid], "stdout": {"text": text[stdout_cursor:], "cursor": len(text),
                "dropped_chars": 0, "has_more": False},
                "stderr": {"text": "", "cursor": 0, "dropped_chars": 0, "has_more": False}}

    async def close(self, sid):
        self.sessions.pop(sid, None)
        return {"status": "closed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--stdio", action="store_true", help="DOM test bridge without network listeners")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ssh-mcp-ui-") as temp:
        config = parse_config({"servers": [
            {"id": "staging", "host": "192.0.2.10", "username": "ops", "description": "产品测试环境",
             "known_hosts": "/etc/ssh-mcp/known_hosts", "private_key": "/etc/ssh-mcp/keys/staging"},
            {"id": "production", "host": "192.0.2.20", "username": "deploy", "description": "网站与应用服务",
             "known_hosts": "/etc/ssh-mcp/known_hosts", "private_key": "/etc/ssh-mcp/keys/production"},
            {"id": "dev-lab", "host": "192.0.2.30", "username": "developer", "description": "实验与开发环境",
             "known_hosts": "/etc/ssh-mcp/known_hosts", "password_env": "LAB_SSH_PASSWORD"},
        ]}, Path(temp))
        registry = Registry(config, Path(temp) / "fixture.sqlite3")
        manager = FixtureManager(config)

        async def fallback(scope, receive, send):
            await Console.respond(send, 404, {"error": "Fixture has no MCP transport"})

        app = Console(fallback, manager, registry, ADMIN_TOKEN)
        loop = asyncio.new_event_loop()

        if args.stdio:
            try:
                for line in sys.stdin:
                    request = json.loads(line)
                    messages = []

                    async def receive(payload=request.get("body", "").encode()):
                        return {"type": "http.request", "body": payload}

                    async def send(message, collected=messages):
                        collected.append(message)

                    scope = {"type": "http", "scheme": "http", "path": request["path"],
                             "method": request.get("method", "GET"),
                             "headers": [(b"host", b"localhost:8765"),
                                         *[(k.lower().encode(), v.encode()) for k, v in request.get("headers", {}).items()]]}
                    loop.run_until_complete(app(scope, receive, send))
                    body = b"".join(m.get("body", b"") for m in messages).decode()
                    print(json.dumps({"id": request["id"], "status": messages[0]["status"], "body": body}), flush=True)
            finally:
                loop.close()
                registry.close()
            return

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def handle_request(self):
                raw = self.rfile.read(min(int(self.headers.get("Content-Length", "0")), 70000))
                scope = {"type": "http", "scheme": "http", "path": self.path.split("?")[0],
                         "method": self.command, "headers": [(k.lower().encode(), v.encode())
                                                             for k, v in self.headers.items()]}
                messages = []

                async def receive():
                    return {"type": "http.request", "body": raw}

                async def send(message):
                    messages.append(message)

                loop.run_until_complete(app(scope, receive, send))
                self.send_response(messages[0]["status"])
                for key, value in messages[0]["headers"]:
                    self.send_header(key.decode(), value.decode())
                self.end_headers()
                self.wfile.write(b"".join(m.get("body", b"") for m in messages))

            do_GET = do_POST = do_PUT = do_DELETE = handle_request

        http = HTTPServer(("127.0.0.1", args.port), Handler)
        print(json.dumps({"preview": f"http://127.0.0.1:{args.port}/console", "mode": "test fixture; SSH simulated"}), flush=True)
        try:
            http.serve_forever()
        finally:
            http.server_close()
            loop.close()
            registry.close()


if __name__ == "__main__":
    main()
