"""SQLite server inventory, optimistic revisions and content-free operator audit."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .config import Config, Server, parse_config
from .errors import InputError


class Conflict(InputError):
    pass


def entry(server: Server) -> dict:
    data = {**server.public(), "known_hosts": str(server.known_hosts)}
    for key in ("private_key", "password_env", "passphrase_env"):
        value = getattr(server, key)
        if value:
            data[key] = str(value)
    return data


class Registry:
    def __init__(self, config: Config, filename: Path | None = None):
        self.base = filename.resolve().parent if filename else Path.cwd()
        if filename:
            filename = filename.resolve()
            filename.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(filename, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
            os.chmod(filename, 0o600)
        self.db = sqlite3.connect(str(filename) if filename else ":memory:", timeout=5)
        self.db.row_factory = sqlite3.Row
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1):
            self.db.close()
            raise InputError("Unsupported inventory database version")
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY, revision INTEGER)")
            self.db.execute("CREATE TABLE IF NOT EXISTS servers (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            self.db.execute("""CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL,
                event TEXT NOT NULL, target TEXT NOT NULL, outcome TEXT NOT NULL)""")
            self.db.execute("PRAGMA user_version = 1")
            if self.db.execute("SELECT revision FROM meta WHERE id=1").fetchone() is None:
                self.db.execute("INSERT INTO meta VALUES (1, 1)")
                self.db.executemany("INSERT INTO servers VALUES (?, ?)",
                                    [(s.id, json.dumps(entry(s))) for s in config.servers])

    def snapshot(self) -> dict:
        with self.db:
            self.db.execute("BEGIN")
            revision = self.db.execute("SELECT revision FROM meta WHERE id=1").fetchone()[0]
            servers = [json.loads(r[0]) for r in self.db.execute("SELECT data FROM servers ORDER BY id")]
        return {"revision": revision, "servers": servers}

    def config(self, initial: Config) -> Config:
        parsed = parse_config({"servers": self.snapshot()["servers"]}, self.base)
        return replace(initial, servers=parsed.servers)

    def change(self, revision: int, server_id: str, data: dict | None, *, create=False) -> None:
        if type(revision) is not int:
            raise InputError("Missing configuration revision; refresh and retry")
        if data is not None:
            parsed = parse_config({"servers": [data]}, self.base).servers[0]
            if parsed.id != server_id:
                raise InputError("Server ID cannot be changed")
            data = entry(parsed)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT revision FROM meta WHERE id=1").fetchone()[0] != revision:
                raise Conflict("Configuration changed elsewhere; refresh before saving")
            exists = self.db.execute("SELECT 1 FROM servers WHERE id=?", (server_id,)).fetchone()
            if create and exists:
                raise Conflict("Server ID already exists")
            if not create and not exists:
                raise Conflict("Server no longer exists; refresh before saving")
            if create and self.db.execute("SELECT count(*) FROM servers").fetchone()[0] >= 128:
                raise InputError("The console supports up to 128 servers")
            if data is None:
                self.db.execute("DELETE FROM servers WHERE id=?", (server_id,))
            elif create:
                self.db.execute("INSERT INTO servers VALUES (?, ?)", (server_id, json.dumps(data)))
            else:
                self.db.execute("UPDATE servers SET data=? WHERE id=?", (json.dumps(data), server_id))
            self.db.execute("UPDATE meta SET revision=revision+1 WHERE id=1")
            self._record("server.delete" if data is None else "server.create" if create else "server.update",
                         server_id, "ok")

    def _record(self, event: str, target: str, outcome: str) -> None:
        self.db.execute("INSERT INTO audit(timestamp,event,target,outcome) VALUES (?,?,?,?)",
                        (datetime.now(timezone.utc).isoformat(), event, target, outcome))
        self.db.execute("DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT 1000)")

    def record(self, event: str, target: str, outcome: str = "ok") -> None:
        with self.db:
            self._record(event, target, outcome)

    def history(self) -> list[dict]:
        return [dict(row) for row in self.db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 50")]

    def close(self) -> None:
        self.db.close()
