# Opt-in live SSH check

Use this only against a target explicitly authorized by its operator. It is separate
from the disposable loopback integration suite and never runs in CI or test discovery.
Prefer a test server. An existing production target can be checked with the same
bounded workflow when its operator authorizes it.

Install the project dependencies **on the MCP host**, then supply a private JSON
configuration following [deployment](deployment.md). The script reads that JSON
directly; it does not change or read the console's SQLite inventory. Explicitly set
the SSH identity and a previously verified `known_hosts` file. A working local
`ssh` command may depend on an agent or SSH config: the product deliberately requires
explicit credentials and does not inherit either. Do not disable host-key checks or
put keys, passwords or real inventory into Git.

From the repository root:

```sh
PYTHONPATH=src python3 scripts/smoke_ssh.py --config config.json --server staging
# Also exercise file operations, when authorized:
PYTHONPATH=src python3 scripts/smoke_ssh.py --config config.json --server staging --files
```

The default checks verify authentication, standard output/error, exit code 7,
a one-second delayed command, PTY input and retained working directory. They use
only test shell processes and change the working directory of that test shell.
The remote host needs a POSIX shell and ordinary `sleep`, `mkdir`, `rm`, `rmdir`
commands; file checks also require SFTP. No software is installed remotely.

`--files` exclusively creates a random `/tmp/ssh-mcp-smoke-<32 hex characters>`
directory with mode 0700, writes and reads a small text/binary test file, deletes
that exact file and removes the empty directory. Cleanup runs in `finally` after
confirmed creation, uses no wildcards or recursive deletion, and refuses paths
outside that exact naming pattern. A network interruption or forced process kill
can leave a directory behind; review the reported path before manual cleanup.
The script never reads application files, inspects environment variables, restarts
services, changes system configuration or performs load tests. SSH login auditing
and operator-configured shell startup hooks still run as usual.

Output contains check labels, exception types and any temporary-directory cleanup
notice, not credentials or remote command transcripts. A nonzero exit means acceptance
is incomplete. Run in an environment which permits outbound SSH; an immediate local
`socket: Operation not permitted` is an execution-environment restriction, not proof
of a remote server fault.

This checks the actual SSH/SFTP implementation, **not** the MCP HTTP transport,
HTTPS deployment, OAuth or an AI client's behavior. Those require the separate
[client acceptance walkthrough](clients.md#acceptance-walkthrough). Record actual
results in [verification](verification.md), keeping private target details out of Git.
