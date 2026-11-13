import contextlib
import os
import sqlite3
from datetime import datetime, timezone


def record_dispatch(server_id: str, session_id: str, event: str, content: str) -> None:
    path = os.environ.get("SSH_MCP_COMMAND_AUDIT_DB")
    if not path:
        return
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS command_audit (
            id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, server_id TEXT NOT NULL,
            session_id TEXT NOT NULL, event TEXT NOT NULL, content TEXT NOT NULL)""")
        db.execute("INSERT INTO command_audit(timestamp,server_id,session_id,event,content) "
                   "VALUES (?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(),
                                          server_id, session_id, event, content))
