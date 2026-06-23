# Troubleshooting

## Connector shows only `search` and `fetch`

Likely causes:

- ChatGPT Developer Mode is not enabled.
- The client is a regular connector or Deep Research-style client that only supports read-only tools.
- The connector tool list was not refreshed after server changes.

Enable Developer Mode for the full coding-agent surface, then refresh the connector.

## OAuth approval fails

Check:

```env
LOCAL_SHELL_MCP_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=...
```

Make sure the connector URL is exactly:

```text
https://your-public-host.example.com/mcp
```

The public base URL should be the origin only, without `/mcp`.

## Public URL does not work

Check the local health endpoint first:

```bash
curl -i http://127.0.0.1:8765/healthz
```

Then check the tunnel or reverse proxy:

- It must forward to the server port, usually `8765`.
- It must preserve HTTPS externally for ChatGPT.
- The public hostname must match `LOCAL_SHELL_MCP_BASE_URL`.

## Container cannot write state

If the container cannot write `/workspace/.local-shell-mcp`, fix ownership:

```bash
sudo mkdir -p workspaces/default/.local-shell-mcp
sudo chown -R 10001:10001 workspaces/default
docker compose restart local-shell-mcp
```

## Tool call times out

Public tool calls are bounded by strict watchdogs and shell timeouts. Check these settings:

```env
LOCAL_SHELL_MCP_TOOL_TIMEOUT_S=60
LOCAL_SHELL_MCP_RUN_SHELL_DEFAULT_TIMEOUT_S=10
LOCAL_SHELL_MCP_RUN_SHELL_MAX_TIMEOUT_S=60
```

Use persistent shells for long-running dev servers, REPLs, or interactive commands.

## Remote worker does not connect

Check:

- The invite has not expired.
- The remote machine can reach the public control server over outbound HTTPS.
- `LOCAL_SHELL_MCP_REMOTE_ENABLED=true` on the control server.
- The pasted command includes the correct `--server`, `--invite`, `--name`, and `--workdir` values.

Then ask the MCP client to run:

```text
Use local-shell-mcp `remote_admin(action="list", args={})`.
```

## Audit log is missing expected calls

Every routed MCP or REST debug tool call should produce a `tool_call_start` and `tool_call_end` pair. Check:

- The server is the instance your connector is actually using.
- The audit log path points to the location you are tailing.
- The state directory is writable.
- The call is not being rejected before routing.

## Release binary lacks system tools

The standalone binary includes the Python server and default OAuth dependencies. It does not bundle host tools such as Git, tmux, shells, compilers, or LibreOffice. Docker images include a broader toolchain.
