import contextlib
import os
import sqlite3
from pathlib import Path
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
def command_history(before: int) -> dict:
    path = os.environ.get("SSH_MCP_COMMAND_AUDIT_DB")
    if not path or not Path(path).exists():
        return {"enabled": bool(path), "rows": [], "more": False}
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT id,timestamp,server_id,event,content FROM command_audit "
                          "WHERE id < ? ORDER BY id DESC LIMIT 21", (before,)).fetchall()
    return {"enabled": True, "rows": [dict(row) for row in rows[:20]], "more": len(rows) > 20}
