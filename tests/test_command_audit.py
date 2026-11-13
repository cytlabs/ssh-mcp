import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ssh_mcp.command_audit import record_dispatch


class CommandAuditTests(unittest.TestCase):
    def test_command_and_shell_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.db"
            with patch.dict(os.environ, SSH_MCP_COMMAND_AUDIT_DB=str(path)):
                record_dispatch("alpha", "one", "command", "hostname")
                record_dispatch("beta", "two", "shell_input", "pwd\n")
            with closing(sqlite3.connect(path)) as db:
                rows = db.execute("SELECT timestamp,server_id,session_id,event,content "
                                  "FROM command_audit ORDER BY id").fetchall()
            self.assertEqual([r[1:] for r in rows], [
                ("alpha", "one", "command", "hostname"),
                ("beta", "two", "shell_input", "pwd\n"),
            ])
            self.assertTrue(all(datetime.fromisoformat(r[0]).utcoffset().total_seconds() == 0
                                for r in rows))
