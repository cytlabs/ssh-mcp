import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ssh_mcp.auth import BearerAuth
from ssh_mcp.buffer import OutputBuffer
from ssh_mcp.config import ConfigError, load_config


class BufferTests(unittest.TestCase):
    def test_replay_overflow_and_cursors(self):
        buffer = OutputBuffer(6)
        buffer.append("你好abc")
        self.assertEqual(buffer.read(0, 2)["text"], "你好")
        self.assertEqual(buffer.read(0, 2)["text"], "你好")
        buffer.append("defgh")
        self.assertEqual(buffer.read(0, 3), {
            "text": "cde", "cursor": 7, "dropped_chars": 4, "has_more": True,
        })
        self.assertEqual(buffer.read(7, 20)["text"], "fgh")
        buffer.append("x" * 100)
        self.assertEqual(len(buffer.read(0, 1000)["text"]), 6)
        self.assertEqual(len(buffer.parts), 1)

    def test_invalid_cursor(self):
        for cursor in (-1, 1, True):
            with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                OutputBuffer(10).read(cursor, 5)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "config.json"
        self.raw = {"servers": [{"id": "test", "host": "example.invalid", "username": "ops",
                                 "known_hosts": "known_hosts", "password_env": "TEST_SSH_PASS"}]}

    def load(self):
        self.path.write_text(json.dumps(self.raw))
        return load_config(self.path)

    def test_public_metadata_and_repr_exclude_credentials(self):
        with patch.dict(os.environ, {"TEST_SSH_PASS": "never-return-this"}):
            server = self.load().server("test")
            self.assertEqual(server.credentials()["password"], "never-return-this")
            for result in (json.dumps(server.public()), repr(server)):
                self.assertNotIn("never-return-this", result)
                self.assertNotIn("TEST_SSH_PASS", result)
                self.assertNotIn("known_hosts", result)

    def test_paths_are_config_relative(self):
        self.assertEqual(self.load().servers[0].known_hosts, self.path.parent / "known_hosts")

    def test_duplicate_servers_rejected(self):
        self.raw["servers"] *= 2
        with self.assertRaises(ConfigError):
            self.load()

    def test_unsafe_http_origins_rejected(self):
        for url in ("http://example.com", "https://u:p@example.com", "https://example.com/mcp",
                    "https://example.com?token=secret", "https://example.com#secret",
                    "https://example.com:invalid", "https://[broken"):
            self.raw["http"] = {"public_url": url}
            with self.subTest(url=url), self.assertRaises(ConfigError):
                self.load()

    def test_plaintext_password_and_unchecked_host_key_rejected(self):
        self.raw["servers"][0]["password"] = "do-not-log-me"
        with self.assertRaises(ConfigError) as raised:
            self.load()
        self.assertNotIn("do-not-log-me", str(raised.exception))
        del self.raw["servers"][0]["password"]
        del self.raw["servers"][0]["known_hosts"]
        with self.assertRaises(ConfigError):
            self.load()

    def test_no_ambient_auth_and_missing_secrets(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ConfigError):
                self.load().server("test").credentials()
            with self.assertRaises(ConfigError):
                self.load().token()
        del self.raw["servers"][0]["password_env"]
        with self.assertRaises(ConfigError):
            self.load()

    def test_token_validation(self):
        for value in ("short", "x" * 31, "x" * 32 + "\n", "密" * 40):
            with patch.dict(os.environ, {"SSH_MCP_TOKEN": value}), self.assertRaises(ConfigError):
                self.load().token()
        with patch.dict(os.environ, {"SSH_MCP_TOKEN": "x" * 48}):
            self.assertEqual(self.load().token(), "x" * 48)

    def test_unknown_fields_and_limits(self):
        for limits in ({"max_sessions": 0}, {"file_timeout": True}, {"typo": 10}):
            self.raw["limits"] = limits
            with self.subTest(limits=limits), self.assertRaises(ConfigError):
                self.load()


class AuthTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, headers, messages=None, max_body=1024):
        calls, sent = [], []

        async def app(scope, receive, send):
            calls.append(await receive())
            await send({"type": "http.response.start", "status": 200, "headers": []})

        async def send(message):
            sent.append(message)

        queue = asyncio.Queue()
        for message in messages or [{"type": "http.request", "body": b"{}"}]:
            queue.put_nowait(message)
        await BearerAuth(app, "x" * 48, max_body)(
            {"type": "http", "headers": headers}, queue.get, send,
        )
        return sent, calls

    async def test_auth_required_on_every_request(self):
        for headers in ([], [(b"authorization", b"Bearer wrong")],
                        [(b"authorization", b"Basic " + b"x" * 48)],
                        [(b"authorization", b"Bearer " + b"x" * 48)] * 2):
            sent, calls = await self.request(headers)
            self.assertEqual(sent[0]["status"], 401)
            self.assertFalse(calls)
            self.assertNotIn("x" * 48, str(sent))

    async def test_valid_auth_body_replayed(self):
        sent, calls = await self.request([(b"authorization", b"bearer " + b"x" * 48)])
        self.assertEqual(sent[0]["status"], 200)
        self.assertEqual(calls[0]["body"], b"{}")

    async def test_chunked_body_limit(self):
        sent, calls = await self.request([(b"authorization", b"Bearer " + b"x" * 48)], [
            {"type": "http.request", "body": b"aaa", "more_body": True},
            {"type": "http.request", "body": b"bbb", "more_body": False},
        ], max_body=5)
        self.assertEqual(sent[0]["status"], 413)
        self.assertFalse(calls)


if __name__ == "__main__":
    unittest.main()
