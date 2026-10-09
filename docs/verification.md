# Verification record

Date: 2026-10-09. Version: `0.1.0a1` (unreleased).

## Executed locally

| Check | Result |
| --- | --- |
| Python syntax compilation of source/tests | Passed on Python 3.10.12 |
| CLI version | Reports `0.1.0a1` |
| Core configuration, output buffer and HTTP auth tests | 13 passed |
| Deterministic process lifecycle tests using a transport fake | 8 passed |
| SQLite inventory and admin API tests | 12 passed |
| Live-test cleanup boundary tests (no network) | 2 passed |
| Full unittest discovery | 35 passed; 1 integration module explicitly skipped |
| Console DOM → real admin API → temporary SQLite | 8 workflow subtests passed (9 including parent suite); SSH simulated |
| JavaScript syntax and document local-link checks | Passed |

The lifecycle suite covers concurrent capacity reservation, failed-connection slot
release, both output streams and exit status, polling cancellation, input/EOF,
timeout, close-before-monitor-start cleanup and idle/completed-result expiry.
These tests validate service logic; they do not exercise the external SSH library.

## Supplied but not yet run

`tests/test_integration.py` contains 10 scenarios using real loopback SSH/SFTP,
temporary credentials, POSIX subprocesses/PTYs and official MCP clients:

- Password and private-key authentication; stdout/stderr and nonzero exit codes.
- Long-running commands and command timeout.
- Persistent PTY state and independent sessions.
- SFTP UTF-8 boundaries, binary chunks, stat/list and deletion.
- Rejection of a changed host key.
- Output flood bounds and session capacity.
- Idle-session expiry.
- Sanitization of library errors.
- HTTP MCP initialization, tool discovery, command/file operations, authentication
  and invalid Host rejection.
- stdio MCP discovery.

The development environment has Python but no working pip/venv bootstrap or
installed MCP/AsyncSSH runtime. The inherited network proxy is unreachable, and
direct package-host DNS resolution is unavailable. Dependency installation could
not complete. No integration success is inferred from source inspection.

CI requires dependencies and sets `SSH_MCP_REQUIRE_INTEGRATION=1`, so a missing
dependency is a failure rather than a silent skipped acceptance check. CI has not
run here. Ruff, dependency audit, wheel build, Docker build and HTTPS deployment
are also unverified. Test failures found when these run must be resolved before release.

## External acceptance still required

The operator console's local HTTP preview failed to start: this sandbox rejects
socket creation with `PermissionError: Operation not permitted`. Chromium launch
also failed with a sandbox `Operation not permitted` error. No browser screenshots
or desktop/mobile visual acceptance are claimed. `tests/console.browser.cjs` and
the console CI job provide the pending workflow and screenshot checks.

DOM tests ran with locally available jsdom 30.1.2 and Node 24.18.0, using stdio to
exercise the real Python console and temporary SQLite. They verified login, search,
server create/edit/delete, simulated SSH probes and sessions, configuration snippets,
management audit and logout. This does not verify rendering or actual SSH connectivity.

An operator-authorized production SSH probe failed immediately at local socket
creation (`socket: Operation not permitted`), before connection or authentication.
No server commands ran and no real user server was contacted or modified.
The opt-in [live SSH check](live-ssh-check.md) is prepared but has not run against
a real target; its cleanup boundary has only been tested locally.

No cloud endpoint was deployed,
GitHub repository created remotely, package published or client integration
activated. Run the [client walkthrough](clients.md#acceptance-walkthrough) through
a deployed HTTPS endpoint with a disposable target and record the chosen client
version, test results and limitations without credentials or private output.

ChatGPT OAuth compatibility is not implemented in this alpha. It is separately
tracked as `MCP-002`; successful bearer-client acceptance will not close that item.
