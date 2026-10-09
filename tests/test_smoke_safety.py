"""Guard the explicit live-test cleanup boundary without connecting to any host."""

import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "smoke_ssh", Path(__file__).parents[1] / "scripts" / "smoke_ssh.py",
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class SmokeSafetyTests(unittest.TestCase):
    def test_cleanup_only_targets_exact_file_and_empty_directory(self):
        directory = "/tmp/ssh-mcp-smoke-" + "a" * 32
        self.assertEqual(smoke.cleanup_command(directory),
                         f"rm -f -- {directory}/probe.txt && rmdir -- {directory}")

    def test_cleanup_rejects_other_paths_and_shell_metacharacters(self):
        for value in ("/", "/tmp", "/tmp/ssh-mcp-smoke-", "a" * 32,
                      "/tmp/ssh-mcp-smoke-" + "a" * 32 + "/..",
                      "/tmp/ssh-mcp-smoke-" + "a" * 32 + "; echo unsafe",
                      "/tmp/ssh-mcp-smoke-" + "a" * 32 + "\n"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                smoke.cleanup_command(value)
