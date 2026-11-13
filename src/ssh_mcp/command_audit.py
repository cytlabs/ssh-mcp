import contextlib
import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

from .auth import operator_name, operator_nickname


def record_dispatch(server_id: str, session_id: str, event: str, content: str,
                    ssh_user: str | None = None) -> None:
    path = os.environ.get("SSH_MCP_COMMAND_AUDIT_DB")
    if not path:
        return
    with contextlib.closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS command_audit (
            id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, server_id TEXT NOT NULL,
            session_id TEXT NOT NULL, event TEXT NOT NULL, content TEXT NOT NULL)""")
        db.execute("CREATE TABLE IF NOT EXISTS command_identity "
                   "(id INTEGER PRIMARY KEY, operator TEXT, ssh_user TEXT, nickname TEXT)")
        if "nickname" not in {row[1] for row in db.execute("PRAGMA table_info(command_identity)")}:
            db.execute("ALTER TABLE command_identity ADD COLUMN nickname TEXT")
        cursor = db.execute("INSERT INTO command_audit(timestamp,server_id,session_id,event,content) "
                   "VALUES (?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(),
                                          server_id, session_id, event, content))
        db.execute("INSERT INTO command_identity(id,operator,ssh_user,nickname) VALUES (?,?,?,?)",
                   (cursor.lastrowid, operator_name.get(), ssh_user, operator_nickname.get()))


def command_history(before: int, search="", start="", end="") -> dict:
    path = os.environ.get("SSH_MCP_COMMAND_AUDIT_DB")
    if not path or not Path(path).exists():
        return {"enabled": bool(path), "rows": [], "more": False}
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    with contextlib.closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        identity = db.execute("SELECT 1 FROM sqlite_master WHERE name='command_identity'").fetchone()
        fields = "operator,ssh_user" if identity else "NULL AS operator,NULL AS ssh_user"
        nick = "nickname" in {row[1] for row in db.execute("PRAGMA table_info(command_identity)")}
        fields += ",nickname" if nick else ",NULL AS nickname"
        tables = "command_audit LEFT JOIN command_identity USING(id)" if identity else "command_audit"
        filters = ["id < ?"]
        params = [before]
        if search:
            columns = ["server_id", "content"] + (["operator", "ssh_user"] if identity else [])
            if nick:
                columns.append("nickname")
            filters.append("(" + " OR ".join(f"instr(lower({c}),lower(?))" for c in columns) + ")")
            params.extend([search] * len(columns))
        if start and end:
            filters.append("julianday(timestamp) >= julianday(?) AND julianday(timestamp) < julianday(?)")
            params.extend([start, end])
        rows = db.execute(f"SELECT id,timestamp,server_id,event,content,{fields} FROM {tables} "
                          "WHERE " + " AND ".join(filters) + " ORDER BY id DESC LIMIT 21", params).fetchall()
    return {"enabled": True, "rows": [dict(row) for row in rows[:20]], "more": len(rows) > 20}
