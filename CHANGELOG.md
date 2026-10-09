# Changelog

## 0.1.0a1 — Unreleased

- Add a built-in Chinese operator console with server CRUD/search, SSH probes,
  line-oriented terminal sessions, client setup snippets and management history.
- Persist inventory and bounded admin audit in SQLite with optimistic revision
  checks; seed JSON once and preserve edits/deletions across restarts.
- Separate human administrator authentication from MCP bearer authentication.
- Add console/API/SQLite tests, DOM-to-backend workflow tests and browser QA scripts.

- Create an independent MIT-licensed SSH MCP project.
- Implement multi-server configuration with password/private-key authentication
  and explicit known-host verification.
- Add asynchronous shell execution, persistent PTYs, output cursors, session
  management, timeouts and resource cleanup.
- Add SFTP text/binary operations and chunked upload/download through MCP.
- Add authenticated HTTP transport, local stdio and operator CLI.
- Add metadata-only audit logging, sanitized errors, configuration validation,
  body/output/file limits and no ambient SSH authentication.
- Add deployment templates, client examples, unit/lifecycle/integration tests and CI.
- Record pending dependency-backed validation and real-client deployment acceptance.
