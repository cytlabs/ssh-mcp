# Architecture and decisions

## Product boundary

One operator deploys a reusable MCP-to-SSH service for trusted AI clients. Servers
and authentication material are configured out of band. The AI chooses targets
and operations, while the operating system/SSH account controls actual permissions.
There is no model provider, agent loop or business context store. A lightweight
operator web console manages the same server inventory and sessions as MCP.

## Components

| Module | Responsibility |
| --- | --- |
| `config.py` | Strict JSON, explicit credential references and public target metadata |
| `cli.py` | Validate, list, generate operator token, launch HTTP or stdio |
| `auth.py` | Constant-time bearer verification on every HTTP request and body limits |
| `server.py` | Official MCP SDK tools, sanitized errors, lifecycle and metadata audit |
| `ssh.py` | AsyncSSH connections, process lifetime, idle expiry and SFTP |
| `buffer.py` | Per-stream bounded replay with explicit character loss |
| `registry.py` | SQLite inventory, initial JSON import, edit revisions and bounded admin audit |
| `console.py` / `static/` | Separate admin API, same-origin web UI, server/session/client management |

Python + AsyncSSH provides SSH and SFTP without invoking a local `ssh` executable.
The official `mcp` Python SDK owns protocol handling and Streamable HTTP. The
dependency constraint selects the SDK's v1 API; a v2 migration is a deliberate
future change, not an implicit upgrade. Python 3.10 is the current minimum.

Protocol references: [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x),
[AsyncSSH API](https://asyncssh.readthedocs.io/en/stable/api.html).

## Process lifetime

HTTP uses stateless MCP transport. SSH terminal state is separately keyed by a
cryptographically random session ID in the single service worker. The caller can
recover IDs with `list_sessions`. MCP initialization/disconnection does not own
the SSH channel lifetime. A deployment-wide token represents one trust domain;
IDs are not a substitute for authentication or multi-tenant authorization.

Each terminal owns one SSH connection, process, bounded stdout/stderr buffers,
reader tasks and a completion monitor. Creation reserves a capacity slot before
awaiting connection establishment. The monitor drains both streams concurrently
and closes resources on completion, timeout or disconnect. The reaper expires
idle shells and retained results; service shutdown closes all terminals.

SFTP connections are short-lived, with separate bounded concurrency and an
operation deadline. Buffers and deadlines protect service resources, not command
semantics. SSH signals cannot guarantee process-tree termination on every server.

## Authentication decisions

Static bearer tokens are the first supported remote mode for clients that accept
headers. HTTPS terminates at a supplied Caddy template or an existing proxy. The
service verifies every HTTP request and checks Host/Origin through the SDK.
It never trusts a user-supplied identity header and does not forward its bearer
token to SSH targets. Credential rotation and runtime config changes require restart;
console inventory edits persist in SQLite and update the worker immediately.

The console uses an independent `SSH_MCP_ADMIN_TOKEN`. MCP clients cannot use their
token to edit the inventory or read credential references. Public static assets contain
no inventory. Admin requests require bearer auth, Host/Origin validation and body limits.
SQLite uses revision checks to prevent stale writes. Runtime terminals remain in memory.

OAuth is tracked separately because browser-based clients require discovery,
redirect validation, PKCE, consent and token lifecycle. Faking those with a login
form around a shared token would not satisfy the protocol. No OAuth metadata is
advertised until that mode exists.

## Future changes requiring a design review

- Multi-user access: per-principal server grants, isolated sessions and identity-bound logs.
- Multiple replicas: session ownership/routing and a defined failure-recovery contract.
- Durable sessions: explicit tmux integration or a remote supervisor, with recovery semantics.
- Browser OAuth: a tested identity provider/gateway integration and real-client acceptance.
- Large artifact delivery: a separate authenticated streaming mechanism with expiry and limits.

Any extension should preserve the generic tool boundary and keep credentials out
of discovery responses, errors and logs.
