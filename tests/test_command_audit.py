import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from ssh_mcp.auth import operator_nickname
from ssh_mcp.command_audit import command_history, prune_content, record_dispatch


class CommandAuditTests(unittest.TestCase):
    def test_input_is_metadata_by_default_and_retention_removes_only_body(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.db"
            with patch.dict(os.environ, {"SSH_MCP_COMMAND_AUDIT_DB": str(path),
                                         "SSH_MCP_AUDIT_SHELL_INPUT": "0"}):
                record_dispatch("server", "abc", "shell_input", "private fixture text")
                with patch.dict(os.environ, SSH_MCP_AUDIT_COMMAND_TEXT="0"):
                    record_dispatch("server", "abc", "command", "unrecorded")
                record_dispatch("server", "abc", "command", "old body")
                record_dispatch("server", "abc", "command", "recent body")
            old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("UPDATE command_audit SET timestamp=? WHERE id=3", (old,))
            prune_content(path, 30)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT content FROM command_audit ORDER BY id").fetchall(),
                                 [("",), ("",), ("",), ("recent body",)])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

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
            with patch.dict(os.environ, SSH_MCP_COMMAND_AUDIT_DB=str(path), SSH_MCP_AUDIT_SHELL_INPUT="1"):
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
