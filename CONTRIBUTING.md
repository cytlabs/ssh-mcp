# Contributing

SSH MCP gives AI clients general-purpose server access through SSH. Contributions
should improve connectivity, execution, terminals, files or interoperability.
Business-specific tools and an embedded agent framework are outside scope.

## Set up

Use Linux/macOS with Python 3.10+ and pip/venv. The integration suite uses POSIX
shells and PTYs; CI runs Linux.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
ruff check .
SSH_MCP_REQUIRE_INTEGRATION=1 python -m unittest discover -s tests -v
python -m build
pip-audit
```

Do not use production SSH targets for automated tests. The integration fixture
generates temporary host/user keys and password credentials, runs encrypted SSH
and SFTP on loopback, and tests an HTTP MCP client against real subprocesses.
The separate lifecycle suite uses a transport fake to test races and timeouts
deterministically; that suite alone does not establish interoperability.

For a separately authorized operator target, use the opt-in
[live SSH check](docs/live-ssh-check.md). It is excluded from automated CI and
defaults to checks without file writes.

## Console tests

The shipped console is buildless; Node.js is only needed for development tests.
Use the Node version range in `package.json` (locally checked with 24.18.0).
Run `npm install`, `npm run test:ui`, then `npx playwright install --with-deps chromium`
and `npm run test:browser` in an environment supporting local listeners and Chromium.
The UI tests use disposable SQLite and simulated SSH. Screenshots land in the
ignored `test-results/` directory. Real SSH verification remains in the Python
integration suite. See [console documentation](docs/console.md).

## Changes and review

1. Describe the user-visible problem and expected result in an issue or pull request.
2. Keep tool names/contracts stable; explain incompatible changes and migration.
3. Add meaningful tests for changed authentication, lifecycle or file behavior.
4. Update relevant docs and `CHANGELOG.md`, including any remaining limitations.
5. Report checks actually run. Do not convert skipped integration tests to a pass.

Never commit real inventories, credentials, private keys, `.env` files or command
transcripts. Example addresses must be reserved examples. Logs and errors must
not expose credentials, input text or arbitrary library exception messages.

Configuration examples and deployment templates are part of the public product.
Review their defaults as carefully as code. New dependencies need a concrete
reason and a license compatible with distributing this MIT project.

## Release process

Before the first public release, close the release gates in `ROADMAP.md`, resolve
and record a tested dependency set, build the wheel/container in CI, enable private
vulnerability reporting, and verify package/repository naming availability.
Tag only a commit whose checks and real-client acceptance are recorded. Publishing
to a registry or making the repository public is a separate maintainer action.

Contributions are made under the repository's MIT license. Keep discussion
respectful, technical and focused on reproducible behavior.
