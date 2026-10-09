"""Strict operator-owned configuration. Never serialize credentials to MCP."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .errors import InputError


class ConfigError(ValueError):
    pass


def integer(value: object, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ConfigError(f"{name} must be an integer in [{low}, {high}]")
    return value


def string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ConfigError(f"{name} must be a non-empty string without NUL bytes")
    return value


def fields(data: dict, allowed: set[str], name: str) -> None:
    if not isinstance(data, dict) or set(data) - allowed:
        raise ConfigError(f"Unknown fields or invalid object in {name}")


def path_from(value: object, base: Path, name: str) -> Path:
    path = Path(string(value, name)).expanduser()
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


@dataclass(frozen=True)
class Server:
    id: str
    host: str
    username: str
    known_hosts: Path = field(repr=False)
    port: int = 22
    description: str = ""
    private_key: Path | None = field(default=None, repr=False)
    password_env: str | None = field(default=None, repr=False)
    passphrase_env: str | None = field(default=None, repr=False)

    def public(self) -> dict:
        return {"id": self.id, "host": self.host, "port": self.port,
                "username": self.username, "description": self.description}

    def credentials(self) -> dict:
        result = {}
        for name, env in (("password", self.password_env), ("passphrase", self.passphrase_env)):
            if env:
                value = os.environ.get(env)
                if not value:
                    raise ConfigError("A configured SSH secret environment variable is missing")
                result[name] = value
        return result


@dataclass(frozen=True)
class Config:
    servers: tuple[Server, ...]
    public_url: str = "https://localhost"
    listen_host: str = "127.0.0.1"
    listen_port: int = 8000
    token_env: str = "SSH_MCP_TOKEN"
    max_sessions: int = 32
    buffer_chars: int = 1_048_576
    idle_timeout: int = 1800
    retention_seconds: int = 600
    connect_timeout: int = 15
    file_timeout: int = 60
    max_file_chunk: int = 262_144

    def server(self, server_id: str) -> Server:
        for server in self.servers:
            if server.id == server_id:
                return server
        raise InputError("Unknown server_id; call list_servers first")

    def token(self) -> str:
        value = os.environ.get(self.token_env, "")
        if len(value) < 32 or not value.isascii() or any(c.isspace() for c in value):
            raise ConfigError("HTTP requires a random ASCII bearer token of at least 32 characters")
        return value


def load_config(filename: str | Path) -> Config:
    path = Path(filename).expanduser().resolve()
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        raise ConfigError("Cannot read configuration JSON") from None
    return parse_config(raw, path.parent)


def parse_config(raw: dict, base: Path) -> Config:
    """Validate configuration data; relative credential paths use an operator-owned base."""
    fields(raw, {"servers", "http", "limits"}, "configuration")
    http, limits = raw.get("http", {}), raw.get("limits", {})
    fields(http, {"public_url", "listen_host", "listen_port", "token_env"}, "http")
    ranges = {"max_sessions": (1, 1024), "buffer_chars": (1024, 8_388_608),
              "idle_timeout": (1, 604800), "retention_seconds": (1, 86400),
              "connect_timeout": (1, 120), "file_timeout": (1, 3600),
              "max_file_chunk": (1024, 1_048_576)}
    fields(limits, set(ranges), "limits")
    kwargs = {k: integer(v, k, *ranges[k]) for k, v in limits.items()}
    for k, v in http.items():
        kwargs[k] = integer(v, k, 1, 65535) if k == "listen_port" else string(v, k)
    try:
        url = urlsplit(kwargs.get("public_url", "https://localhost"))
        if url.port is not None:
            integer(url.port, "public_url port", 1, 65535)
    except ValueError:
        raise ConfigError("http.public_url contains an invalid host or port") from None
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in ("", "/")):
        raise ConfigError("http.public_url must be an HTTPS origin without credentials or a path")
    entries = raw.get("servers")
    if not isinstance(entries, list):
        raise ConfigError("servers must be an array")
    servers, ids = [], set()
    for entry in entries:
        fields(entry, {"id", "host", "port", "username", "description", "known_hosts",
                       "private_key", "password_env", "passphrase_env"}, "server")
        sid = string(entry.get("id"), "server.id")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", sid) or sid in ids:
            raise ConfigError("Server IDs must be unique, 1–64 alphanumeric/_/- characters")
        ids.add(sid)
        options = {}
        for key in ("private_key", "known_hosts"):
            if key in entry:
                options[key] = path_from(entry[key], base, key)
        if "known_hosts" not in options:
            raise ConfigError("Every server needs an explicit known_hosts file")
        for key in ("password_env", "passphrase_env"):
            if key in entry:
                options[key] = string(entry[key], key)
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", options[key]):
                    raise ConfigError("Secret references must be environment variable names")
        if not (options.get("private_key") or options.get("password_env")):
            raise ConfigError("Each server needs private_key or password_env")
        if options.get("passphrase_env") and not options.get("private_key"):
            raise ConfigError("passphrase_env requires private_key")
        description = entry.get("description", "")
        if not isinstance(description, str) or len(description) > 512:
            raise ConfigError("description must be a string up to 512 characters")
        servers.append(Server(
            id=sid, host=string(entry.get("host"), "host"),
            username=string(entry.get("username"), "username"),
            port=integer(entry.get("port", 22), "port", 1, 65535),
            description=description, **options,
        ))
    return Config(servers=tuple(servers), **kwargs)
