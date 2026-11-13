import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from ssh_mcp.auth import operator_nickname
from ssh_mcp.command_audit import command_history, record_dispatch


class CommandAuditTests(unittest.TestCase):
    def test_old_records_and_nickname_search(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.db"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE command_identity(id INTEGER PRIMARY KEY,operator TEXT,ssh_user TEXT)")
            with patch.dict(os.environ, SSH_MCP_COMMAND_AUDIT_DB=str(path)):
                marker = operator_nickname.set("林辰")
                try:
                    record_dispatch("alpha", "one", "command", "uptime", "ops")
                finally:
                    operator_nickname.reset(marker)
                self.assertEqual(command_history(100, "林辰")["rows"][0]["nickname"], "林辰")

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
