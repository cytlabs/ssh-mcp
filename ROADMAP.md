# Product roadmap

## Purpose

Give any compatible MCP client a general SSH terminal without distributing SSH
credentials to that client. The service owns connections and execution; the client
owns task planning. Initial users are individual developers/operators managing
their own servers. The project is self-hosted and licensed under MIT.

## 0.1 — Single-operator MVP

Implementation is present for multi-target configuration, password/key auth,
strict host-key checks, arbitrary commands, persistent PTYs, asynchronous output,
SFTP chunks, HTTP bearer auth, stdio, CLI validation and bounded resources.
Packaging, deployment templates, documentation and CI are included. The operator
console and SQLite inventory are implemented; local DOM/API/persistence tests pass.

**Release status: blocked on validation, not yet accepted or published.**

Acceptance requires an authenticated public HTTPS MCP client to list targets,
execute a command, edit a file and run a test, without a manual SSH login during
the interaction. Unit tests and local protocol fixtures do not alone satisfy that gate.

## Tracked work

These are local tracking IDs. No external GitHub issues have been created yet.

| ID | Status | Work and completion evidence |
| --- | --- | --- |
| MCP-001 | Blocked by development environment | Install runtime/dev dependencies; pass real SSH/SFTP + HTTP/stdio tests, lint, package build, dependency audit and Docker build. Record resolved dependency versions. Current environment has unavailable package network access. |
| MCP-002 | Planned | OAuth-capable gateway/IdP integration or native OAuth, including discovery, PKCE, consent, refresh/revocation, audience checking and browser-client acceptance. Needed for the documented ChatGPT OAuth flow. |
| MCP-003 | Deployment authorized; SSH access blocked | Operator has selected a production host. Current execution environment denies SSH socket creation and sandbox escalation. Inspect existing services/proxy after access is available, choose a trusted HTTPS origin, run isolated integration tests before deploying, then record real client acceptance and bounded live SSH checks. Private host details and credentials stay outside this repository. |
| MCP-004 | Pending release | Confirm public project/package name, enable private vulnerability reporting, record tested dependency resolution, choose a version tag and publish only after release gates pass. |
| MCP-005 | Implemented; browser QA blocked | Operator console and SQLite inventory. Python API/persistence tests and DOM-to-SQLite workflows passed. Current sandbox rejects loopback listeners and Chromium startup; desktop/mobile rendering and real SSH console flow still need verification. |

## 0.2 — Client reach and operator ergonomics

- OAuth integration and actual ChatGPT/Claude browser-client acceptance.
- Optional operator CLI parity with the SQLite-backed web console.
- Connection diagnostics that keep secrets out of returned errors and logs.
- Checked dependency lock and a documented compatibility matrix.

## Later, driven by use

- Per-user identity and server grants if deployments need multiple trust domains.
- Durable terminal recovery with an explicit remote supervision contract.
- Large artifact transfer outside MCP text messages, with authenticated delivery.

## Non-goals

No embedded AI model or planning loop; no business action catalog; no command
allowlist; no complex dashboard; no hidden reading of unrelated SSH configs or
agents; no claims that arbitrary root execution can be made credential-isolated
on the same host by application filtering.
