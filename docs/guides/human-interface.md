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
- automatic browser OAuth Authorization Code flow with PKCE S256;
- authenticated local tmux terminal listing, creation, input, resize, snapshots, and termination;
- workspace-confined local file browsing, previews, editing, creation, copy, move, rename, and deletion;
- OAuth-protected Human UI APIs and terminal WebSockets;
- a private loopback-only token path for future native OpenTUI clients;
- configurable UI enablement and mount path.

Remote-worker terminals and files, rich xterm-compatible rendering, Todos, Audit, dashboard telemetry, and the native OpenTUI executable remain in the explicit follow-up migration queue.

## Authentication

The HTML, CSS, and JavaScript shell is public so a browser can load the authentication experience. Human UI API routes under `/api/ui` follow the normal server authentication mode.

With `auth_mode: oauth`, select **Sign in with OAuth**. The browser:

1. dynamically registers the exact `<origin><ui_path>/callback` redirect URI;
2. creates a cryptographically random PKCE verifier and OAuth `state` value;
3. requests approval using `code_challenge_method=S256` and the server-advertised scope and resource;
4. verifies both `state` and the authorization response `iss` value;
5. exchanges the code while including the resource required by the fork OAuth server.

The access token, pending verifier, and state are stored only in the current tab's `sessionStorage`. Pending authorization state expires after ten minutes. **Sign out** removes the browser token immediately, and closing the tab removes all tab-scoped OAuth state. The expandable manual-token form remains available for troubleshooting and existing tokens.

The OAuth approval page still requires the configured admin PIN. Configure `base_url` to the externally reachable origin before using the UI through a reverse proxy or public hostname, so issuer and resource validation match the browser-visible deployment.

Native clients use a separate private token stored at:

```text
<state_dir>/ui/local-token
```

The file is created with mode `0600`. This token bypasses OAuth only when both conditions hold:

1. the request targets `/api/ui`;
2. the transport peer itself is a loopback address.

Forwarded headers are ignored, so a reverse proxy connected over loopback does not grant this bypass to remote users. Browser terminal WebSockets never accept the private loopback token: in OAuth mode they require a valid bearer token with both `shell:read` and `shell:execute` scopes.

## Terminals

The **Terminals** panel manages the same tmux-backed persistent shells exposed by the MCP shell tools. A browser can create a shell, select an existing shell, submit commands, resize the tmux window, and terminate a selected shell. The server streams bounded `capture-pane` snapshots every 250 ms only when output changes.

The browser sends ordered JSON controls over:

```text
<ui_path>/ws/terminals/<shell_id>
```

The OAuth access token is transported as a base64url-encoded WebSocket subprotocol credential; the server accepts only the non-secret `lsm-ui-terminal` subprotocol, so the bearer credential is not echoed back. Missing authentication closes with code `4401`, missing shell scopes with `4403`, invalid controls with `4400`, missing shells with `4404`, idle connections with `4408`, and connection-capacity exhaustion with `4429`.

Terminal input and resize controls are processed in receive order. Individual messages are limited to 64 KiB, snapshots are limited to 5,000 lines, dimensions reuse the persistent-shell bounds, and each browser sends a heartbeat every 30 seconds. Closing or reloading the browser disconnects the WebSocket but deliberately leaves the tmux shell running; use **Kill selected** when the shell itself should terminate.

The current renderer displays normalized full-pane text snapshots rather than a raw PTY byte stream. Interactive command workflows work now, while alternate-screen applications, exact ANSI styling, mouse protocols, and remote-machine terminals remain queued with the xterm/OpenTUI migration.

## Files

The **Files** panel browses the local workspace used by the server. Directory entries are sorted with directories first, hidden entries can be toggled, double-clicking or **Open** enters a directory, and the path field plus **Up** button provide direct navigation. Directory previews are themselves navigable, so selecting a child from the preview opens its containing directory and keeps that child selected.

Read-only file routes require `shell:read`. Creating, replacing, copying, moving, renaming, or deleting entries additionally requires `shell:write`. The browser surface stays confined to `workspace_root` even when the server-wide `allow_full_control` setting is enabled; that setting does not turn the Human UI into an unrestricted host filesystem browser.

The built-in preview supports:

- directory entries, bounded to 1,000 items;
- UTF-8 text, bounded to the first 400 lines and the configured file-read byte limit;
- a 256-byte hexadecimal sample for binary files;
- inline AVIF, BMP, GIF, JPEG, PNG, and WebP images that fit the configured file-read byte limit.

SVG is intentionally rendered as text instead of an inline image, preventing active SVG content from executing in the browser. Images above the byte limit produce metadata and an explanatory message rather than an oversized data URL.

**Edit** loads the complete bounded UTF-8 file. Binary files and files truncated by `max_file_read_bytes` are refused rather than silently saving a partial document. Saves reuse the normal file operation path: existing modes are preserved, writes use same-directory atomic replacement and path locking, command/path restrictions remain active, and the event loop is not blocked by disk operations. **New file** uses create-only semantics, so it will not overwrite an existing path.

Deletion is explicit and confirmed in the browser. The workspace root itself cannot be deleted. Deleting a symbolic link removes the selected link entry without deleting its target. Recursive deletion is requested only for selected directories.

**Copy**, **Move**, and **Rename** work with regular files, directories, and symbolic links. They never replace an existing destination. Directory copies preserve symbolic links as links instead of traversing their targets, and copying or moving a directory into its own subtree is rejected. Source and destination paths are serialized through the shared cross-thread and cross-process path-lock registry.

Moves and renames use the operating system rename operation when source and destination share a filesystem. If the operating system reports a cross-device move, the server copies the entry without following symbolic links and removes the source only after the copy completes. A failed source removal rolls back the copied destination. Regular-file copies use exclusive destination creation, preserve file metadata, flush the copied data, and reject a source that changes while it is being read.

Selection and preview requests use generation guards. A slow response for an earlier selection is ignored, periodic dashboard refreshes retain the current selection without reloading its preview, and signing out invalidates pending file work.

The current Files panel is local-only. Remote-worker files, richer binary viewers, and the native OpenTUI Files screen remain in the follow-up migration queue.

## Configuration

```yaml
ui_enabled: true
ui_path: /ui
ui_terminal_idle_timeout_s: 3600
ui_terminal_max_connections: 8
```

Equivalent environment variables are:

```bash
LOCAL_SHELL_MCP_UI_ENABLED=true
LOCAL_SHELL_MCP_UI_PATH=/ui
LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S=3600
LOCAL_SHELL_MCP_UI_TERMINAL_MAX_CONNECTIONS=8
```

`ui_path` must be a non-root URL path. Paths reserved by the MCP, OAuth, remote-worker, download, health, documentation, and Human UI API surfaces are rejected. Set `ui_terminal_idle_timeout_s` to `0` to disable idle expiry; negative values are rejected. `ui_terminal_max_connections` must be between `1` and `128`.

Disable the browser surface completely with:

```bash
LOCAL_SHELL_MCP_UI_ENABLED=false
```

## Security notes

Do not run `auth_mode: none` on a public or shared network. The Human UI can create shells and execute arbitrary terminal input with the server account's permissions, so it inherits the same deployment trust requirements as the REST and MCP surfaces.

Automatic OAuth sign-in requires a secure browser context for Web Crypto. HTTPS and localhost satisfy this requirement in supported browsers. The browser refuses to start PKCE when secure randomness or SHA-256 Web Crypto is unavailable.

The browser shell sets a restrictive Content Security Policy, disallows framing, avoids inline scripts, validates callback issuer and state values, and serves assets with MIME sniffing disabled.
