# Human interface

The HTTP server includes the canonical packaged browser Human UI at `/ui` by default. The native browser interface remains the default cross-platform surface. An optional OpenTUI client uses the same authenticated Human UI API from a terminal, either as a release/Docker sidecar, from source with Bun, or through the browser's separate OpenTUI Console panel. Yazi is not required.

## Start the HTTP server

```bash
local-shell-mcp --mode http
```

Open the URL formed from the configured host and port, for example:

```text
http://127.0.0.1:8765/ui
```

## OpenTUI client

Keep the HTTP service running, then launch the optional native terminal interface in another terminal:

```bash
local-shell-mcp tui
```

The CLI defaults to the configured loopback API at `http://127.0.0.1:<port>/api/ui`. A different loopback port or HTTPS endpoint can be selected explicitly:

```bash
local-shell-mcp tui --api-base https://localhost:9443/api/ui
```

`--api-base` accepts only a credential-free loopback HTTP(S) URL with the exact `/api/ui` path. The mode-`0600` local UI token is passed to the OpenTUI process through its environment and never appears in the command line. Resolution order is: an administrator-configured `ui_tui_command`, a platform sidecar beside the installed executable, a release/runtime sidecar, an optional embedded payload, then the checked-out `ui-opentui/src/tui.tsx` source when Bun is available.

Official release archives and Docker images build a platform-native `local-shell-mcp-tui` sidecar. Source distributions include the TypeScript/TSX source and lockfile but exclude `node_modules` and generated binaries. The ordinary Python wheel remains platform-independent; a source checkout can run or compile OpenTUI with:

```bash
cd ui-opentui
bun install --frozen-lockfile
bun run typecheck
bun test
bun run build:tui
```

The browser also exposes an optional **OpenTUI Console** when a runtime is available. It is separate from the native Dashboard, Remotes, Terminals, Files, Todos, and Audit panels: xterm connects to an authenticated `<ui_path>/ws/opentui` WebSocket, the server starts a private PTY/ConPTY OpenTUI process, and that process talks back to the loopback Human UI API. Closing the console terminates only that OpenTUI process. A clean process exit closes normally; a non-zero exit closes the WebSocket abnormally so the browser reconnect policy can recover the console.

The current migration slice provides:

- a packaged responsive browser shell;
- runtime and package version information;
- local and remote machine inventory;
- process-scoped local and remote Dashboard telemetry with degraded-source alerts;
- OAuth-scoped remote worker inventory, one-time enrollment invitations, rename, and revocation;
- automatic browser OAuth Authorization Code flow with PKCE S256;
- machine-isolated local and remote persistent-terminal listing, creation, raw PTY streaming, xterm rendering, snapshot fallback, input, resize, command history, and termination;
- machine-aware local and remote file browsing, bounded previews, text editing, creation, and deletion;
- local workspace copy, move, and rename operations;
- revision-guarded local and remote Todo lists with machine isolation;
- filtered local and remote Audit records with scope-sensitive details and bounded native image previews;
- OAuth-protected Human UI APIs and terminal WebSockets;
- a private loopback-only token path for trusted local/native automation clients;
- safe lightweight syntax highlighting for bounded Files previews and Audit JSON;
- configurable UI enablement, mount path, and local-only wallpaper mode.

The browser-native controls remain the default interface on Linux, macOS, and Windows. OpenTUI is an optional second client built from the adapted upstream React/OpenTUI sources; it reuses the fork's API, OAuth boundaries, remote-worker dispatch, tmux, and ConPTY implementations. Yazi remains intentionally absent because Files operations are performed through the authenticated API rather than a shell-launched file manager.

## Authentication

The HTML, CSS, and JavaScript shell is public so a browser can load the authentication experience. Human UI API routes under `/api/ui` follow the normal server authentication mode.

With `auth_mode: oauth`, select **Sign in with OAuth**. The browser:

1. dynamically registers the exact `<origin><ui_path>/callback` redirect URI;
2. creates a cryptographically random PKCE verifier and OAuth `state` value;
3. requests approval using `code_challenge_method=S256` and the server-advertised scope and resource;
4. verifies both `state` and the authorization response `iss` value;
5. exchanges the code while including the resource required by the fork OAuth server.

The access token, pending verifier, and state are stored only in the current tab's `sessionStorage`. Pending authorization state expires after ten minutes. **Sign out** removes the browser token immediately, and closing the tab removes all tab-scoped OAuth state. An HTTP `401` clears the invalid token and returns to authentication; an HTTP `403` preserves the valid session and displays the missing-scope detail so a deliberately reduced token does not look expired. Remote enrollment commands are handled separately: the one-time command exists only in memory and the result dialog while visible, is never written to browser storage, and is cleared when the dialog closes, the user signs out, or the page unloads. The expandable manual-token form remains available for troubleshooting and existing tokens.

The OAuth approval page still requires the configured admin PIN. Configure `base_url` to the externally reachable origin before using the UI through a reverse proxy or public hostname, so issuer and resource validation match the browser-visible deployment.

Native clients use a separate private token stored at:

```text
<state_dir>/ui/local-token
```

The file is created with mode `0600`. This token bypasses OAuth only when both conditions hold:

1. the request targets `/api/ui`;
2. the transport peer itself is a loopback address.

Forwarded headers are ignored, so a reverse proxy connected over loopback does not grant this bypass to remote users. Browser terminal WebSockets never accept the private loopback token: in OAuth mode they require a valid bearer token with both `shell:read` and `shell:execute` scopes, plus `remote:use` when the selected machine is remote.

## Dashboard

The **Dashboard** panel displays one process-scoped telemetry snapshot for the selected machine. The local server samples its own host and process environment, while an online remote worker returns the same schema through the native `dashboard_snapshot` RPC. Dashboard requests do not create or reuse Files/Todos workspace sessions, never carry a `session_id`, and do not construct remote shell commands. Local reads require `shell:read`; a remote selection additionally requires `remote:use`.

The snapshot includes CPU utilization and count, memory pressure, workspace-filesystem usage, one-minute load, aggregate non-loopback network receive/transmit rates, host uptime, runtime/package version information, and metadata-only Audit activity from the previous 24 hours. CPU and network rates are derived from interval samples. Unsupported or unreadable telemetry remains `null` and renders as `—`; the browser never converts a missing source into a false zero. The server bounds alerts and activity to twelve rows each, validates finite numeric values and encoded text lengths, and rejects malformed worker payloads before returning them to the browser.

Audit contributes only tool/event names, operation categories, timestamps, status, and duration. Dashboard responses never contain Audit `input`, `output`, `error`, session payloads, or child-event details. Failed recent calls produce a summary alert that directs an authorized operator to the Audit panel for details. Disk usage at 85% and memory usage at 90% produce warnings; disk usage at 95% and memory usage at 98% produce critical alerts. If the Audit store cannot be queried, system telemetry remains available and the source is marked degraded instead of failing the whole Dashboard.

The browser polls the selected machine every five seconds and retains at most sixty in-tab samples for lightweight CPU, memory, disk, and network sparklines. Machine switches and sign-out increment a generation guard so a slow response from a previously selected worker cannot overwrite the active panel. Inventory refreshes preserve an online selection and immediately fall back to local if the worker becomes unavailable. Wide layouts use separate system, alert, and activity columns; medium and narrow layouts collapse to two and one column. Long alert titles, details, and timestamps are independently bounded and wrapped so they cannot overlap adjacent rows.

All browser Dashboard text is assigned through `textContent`; sparklines are created with explicit SVG `polyline` nodes and numeric attributes. Telemetry text is never interpreted as HTML, SVG markup, or script. OpenTUI renders the same normalized telemetry with terminal-native panels and bounded charts; neither client interprets worker text as markup.

## Remotes

The **Remotes** panel manages the durable worker control-plane registry rather than a workspace session. Listing, creating an enrollment invitation, renaming, and revoking all require `remote:use`; these routes do not accept or create a Files/Todos `session_id`. When remote workers are disabled, the list route returns an empty inventory with `enabled=false`, while invitation, rename, and revoke requests return a conflict instead of silently enabling the feature.

The inventory shows online/offline status, last-seen age and timestamp, queue depth, workdir, advertised capabilities, and a bounded allowlist of worker metadata: local-shell-mcp version, hostname, user, Python version, platform, current directory, and reported workdir. Arbitrary worker `info` keys, credentials, invite codes, registry paths, and connection tokens are never returned. The server caps the response at 1,024 workers, rejects duplicate machine identities and unsupported statuses, validates finite timestamps and non-negative queue counts, bounds every encoded text field, de-duplicates capabilities, and recomputes online/offline/total counts instead of trusting stored aggregates. Workers now advertise their local-shell-mcp version during enrollment and heartbeat registration so mixed-version fleets are visible.

**New invite** creates one enrollment capability with an optional machine name, optional starting workdir, and a lifetime between 60 seconds and 24 hours. The existing manager also bounds pending invitations to 1,024 and consumes each code only once. The Human UI response deliberately omits the raw code and join URL and returns only the ready-to-run command plus its expiration. The command is displayed as inert text, is not written to browser storage or Audit, and is cleared from memory and the document when the result closes, authentication ends, or the page unloads. Clipboard access occurs only after the operator selects **Copy command**.

Renaming changes the durable worker identity and refreshes every machine selector after success. Revocation removes the persisted worker registration, disconnects the current worker, invalidates its credential for future reconnects, and cancels outstanding work assigned to that machine. Both operations are explicit dialog submissions and produce metadata-only Audit events without worker secrets.

The browser polls the control-plane inventory every four seconds with an independent generation guard, preserves a still-valid selected worker, and prevents a stale response from replacing newer state. Worker-provided text is assigned only through `textContent`; status styling is restricted to the fixed online/offline classes. Wide layouts use a list/detail split, while narrow screens collapse to one column and stack destructive-action controls. OpenTUI provides the same invite, rename, revoke, mouse, keyboard, and responsive list/detail workflows through the shared API.

## Terminals

The **Terminals** panel manages the same platform-native persistent shells exposed by the MCP shell tools on one selected local or remote machine. POSIX hosts retain the tmux backend; Windows hosts use pywinpty-backed ConPTY sessions. A browser can list, create, select, interact with, resize, inspect, and terminate a shell. The control server verifies the selected worker and shell first, then treats `(machine, shell_id)` as the durable identity; two machines may safely use the same shell ID without sharing browser state.

The browser always opens its authenticated WebSocket to the control server rather than directly to a worker:

```text
<ui_path>/ws/terminals/<shell_id>?machine=<machine>&mode=auto&cols=<cols>&rows=<rows>
```

`mode=auto` negotiates a connection-scoped raw PTY bridge when the selected machine supports either POSIX PTYs or Windows ConPTY. The first text message is a bounded `ready` control containing only the machine, shell, selected mode, and backend. In PTY mode, all terminal output after `ready` is sent as binary WebSocket frames, and xterm input is returned as binary frames. Resize, ping, and close remain ordered JSON controls. An older remote worker or a host without the required PTY implementation falls back to the existing snapshot protocol. Clients that omit `mode` retain the original snapshot-only message sequence without a new negotiation event.

On POSIX, the server opens a fresh PTY and runs `tmux attach-session` inside it. That attach client is short lived and belongs only to the WebSocket connection; the underlying tmux shell remains persistent. On Windows, one pywinpty process owns each persistent ConPTY shell. A dedicated daemon reader thread drains that process into a bounded one-megabyte snapshot tail and fans the same normalized UTF-8 stream out to an exclusive raw subscriber. Closing the subscriber does not close the ConPTY process, and a reader failure force-closes and removes the unusable session instead of leaving a stale registry entry.

A remote PTY uses five internal, allowlisted worker RPCs: `open_terminal_bridge`, `read_terminal_bridge`, `write_terminal_bridge`, `resize_terminal_bridge`, and `close_terminal_bridge`. The worker returns an opaque random bridge capability only to the control server. The browser never receives that capability, a worker address, worker credentials, or a direct worker WebSocket, and none of these RPCs create or carry a Files/Todos `session_id`.

Raw bridges are exclusive per `(machine, shell_id)` so two Human UI clients cannot race terminal input into the same persistent shell. Open and pending bridges also count against the configured Human UI terminal connection limit. Shell IDs, bridge capabilities, dimensions, read waits, base64 envelopes, byte counts, backends, and remote response identities are independently validated. A valid bounded poll may contain an empty payload with `bytes=0` and `eof=false`; it keeps the bridge connected. Raw reads and writes are limited to 64 KiB per operation; larger browser paste events are split into ordered 64 KiB frames. POSIX writes retry partial and temporarily blocked writes until the complete bounded chunk has been delivered in order. ConPTY input uses an incremental UTF-8 decoder so a multibyte character split across frames is not corrupted, retries temporarily blocked writes, and accepts every non-negative pywinpty queued-write result, including zero. If a pywinpty build does not expose `setwinsize`, resize returns `resized=false` without disconnecting the terminal.

Each ConPTY raw subscriber is independently bounded to one megabyte and begins with the current snapshot tail so xterm receives existing context before future output. Overflow preserves the newest bounded tail, marks only that raw stream as finished, and leaves the persistent shell available for snapshot reads or a later attachment. A malformed remote open response with a valid capability is closed immediately; a worker bridge that loses its controller polling lease is reaped within at most five minutes.

The bundled browser terminal uses pinned `@xterm/xterm 5.5.0`, `@xterm/addon-fit 0.10.0`, and the matching `@xterm/addon-image 0.8.0`. The committed JavaScript and CSS are generated reproducibly from `ui-terminal/package-lock.json`, have no source map or external font dependency, ship with the corresponding license text, and include their build source and tests in the sdist without `node_modules`. xterm provides cursor addressing, alternate-screen applications, scrollback, full keyboard input, UTF-8, 16/256/true color, and terminal resize semantics. FitAddon measures the visible pane and sends the resulting rows and columns only after protocol negotiation completes.

Both the native browser terminal and optional browser OpenTUI Console decode Sixel and iTerm inline-image protocol output through the official xterm addon. Each image is limited to 16,777,216 decoded pixels; Sixel input is limited to 25,000,000 bytes, iTerm input to 20,000,000 bytes, and retained image storage to 64 MB with oldest-image eviction. Placeholder rendering is disabled. The addon recognizes bounded PNG, JPEG, GIF, iTerm IIP, and Sixel data and renders it to a canvas layer; terminal output is never interpreted as HTML, SVG, or script. The OpenTUI PTY advertises `xterm-256color`, true color, and the VS Code/xterm.js program surface so compatible applications can choose iTerm IIP or Sixel automatically. Because xterm creates runtime style elements, canvas layers, and a bounded inline Wasm decoder for Sixel, the page CSP permits inline styles and `wasm-unsafe-eval` while keeping scripts restricted to same-origin files and never enabling general `unsafe-eval`. OSC 8 hyperlink controls are consumed before the native terminal records them, and its no-op link handler remains as defense in depth, so terminal output cannot navigate the browser.

The snapshot fallback remains available for compatibility and unsupported workers. The public MCP and HTTP `read_persistent_shell_output` tool continues to return plain text by default. The Human UI snapshot path privately requests `preserve_ansi=true`: POSIX captures tmux escape sequences, while ConPTY reads its bounded shared tail. Plain ConPTY reads strip OSC, CSI, DCS, APC, PM, SOS, and NUL controls before returning text. The bounded inert browser renderer creates only text nodes and fixed-class spans and preserves its scroll-freeze, **Jump to latest**, and pending-update behavior.

The command field keeps at most 100 consecutive-de-duplicated commands in the current tab and current terminal connection. In snapshot mode Arrow Up and Arrow Down navigate that list while preserving the unsent draft. In PTY mode xterm owns the keyboard directly, while the touch-friendly key bar sends only fixed Escape, Tab, Arrow Up, Arrow Down, Ctrl-C, and Ctrl-D byte sequences through the currently negotiated socket. No terminal input or history is written to browser storage.

HTTP list/read operations require `shell:read`; start/send/resize/kill require `shell:read` and `shell:execute`; every remote operation additionally requires `remote:use`. Browser terminal WebSockets require both shell scopes, plus `remote:use` for a remote machine. The bearer token remains a base64url WebSocket subprotocol credential and is never echoed. Missing authentication closes with `4401`, missing scopes with `4403`, invalid controls with `4400`, missing shells with `4404`, unsupported explicitly required PTY mode with `4406`, idle connections with `4408`, an already attached raw shell with `4409`, unavailable remote workers with `1013`, and connection-capacity exhaustion with `4429`.

The browser retains separate list and socket generation guards, includes the selected machine in every request, closes the previous socket on a machine or shell change, and does not enable input until a `ready` or compatible first snapshot has selected the protocol. Closing, reloading, signing out, or losing the connection terminates only the raw attachment and releases its capability; it deliberately leaves the tmux or ConPTY persistent shell running. Use **Kill selected** when the persistent shell itself should terminate. OpenTUI lists and operates the same persistent shell inventory through `/api/ui/terminals`; the optional browser Console PTY is separate and is terminated when that console closes.

## Files

The **Files** panel has a machine selector for the server's local workspace and each currently online remote worker. Directory entries are sorted with directories first, hidden entries can be toggled, double-clicking or **Open** enters a directory, and the path field plus **Up** button provide direct navigation. Directory previews are themselves navigable, so selecting a child from the preview opens its containing directory and keeps that child selected. Offline and revoked workers remain visible in inventory but cannot be selected for file work.

Read-only local routes require `shell:read`. Remote reads additionally require `remote:use`. Creating, replacing, or deleting entries requires `shell:write`, plus `remote:use` for a remote machine. The local browser surface stays confined to `workspace_root` even when the server-wide `allow_full_control` setting is enabled; that setting does not turn the Human UI into an unrestricted host filesystem browser.

For each remote machine, the server lazily creates and caches one explicit worker workspace session rooted at the worker's advertised workdir. Every remote file RPC carries that session ID. If a worker restarts and rejects the cached session, the UI recreates it and retries the operation once. Remote requests are capped at 60 seconds and use the existing worker allowlist rather than constructing shell commands.

Remote UI paths are portable workspace-relative paths. Absolute POSIX paths, UNC paths, drive-qualified paths, home-expansion forms, NUL bytes, and `..` components are rejected before dispatch. The worker resolves every path against the workspace session again, including a second containment check after following symbolic links, so a link cannot be used to read outside the remote workdir.

The built-in preview supports:

- directory entries, bounded to 1,000 items;
- UTF-8 text, bounded to the first 400 lines and the configured file-read byte limit, with safe lightweight syntax highlighting for recognized extensions and media types;
- a 256-byte hexadecimal sample for binary files;
- inline AVIF, BMP, GIF, JPEG, PNG, and WebP images that fit the configured file-read byte limit.

Remote file bytes are fetched through the existing transfer RPC in chunks of at most 256 KiB. Every chunk is checked for the requested offset, returned length, total file size, progress, early EOF, and SHA-256 digest. A size change, malformed payload, corrupt digest, or stalled transfer aborts the preview. Truncated text prefixes use incremental UTF-8 decoding, so a byte limit that splits a multibyte character does not turn valid text into binary or insert a replacement character. Filenames containing selector-like text such as `name:raw` remain literal because remote previews and editor reads use raw transfer chunks instead of the text-selector parser.

SVG is intentionally rendered as text instead of an inline image, preventing active SVG content from executing in the browser. Images above the byte limit produce metadata and an explanatory message rather than an oversized data URL.

**Edit** loads the complete bounded UTF-8 file. Binary files and files above `max_file_read_bytes` are refused rather than silently saving a partial document. The response includes the SHA-256 digest of the exact file revision. OpenTUI sends that digest when saving; local and remote writes compare it under the existing path lock and reject stale editors instead of overwriting a concurrent change. Local saves reuse the normal atomic file operation path with mode preservation, while remote saves reuse the worker's session-bound `write_file` primitive. **New file** uses create-only semantics locally and remotely, so it will not overwrite an existing path.

Deletion is explicit and confirmed in the browser. Neither the local nor a remote workspace root can be deleted. Deleting a symbolic link removes the selected link entry without deleting its target. Recursive deletion is requested only for selected directories.

Local **Copy**, **Move**, and **Rename** work with regular files, directories, and symbolic links. They never replace an existing destination. Directory copies preserve symbolic links as links instead of traversing their targets, and copying or moving a directory into its own subtree is rejected. Source and destination paths are serialized through the shared cross-thread and cross-process path-lock registry.

Local moves and renames use the operating system rename operation when source and destination share a filesystem. If the operating system reports a cross-device move, the server copies the entry without following symbolic links and removes the source only after the copy completes. A failed source removal rolls back the copied destination. Regular-file copies use exclusive destination creation, preserve file metadata, flush the copied data, and reject a source that changes while it is being read.

Remote copy, move, rename, and directory creation remain disabled because the current worker allowlist has no corresponding primitives. Both browser and OpenTUI report these capabilities explicitly and do not emulate them with remote shell commands. Cross-workspace movement uses the explicit session transfer tools. Local OpenTUI Files additionally supports API-backed directory creation, revision-guarded editing, and bounded terminal-native image previews.

List and preview requests use generation and machine guards. Switching machines invalidates the previous path, selection, editor, preview, and pending directory request; a slow response from an earlier machine cannot overwrite the active workspace. Periodic dashboard refreshes preserve an online current machine and selection, fall back to local immediately if a worker becomes unavailable, and signing out invalidates pending file work.

## Todos

The **Todos** panel edits the structured Todo list owned by one explicit Human UI workspace session. The local server reuses one session rooted at `workspace_root`; each remote worker reuses the same lazily created per-machine workspace session used by remote Files. Todo data is therefore isolated by machine and by worker session, while terminal shell IDs remain a separate namespace.

Local reads require `shell:read`, and local replacements additionally require `shell:write`. Remote reads require `shell:read` plus `remote:use`; remote replacements additionally require `shell:write`. Remote Todo operations use the worker's native `read_todos` and `write_todos` RPC handlers with the same 60-second timeout and stale-session recreate-and-retry behavior as remote Files. The UI never constructs remote shell commands to emulate Todo storage.

Each persisted list has a monotonic non-negative `revision`. The browser sends the revision it loaded as `expected_revision` when replacing the list. The server performs the comparison and replacement while holding the shared path lock, writes a mode-`0600` temporary file in the same state directory, flushes it, and publishes it with `os.replace`. A competing writer advances the revision first, causing the stale replacement to fail with HTTP `409`; the browser then reloads the current list instead of overwriting it. Existing Todo files without a revision remain readable as revision zero.

Todo count and serialized-byte limits reuse `max_todos` and `max_todo_bytes`. The Human UI additionally bounds machine names, item IDs, content, status, and priority fields by encoded byte length and rejects duplicate IDs or malformed item shapes. A save disables machine selection and row controls until completion. Machine switches reset list state and increment a request generation, so a slow response from a previous machine cannot replace the active list. Periodic inventory refreshes do not overwrite unsaved edits, and offline or revoked workers remain visible but cannot be selected.

The browser and OpenTUI support filtering open and completed items, adding and removing rows, and editing content, status, and priority. Both clients use revision-guarded writes; their list areas remain height-bounded and usable across narrow and wide layouts.

## Audit

The **Audit** panel reads the private process-level JSONL log for one selected machine. Unlike Files and Todos, Audit data is not owned by a workspace session: the local server reads its own process log, while a remote worker serves its own log through native `query_audit` and `get_audit_entry` RPC handlers. Remote requests therefore carry no Files/Todos `session_id`, use the existing worker allowlist, require an online exact machine match, and are capped at 60 seconds. The UI never constructs remote shell commands or copies remote log files to emulate Audit access.

The query path reads a consistent bounded tail while holding the same cross-process transaction lock used by Audit append and retention. It examines at most 4 MB and returns at most 2,000 coalesced rows. Malformed JSONL lines are skipped. Stored `tool_call_start` and `tool_call_end` events remain explicit on disk for retention integrity, while the Human UI query pairs them by `call_id` (or a legacy tool/node/session key), preserves unpaired rows, and folds semantic `parent_call_id` events into the displayed call without deleting their source records. Routine `auth_ok` events are hidden so polling the authenticated UI does not create an ever-growing visible feedback loop.

Lists require `shell:read`; selecting a remote machine additionally requires `remote:use`. Full details are authorized again based on the actual operation: file mutations require `shell:write`, shell and job activity require `shell:execute`, shared-file activity requires `file:share`, Git writes require `git:write`, and remote activity requires `remote:use`. Unknown operation types require the complete supported scope set rather than guessing a weaker permission. This second check prevents a read-only token from using the list endpoint to retrieve command, mutation, sharing, or remote-operation payloads.

The list response is metadata-only: it includes stable identifiers, timestamps, operation, tool, status, duration, session, and lifecycle counts, but excludes `input`, `output`, `error`, and child-event payloads. Free-text search is limited to the same summary metadata, so a read-only token cannot use match/no-match behavior to probe protected payload content. The browser can also filter by operation, event text, session, order, and result limit. Machine and detail requests carry independent generation guards, so a slow response from a previous worker or selection cannot overwrite the active panel. Inventory refreshes preserve an online selection and fall back to local when a worker becomes unavailable. Both the list and detail areas are height-bounded and scrollable on narrow and wide layouts.

Audit fields are normalized through the shared portability, byte-budget, and credential-redaction boundary before they reach the JSONL log. The browser renders JSON with a dependency-free tokenizer that creates only text nodes and fixed-class spans; OpenTUI uses a terminal-native highlighter. Stored HTML, SVG, or script-like text is never interpreted as active markup. For `view_image` records, the detail endpoint removes the original inline MCP image field, validates base64, byte limits, and PNG/JPEG/GIF/WebP magic, and preserves the bounded browser preview. When OpenTUI supplies a viewport, Pillow also decodes a first-frame RGBA thumbnail with strict source-pixel and output-dimension limits. Invalid, oversized, or undecodable image payloads produce an isolated preview error while the sanitized Audit detail remains readable.

## Configuration

```yaml
ui_enabled: true
ui_path: /ui
ui_tui_command: null
ui_terminal_idle_timeout_s: 3600
ui_terminal_max_connections: 8
ui_wallpaper: aurora
```

Equivalent environment variables are:

```bash
LOCAL_SHELL_MCP_UI_ENABLED=true
LOCAL_SHELL_MCP_UI_PATH=/ui
# Optional override; normally release sidecar or Bun source discovery is automatic.
# LOCAL_SHELL_MCP_UI_TUI_COMMAND=/opt/local-shell-mcp-tui
LOCAL_SHELL_MCP_UI_TERMINAL_IDLE_TIMEOUT_S=3600
LOCAL_SHELL_MCP_UI_TERMINAL_MAX_CONNECTIONS=8
LOCAL_SHELL_MCP_UI_WALLPAPER=aurora
```

`ui_path` must be a non-root URL path. Paths reserved by the MCP, OAuth, remote-worker, download, health, documentation, and Human UI API surfaces are rejected. `ui_tui_command` is an administrator-controlled argv string used only when explicitly configured; do not point it at untrusted content. Set `ui_terminal_idle_timeout_s` to `0` to disable idle expiry; negative values are rejected. `ui_terminal_max_connections` must be between `1` and `128` and is shared by persistent-terminal attachments and browser OpenTUI Console processes. `ui_wallpaper` accepts `aurora`, `grid`, or `none`; all three are local CSS treatments and never fetch an image or send browser context to a third party.

Disable the browser surface completely with:

```bash
LOCAL_SHELL_MCP_UI_ENABLED=false
```

## Security notes

Do not run `auth_mode: none` on a public or shared network. The Human UI and OpenTUI can create shells and execute arbitrary terminal input with the server account's permissions, so they inherit the same deployment trust requirements as the REST and MCP surfaces. The browser OpenTUI Console requires the same OAuth shell scopes as browser terminals and never receives the private local token; only the server-spawned PTY child gets that token in its environment for loopback API calls.

Automatic OAuth sign-in requires a secure browser context for Web Crypto. HTTPS and localhost satisfy this requirement in supported browsers. The browser refuses to start PKCE when secure randomness or SHA-256 Web Crypto is unavailable.

The browser shell sets a restrictive Content Security Policy, disallows framing, avoids inline scripts, validates callback issuer and state values, and serves assets with MIME sniffing disabled.
