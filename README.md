# SSH MCP

**A real SSH terminal for your AI client. Your credentials stay on the server.**

[中文说明](README.zh-CN.md) · [Deployment](docs/deployment.md) ·
[Client setup](docs/clients.md) · [Operator console](docs/console.md) · [Tool reference](docs/tools.md) · [Roadmap](ROADMAP.md)

SSH MCP connects MCP clients to operator-configured SSH servers. The client chooses
a server, runs arbitrary shell commands, keeps interactive terminals open, and
reads or writes files over SFTP. It needs no local SSH installation or SSH key.

The MCP service provides connections and execution. The AI client plans the work.
There are no Docker-, Nginx-, or application-specific tools or command allowlists.

**Status: `0.1.0a1`, pre-release development.** Core unit tests have run locally;
SSH/MCP integration tests and container builds are supplied but have not yet run in
the development environment. No hosted endpoint or client certification is claimed.
See [verification status](docs/verification.md) before deploying.

## Capabilities

- Multiple SSH targets, password or private-key authentication, strict host-key checking.
- Arbitrary commands with stdout, stderr, exit status, timeout and asynchronous polling.
- Persistent shells with optional PTY, interactive input, resizing and independent sessions.
- Replayable output cursors, bounded buffers, idle expiry and completed-output retention.
- SFTP text and binary files, byte-range editing, chunked uploads and downloads.
- Authenticated Streamable HTTP behind HTTPS, or local stdio.
- Built-in operator console for server management, connection checks, sessions and client setup.
- SQLite inventory and management history, JSON runtime settings, and content-free operation logs.

This release uses one operator bearer token and a single worker. All clients with
that token share the configured servers and sessions. Terminals survive individual
requests and client reconnects, but do not survive a service restart.

## Quick start

Requires Python 3.10+ with pip/venv, and network access from the MCP host to each
target's SSH port. Targets need an SSH server; file tools also need SFTP enabled.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
cp config.example.json config.json
mkdir -p secrets
chmod 700 secrets
```

Edit `config.json`: replace the example targets, point `private_key` and
`known_hosts` to real files, and remove unused targets. Relative paths are resolved
against the configuration file's directory. Passwords and key passphrases are
referenced by environment-variable name, never stored inline in the JSON.

Populate `known_hosts` with independently verified target host keys. See
[host-key enrollment](docs/deployment.md#host-key-enrollment); do not disable verification.

```sh
export SSH_MCP_TOKEN="$(ssh-mcp generate-token)"
export SSH_MCP_ADMIN_TOKEN="$(ssh-mcp generate-token)"
# If configured, load LAB_SSH_PASSWORD from your secret manager/environment.
ssh-mcp check --config config.json
ssh-mcp serve --config config.json
```

The internal endpoint is `http://127.0.0.1:8000/mcp`; requests require
`Authorization: Bearer <SSH_MCP_TOKEN>`. Put the supplied HTTPS reverse proxy in
front of it for remote clients. Do not expose the internal HTTP port publicly.

Open `/console` to manage servers with the separate admin token. The first service
start imports JSON targets into SQLite; later inventory changes are made in the console
and persist across restarts. Runtime settings remain in JSON. See [console and database setup](docs/console.md).

For local stdio: `ssh-mcp serve --transport stdio --config /absolute/path/config.json`.
stdio uses the local process trust boundary and does not require an HTTP token.

## Example interaction

1. Ask the client to list servers → `list_servers`.
2. Ask what containers are running on staging → `execute_command("staging", "docker ps -a")`.
3. For an interactive workflow → `create_session`, then `send_input` with a newline.
4. Poll `read_output` using returned cursors; inspect exit status and output loss.
5. Use `read_file` / `write_file` to edit; run tests through the same shell tools.
6. Call `close_session` to release each terminal and its output.

These are example actions, not operations performed on any user server.

## Client compatibility

Header-capable remote MCP clients can use HTTPS + Bearer authentication. Codex,
Cursor and Claude Code configuration examples are in [client setup](docs/clients.md).
Local clients can use stdio. **ChatGPT custom remote integrations requiring OAuth
need an OAuth-capable gateway or a future OAuth release; a static bearer endpoint
is not a drop-in ChatGPT OAuth integration.** Do not disable authentication to connect.

## Development

```sh
python -m pip install -e '.[dev]'
ruff check .
SSH_MCP_REQUIRE_INTEGRATION=1 python -m unittest discover -s tests -v
python -m build
pip-audit
```

Integration tests start disposable local SSH/SFTP targets and an HTTP MCP endpoint;
they do not use `config.json`, production servers, or existing SSH credentials.
Without installed dependencies, plain unittest discovery explicitly skips the
integration module; CI sets the flag above so missing dependencies fail the build.

See [architecture](docs/architecture.md), [contributing](CONTRIBUTING.md), and
[security boundaries](SECURITY.md). Licensed under [MIT](LICENSE).
