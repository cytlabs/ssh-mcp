"""Small operator CLI. Config editing stays outside the AI tool surface."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import sqlite3
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, load_config
from .errors import InputError


def main() -> None:
    parser = argparse.ArgumentParser(prog="ssh-mcp", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("serve", "check", "list-servers"):
        command = sub.add_parser(name)
        command.add_argument("--config", default="config.json")
        command.add_argument("--database", help="SQLite inventory; default: data/ssh-mcp.sqlite3 beside config")
        if name == "serve":
            command.add_argument("--transport", choices=["http", "stdio"], default="http")
    sub.add_parser("generate-token", help="Print a new token for an operator to store securely")
    args = parser.parse_args()
    if args.command == "generate-token":
        print(secrets.token_urlsafe(48))
        return
    try:
        config = load_config(args.config)
        from .registry import Registry
        database = Path(args.database) if args.database else Path(args.config).resolve().parent / "data/ssh-mcp.sqlite3"
        if args.command != "serve" and database.exists():
            registry = Registry(config, database)
            try:
                config = registry.config(config)
            finally:
                registry.close()
        if args.command == "list-servers":
            print(json.dumps([s.public() for s in config.servers], indent=2))
        elif args.command == "check":
            for server in config.servers:
                for path in (server.known_hosts, server.private_key):
                    if path and not path.is_file():
                        raise ConfigError("A configured known_hosts or private key file is missing")
                server.credentials()
            config.token()
            print(f"Configuration valid: {len(config.servers)} server(s). SSH connectivity not tested.")
        else:
            from .server import create_http_app, run_stdio
            logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
            logging.getLogger("ssh_mcp.audit").setLevel(logging.INFO)
            if args.transport == "stdio":
                registry = Registry(config, database)
                try:
                    asyncio.run(run_stdio(registry.config(config)))
                finally:
                    registry.close()
            else:
                import uvicorn
                uvicorn.run(create_http_app(config, database), host=config.listen_host,
                            port=config.listen_port, workers=1, access_log=False,
                            proxy_headers=False, log_level="warning")
    except (ConfigError, InputError, OSError, sqlite3.Error):
        print("Configuration or startup failed. Check JSON fields, secret environment variables, "
              "key/known_hosts files, SQLite permissions and listen address. No credentials were printed.", file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
