# MCP client setup

The examples target `https://ssh-mcp.example.com/mcp`; replace it with your deployed
endpoint. Store the MCP token in the client's secret/environment configuration,
separately from conversations. Clients never need the SSH password or private key.
The MCP token itself grants access to all configured targets and is a secret.

These are configuration examples checked against vendor documentation, **not
claims of completed end-user client acceptance**. Availability and organization
policies depend on the client and account. See [verification](verification.md).

## Codex: remote HTTP

The official configuration supports a URL and an environment variable for the
bearer token. In your Codex config:

```toml
[mcp_servers.ssh]
url = "https://ssh-mcp.example.com/mcp"
bearer_token_env_var = "SSH_MCP_TOKEN"
startup_timeout_sec = 20
tool_timeout_sec = 90
```

Make `SSH_MCP_TOKEN` available to the Codex process through your environment/secret
store, restart or reload the client, and check that `list_servers` is discoverable.
Reference: [official MCP configuration](https://developers.openai.com/codex/mcp).

## Claude Code: remote HTTP

Use an HTTP entry in `.mcp.json`; the token reference is expanded by the client:

```json
{
  "mcpServers": {
    "ssh": {
      "type": "http",
      "url": "https://ssh-mcp.example.com/mcp",
      "headers": {"Authorization": "Bearer ${SSH_MCP_TOKEN}"}
    }
  }
}
```

Load the environment variable before starting Claude Code, then inspect `/mcp`.
This example is specifically for Claude Code; do not assume the same authentication
UI exists in Claude Desktop or claude.ai.
Reference: [Claude Code MCP and environment expansion](https://code.claude.com/docs/en/mcp).

## Cursor: remote HTTP

Add an entry in your user MCP configuration (`~/.cursor/mcp.json`), using Cursor's
environment-variable interpolation:

```json
{
  "mcpServers": {
    "ssh": {
      "url": "https://ssh-mcp.example.com/mcp",
      "headers": {"Authorization": "Bearer ${env:SSH_MCP_TOKEN}"}
    }
  }
}
```

Ensure the Cursor process receives the environment variable, then check its MCP
tool list. GUI-launched applications may have a different environment from a
terminal. Reference: [Cursor MCP configuration](https://cursor.com/docs/mcp).

## Local stdio: clients that launch a process

Use an absolute executable and configuration path:

```json
{
  "mcpServers": {
    "ssh": {
      "command": "/opt/ssh-mcp/.venv/bin/ssh-mcp",
      "args": ["serve", "--transport", "stdio", "--config", "/etc/ssh-mcp/config.json"]
    }
  }
}
```

The service process runs locally in this mode. Its environment and local files
must supply SSH credentials. stdout is reserved for the protocol; logs use stderr.
For an AI client without a local process environment, use remote HTTP instead.

## ChatGPT: OAuth integration still required

The documented ChatGPT custom MCP setup offers OAuth-related or unauthenticated
modes; static OAuth client credentials are distinct from a service's bearer API
token. SSH MCP `0.1.0a1` does not implement an OAuth authorization server or an
interactive login/consent flow. Do not select “No authentication” for this service.
Reference: [OpenAI custom MCP server guide](https://developers.openai.com/api/docs/guides/custom-mcp-server).

A future gateway integration must provide OAuth discovery, authorization code +
PKCE, validated redirect URIs, consent, audience-bound access tokens and revocation.
It must keep the internal bearer token server-side and prevent direct access to
the backend. This repository does not ship or claim to have tested that gateway.
Native OAuth / external identity-provider integration is tracked as `MCP-002` in
[the roadmap](../ROADMAP.md).

## Acceptance walkthrough

Use a disposable target configured by the operator. Once the chosen client is connected:

1. Ask “List the available servers.” Verify the expected aliases and absence of credentials.
2. Ask “On the test server, run `printf hello; printf error >&2; exit 7`.” Verify both
   streams and the exit code, including polling if the first response is running.
3. Ask for a persistent terminal; change directory, then check `pwd` in a separate input.
4. Ask to create a temporary text file, read it back, edit it and run a test against it.
5. Ask to run a command longer than one MCP request; reconnect the client and recover
   the session with `list_sessions`, then poll using output cursors.
6. Close the sessions and remove the temporary file. Save only sanitized results.

Run the same checks through the public HTTPS endpoint. SDK integration tests are
necessary but do not substitute for this actual client workflow.
