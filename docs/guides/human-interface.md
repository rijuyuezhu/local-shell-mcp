# Human interface

The HTTP server includes a browser Human UI foundation at `/ui` by default. It is designed to become the shared backend for the browser interface and the native OpenTUI client.

## Start the HTTP server

```bash
local-shell-mcp --mode http
```

Open the URL formed from the configured host and port, for example:

```text
http://127.0.0.1:8765/ui
```

The current migration slice provides:

- a packaged responsive browser shell;
- runtime and package version information;
- local and remote machine inventory;
- OAuth-protected Human UI APIs;
- a private loopback-only token path for future native OpenTUI clients;
- configurable UI enablement and mount path.

Terminal, Files, Todos, Audit, dashboard telemetry, and the native OpenTUI executable remain in the explicit follow-up migration queue.

## Authentication

The HTML, CSS, and JavaScript shell is public so a browser can load the authentication experience. Human UI API routes under `/api/ui` follow the normal server authentication mode.

With `auth_mode: oauth`, paste a valid OAuth access token into the browser form. The browser stores it only in `sessionStorage`, so closing the tab removes it.

Native clients use a separate private token stored at:

```text
<state_dir>/ui/local-token
```

The file is created with mode `0600`. This token bypasses OAuth only when both conditions hold:

1. the request targets `/api/ui`;
2. the transport peer itself is a loopback address.

Forwarded headers are ignored, so a reverse proxy connected over loopback does not grant this bypass to remote users.

## Configuration

```yaml
ui_enabled: true
ui_path: /ui
```

Equivalent environment variables are:

```bash
LOCAL_SHELL_MCP_UI_ENABLED=true
LOCAL_SHELL_MCP_UI_PATH=/ui
```

`ui_path` must be a non-root URL path. Paths reserved by the MCP, OAuth, remote-worker, download, health, documentation, and Human UI API surfaces are rejected.

Disable the browser surface completely with:

```bash
LOCAL_SHELL_MCP_UI_ENABLED=false
```

## Security notes

Do not run `auth_mode: none` on a public or shared network. The Human UI can display and eventually mutate shell, filesystem, remote-worker, and task state, so it inherits the same deployment trust requirements as the REST and MCP surfaces.

The browser shell sets a restrictive Content Security Policy, disallows framing, avoids inline scripts, and serves assets with MIME sniffing disabled.
