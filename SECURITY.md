# Security policy and boundaries

## Intended trust model

SSH MCP is a remote administration capability for one operator and their trusted
clients. Possession of its bearer token grants the ability to run arbitrary
commands using every configured SSH account. There is no command allowlist,
per-operation confirmation, multi-user authorization or read-only account mode.
Use remote OS account permissions to enforce the access you intend.

Credential management is exclusively operator-side. Public server metadata omits
private-key paths, password/passphrase environment references and secret values.
SSH failures are converted to safe errors. Audit logs omit command/input/output
and credential material. Ambient SSH agents, default keys and user SSH config
are not used. Every configured target requires an explicit verified `known_hosts`.

## Credential isolation

The service account must be able to read configured SSH credentials, but target
accounts should not be able to read the service configuration, files or process
environment. If a target account has root on the MCP deployment host, arbitrary
shell commands can read those secrets. No application-level promise can prevent
that while granting full root shell access. Use a separate host or an OS boundary
appropriate to your trust model.

Remote command/file output may itself contain secrets stored on the target. SSH
MCP returns the requested content; it does not attempt unreliable blanket output
redaction. Keep service login credentials outside target-readable locations.

## Remote endpoint

- Terminate HTTPS at the supplied Caddy deployment or an existing trusted proxy.
- Keep the backend port private; a deployment with publicly accessible plaintext
  HTTP does not meet this project's remote deployment requirements.
- Generate a random bearer token, protect its client/server storage and rotate it
  with a service restart. Do not put it in URLs or conversations.
- `/mcp` requests require the MCP token, including protocol initialization.
- `/admin/` requests require a different administrator token. Public `/console`
  assets contain no server inventory or credentials. Never give an AI the admin token.
- SDK Host/Origin checks remain enabled. Configure the actual public origin.
- Configure proxy request-size/time limits; avoid proxy logs containing headers or bodies.
- A shared token is a shared trust domain. Session IDs do not isolate users.

Tool annotations inform client UX; they are not authorization. Arbitrary shell,
interactive input and upload/delete tools are conservatively marked destructive.
Outputs from remote servers may contain prompt injection; clients must treat
them as untrusted data and retain their normal user approval behavior.

## Resource and termination limits

The operator console stores server metadata, credential references and bounded
management audit records in SQLite. It returns credential references only to the
human admin API, never MCP discovery. It does not store raw SSH passwords or private
keys in the database. Protect the database as private infrastructure information.
Optional tab-scoped login uses sessionStorage; it is not an HttpOnly cookie or a
multi-user session system. The UI uses a restrictive CSP and renders remote output
as text, not HTML. Full browser rendering verification remains pending.

Connection and file operations have deadlines. Command jobs have explicit
timeouts; shells have idle expiry. Output buffers, file chunks, terminal counts
and directory listings are bounded. Completed output is retained temporarily.
Closing/terminating an SSH channel is best effort and cannot guarantee removal
of daemonized or disowned remote children. There is no durable output archive.

## Reporting

This repository is in pre-release development, with no public security contact
or hosted service yet. Before opening the repository publicly, maintainers must
enable GitHub private vulnerability reporting and verify that the Security tab
provides a private report action. Use that channel for vulnerabilities once enabled.
Do not post credentials, exploit details against real servers, or private command
output in public issues. Ordinary sanitized bugs can use the bug template.

Only the current development version is being maintained; there is no stable
security-support window yet. Dependency audits and integration validation must
pass before a public release. See [release gates](ROADMAP.md).
