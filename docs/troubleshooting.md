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
WORKGATE_BASE_URL=https://your-public-host.example.com
WORKGATE_AUTH_MODE=oauth
WORKGATE_OAUTH_ADMIN_PIN=...
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
- The public hostname must match `WORKGATE_BASE_URL`.

## Tool call times out

Public tool calls are bounded by strict watchdogs and shell timeouts. Check these settings:

```env
WORKGATE_TOOL_TIMEOUT_S=60
WORKGATE_RUN_SHELL_DEFAULT_TIMEOUT_S=10
WORKGATE_RUN_SHELL_MAX_TIMEOUT_S=120
```

Use persistent shells for long-running dev servers, REPLs, or interactive commands.

## Remote worker does not connect

Check:

- The invite has not expired.
- The remote machine can reach the public control server over outbound HTTPS.
- `WORKGATE_REMOTE_ENABLED=true` on the control server.
- The pasted command or `worker connect` invocation includes the correct `--server`, invite, `--name`, and `--workdir` values.


For an installed worker, inspect the native service without exposing identity credentials:

```bash
workgate worker status
workgate worker logs --lines 100
```

A `not_installed` status means enrollment may exist but no user service is installed. `unavailable` means systemd/launchd is supported on the platform but not reachable for the current user session. Windows returns `unsupported`. Use `worker run` to diagnose the stored identity in the foreground; use `worker install-service` only after foreground connection succeeds.

Then ask the MCP client to run:

```text
Use workgate `remote_admin(action="list", args={})`.
```

## Audit log is missing expected calls

Every routed MCP or REST debug tool call should produce a `tool_call_start` and `tool_call_end` pair. Check:

- The server is the instance your connector is actually using.
- The audit log path points to the location you are tailing.
- The state directory is writable.
- The call is not being rejected before routing.

## Release binary lacks system tools

The standalone binary includes the Python server and default OAuth
dependencies. On POSIX systems, persistent shells require a host tmux executable;
the default is `tmux` from `PATH`, and `WORKGATE_TMUX_BIN` may point to a
different executable. Git, shells, compilers, LibreOffice, and other host tools
are not bundled.
