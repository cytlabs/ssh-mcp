"""公开入口联调必须在发送认证头前拒绝不安全 URL。"""

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    spec = importlib.util.spec_from_file_location("smoke_http", SCRIPTS / "smoke_http.py")
    smoke_http = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke_http)
finally:
    sys.path.pop(0)


class HTTPProbeSafetyTests(unittest.TestCase):
    def test_accept_https_mcp_with_optional_port(self):
        for value in ("https://example.com/mcp", "https://192.0.2.1:8443/mcp"):
            self.assertEqual(smoke_http.validate_url(value), value)

    def test_reject_plaintext_credentials_query_and_wrong_endpoint(self):
        for value in ("http://example.com/mcp", "https://user:secret@example.com/mcp",
                      "https://example.com/mcp?token=secret", "https://example.com/mcp#secret",
                      "https://example.com/console", "https:///mcp",
                      "https://example.com:99999/mcp", "https://example.com:wrong/mcp"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                smoke_http.validate_url(value)


if __name__ == "__main__":
    unittest.main()
