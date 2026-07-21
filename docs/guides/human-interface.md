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
- process-scoped local and remote Dashboard telemetry with degraded-source alerts;
- OAuth-scoped remote worker inventory, one-time enrollment invitations, rename, and revocation;
- automatic browser OAuth Authorization Code flow with PKCE S256;
- machine-isolated local and remote tmux terminal listing, creation, input, resize, snapshots, and termination;
- machine-aware local and remote file browsing, bounded previews, text editing, creation, and deletion;
- local workspace copy, move, and rename operations;
- revision-guarded local and remote Todo lists with machine isolation;
- filtered local and remote Audit records with scope-sensitive details;
- OAuth-protected Human UI APIs and terminal WebSockets;
- a private loopback-only token path for future native OpenTUI clients;
- configurable UI enablement and mount path.

Rich xterm-compatible rendering and the native OpenTUI executable remain in the explicit follow-up migration queue.

## Authentication

The HTML, CSS, and JavaScript shell is public so a browser can load the authentication experience. Human UI API routes under `/api/ui` follow the normal server authentication mode.

With `auth_mode: oauth`, select **Sign in with OAuth**. The browser:

1. dynamically registers the exact `<origin><ui_path>/callback` redirect URI;
2. creates a cryptographically random PKCE verifier and OAuth `state` value;
3. requests approval using `code_challenge_method=S256` and the server-advertised scope and resource;
4. verifies both `state` and the authorization response `iss` value;
5. exchanges the code while including the resource required by the fork OAuth server.

The access token, pending verifier, and state are stored only in the current tab's `sessionStorage`. Pending authorization state expires after ten minutes. **Sign out** removes the browser token immediately, and closing the tab removes all tab-scoped OAuth state. Remote enrollment commands are handled separately: the one-time command exists only in memory and the result dialog while visible, is never written to browser storage, and is cleared when the dialog closes, the user signs out, or the page unloads. The expandable manual-token form remains available for troubleshooting and existing tokens.

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

All Dashboard text is assigned through `textContent`; sparklines are created with explicit SVG `polyline` nodes and numeric attributes. Telemetry text is never interpreted as HTML, SVG markup, or script. The native OpenTUI Dashboard and its exact chart rendering remain deferred.

## Remotes

The **Remotes** panel manages the durable worker control-plane registry rather than a workspace session. Listing, creating an enrollment invitation, renaming, and revoking all require `remote:use`; these routes do not accept or create a Files/Todos `session_id`. When remote workers are disabled, the list route returns an empty inventory with `enabled=false`, while invitation, rename, and revoke requests return a conflict instead of silently enabling the feature.

The inventory shows online/offline status, last-seen age and timestamp, queue depth, workdir, advertised capabilities, and a bounded allowlist of worker metadata: local-shell-mcp version, hostname, user, Python version, platform, current directory, and reported workdir. Arbitrary worker `info` keys, credentials, invite codes, registry paths, and connection tokens are never returned. The server caps the response at 1,024 workers, rejects duplicate machine identities and unsupported statuses, validates finite timestamps and non-negative queue counts, bounds every encoded text field, de-duplicates capabilities, and recomputes online/offline/total counts instead of trusting stored aggregates. Workers now advertise their local-shell-mcp version during enrollment and heartbeat registration so mixed-version fleets are visible.

**New invite** creates one enrollment capability with an optional machine name, optional starting workdir, and a lifetime between 60 seconds and 24 hours. The existing manager also bounds pending invitations to 1,024 and consumes each code only once. The Human UI response deliberately omits the raw code and join URL and returns only the ready-to-run command plus its expiration. The command is displayed as inert text, is not written to browser storage or Audit, and is cleared from memory and the document when the result closes, authentication ends, or the page unloads. Clipboard access occurs only after the operator selects **Copy command**.

Renaming changes the durable worker identity and refreshes every machine selector after success. Revocation removes the persisted worker registration, disconnects the current worker, invalidates its credential for future reconnects, and cancels outstanding work assigned to that machine. Both operations are explicit dialog submissions and produce metadata-only Audit events without worker secrets.

The browser polls the control-plane inventory every four seconds with an independent generation guard, preserves a still-valid selected worker, and prevents a stale response from replacing newer state. Worker-provided text is assigned only through `textContent`; status styling is restricted to the fixed online/offline classes. Wide layouts use a list/detail split, while narrow screens collapse to one column and stack destructive-action controls. The native OpenTUI Remotes screen remains deferred.

## Terminals

The **Terminals** panel manages the same tmux-backed persistent shells exposed by the MCP shell tools on one selected local or remote machine. A browser can list, create, select, write to, resize, inspect, and terminate a shell. The local server executes these operations directly. For a remote machine it calls the worker's native `list_persistent_shells`, `start_persistent_shell`, `read_persistent_shell_output`, `send_persistent_shell_input`, `resize_persistent_shell`, and `kill_persistent_shell` RPCs. These calls are machine-scoped and do not create, reuse, or carry Files/Todos workspace `session_id` values.

The browser always opens its WebSocket to the control server rather than directly to a worker:

```text
<ui_path>/ws/terminals/<shell_id>?machine=<machine>&lines=<bounded-lines>
```

The control server verifies that the selected worker is still online before listing or opening a shell and treats `(machine, shell_id)` as the terminal identity. This prevents two machines with the same tmux shell name from sharing browser state or output. HTTP list/read operations require `shell:read`; start/send/resize/kill require `shell:read` and `shell:execute`; every remote operation additionally requires `remote:use`.

The OAuth access token is transported as a base64url-encoded WebSocket subprotocol credential; the server accepts only the non-secret `lsm-ui-terminal` subprotocol, so the bearer credential is not echoed back. Missing authentication closes with code `4401`, missing shell or remote scopes with `4403`, invalid controls with `4400`, missing shells with `4404`, idle connections with `4408`, unavailable remote workers with `1013`, and connection-capacity exhaustion with `4429`.

Terminal input and resize controls are processed in receive order. Individual messages are limited to 64 KiB, snapshots are limited to 5,000 lines and 4 MB, dimensions reuse the persistent-shell bounds, remote inventory is capped at 256 shells, and worker text fields and errors are bounded before browser delivery. Remote responses are validated against the same typed result models used locally; mismatched shell IDs, duplicate sessions, malformed dimensions, oversized output, and malformed worker payloads are rejected.

Local panes are sampled every 250 ms and remote panes every 750 ms; unchanged snapshots are not resent. The browser uses separate list and socket generations, includes the selected machine in every HTTP body, query, WebSocket URL, and accepted socket message, and closes the previous socket immediately on a machine switch. Inventory refreshes preserve an online selection and fall back to local if a worker becomes unavailable. Signing out clears terminal loading state and invalidates pending list/socket work.

Closing or reloading the browser disconnects the WebSocket but deliberately leaves the tmux shell running; use **Kill selected** when the shell itself should terminate. The current renderer displays normalized full-pane text snapshots rather than a raw PTY byte stream. Interactive command workflows work locally and remotely, while alternate-screen applications, exact ANSI styling, mouse protocols, Windows ConPTY parity, and native OpenTUI rendering remain queued with the richer terminal-client migration.

## Files

The **Files** panel has a machine selector for the server's local workspace and each currently online remote worker. Directory entries are sorted with directories first, hidden entries can be toggled, double-clicking or **Open** enters a directory, and the path field plus **Up** button provide direct navigation. Directory previews are themselves navigable, so selecting a child from the preview opens its containing directory and keeps that child selected. Offline and revoked workers remain visible in inventory but cannot be selected for file work.

Read-only local routes require `shell:read`. Remote reads additionally require `remote:use`. Creating, replacing, or deleting entries requires `shell:write`, plus `remote:use` for a remote machine. The local browser surface stays confined to `workspace_root` even when the server-wide `allow_full_control` setting is enabled; that setting does not turn the Human UI into an unrestricted host filesystem browser.

For each remote machine, the server lazily creates and caches one explicit worker workspace session rooted at the worker's advertised workdir. Every remote file RPC carries that session ID. If a worker restarts and rejects the cached session, the UI recreates it and retries the operation once. Remote requests are capped at 60 seconds and use the existing worker allowlist rather than constructing shell commands.

Remote UI paths are portable workspace-relative paths. Absolute POSIX paths, UNC paths, drive-qualified paths, home-expansion forms, NUL bytes, and `..` components are rejected before dispatch. The worker resolves every path against the workspace session again, including a second containment check after following symbolic links, so a link cannot be used to read outside the remote workdir.

The built-in preview supports:

- directory entries, bounded to 1,000 items;
- UTF-8 text, bounded to the first 400 lines and the configured file-read byte limit;
- a 256-byte hexadecimal sample for binary files;
- inline AVIF, BMP, GIF, JPEG, PNG, and WebP images that fit the configured file-read byte limit.

Remote file bytes are fetched through the existing transfer RPC in chunks of at most 256 KiB. Every chunk is checked for the requested offset, returned length, total file size, progress, early EOF, and SHA-256 digest. A size change, malformed payload, corrupt digest, or stalled transfer aborts the preview. Truncated text prefixes use incremental UTF-8 decoding, so a byte limit that splits a multibyte character does not turn valid text into binary or insert a replacement character. Filenames containing selector-like text such as `name:raw` remain literal because remote previews and editor reads use raw transfer chunks instead of the text-selector parser.

SVG is intentionally rendered as text instead of an inline image, preventing active SVG content from executing in the browser. Images above the byte limit produce metadata and an explanatory message rather than an oversized data URL.

**Edit** loads the complete bounded UTF-8 file. Binary files and files above `max_file_read_bytes` are refused rather than silently saving a partial document. Local saves reuse the normal atomic file operation path with mode preservation and path locking. Remote saves reuse the worker's session-bound `write_file` primitive. **New file** uses create-only semantics locally and remotely, so it will not overwrite an existing path.

Deletion is explicit and confirmed in the browser. Neither the local nor a remote workspace root can be deleted. Deleting a symbolic link removes the selected link entry without deleting its target. Recursive deletion is requested only for selected directories.

Local **Copy**, **Move**, and **Rename** work with regular files, directories, and symbolic links. They never replace an existing destination. Directory copies preserve symbolic links as links instead of traversing their targets, and copying or moving a directory into its own subtree is rejected. Source and destination paths are serialized through the shared cross-thread and cross-process path-lock registry.

Local moves and renames use the operating system rename operation when source and destination share a filesystem. If the operating system reports a cross-device move, the server copies the entry without following symbolic links and removes the source only after the copy completes. A failed source removal rolls back the copied destination. Regular-file copies use exclusive destination creation, preserve file metadata, flush the copied data, and reject a source that changes while it is being read.

Remote copy, move, and rename remain disabled because the current worker allowlist has no corresponding primitives. The UI reports these capabilities explicitly and does not emulate them with remote shell commands. Richer binary viewers and the native OpenTUI Files screen remain in the follow-up migration queue.

List and preview requests use generation and machine guards. Switching machines invalidates the previous path, selection, editor, preview, and pending directory request; a slow response from an earlier machine cannot overwrite the active workspace. Periodic dashboard refreshes preserve an online current machine and selection, fall back to local immediately if a worker becomes unavailable, and signing out invalidates pending file work.

## Todos

The **Todos** panel edits the structured Todo list owned by one explicit Human UI workspace session. The local server reuses one session rooted at `workspace_root`; each remote worker reuses the same lazily created per-machine workspace session used by remote Files. Todo data is therefore isolated by machine and by worker session, while terminal shell IDs remain a separate namespace.

Local reads require `shell:read`, and local replacements additionally require `shell:write`. Remote reads require `shell:read` plus `remote:use`; remote replacements additionally require `shell:write`. Remote Todo operations use the worker's native `read_todos` and `write_todos` RPC handlers with the same 60-second timeout and stale-session recreate-and-retry behavior as remote Files. The UI never constructs remote shell commands to emulate Todo storage.

Each persisted list has a monotonic non-negative `revision`. The browser sends the revision it loaded as `expected_revision` when replacing the list. The server performs the comparison and replacement while holding the shared path lock, writes a mode-`0600` temporary file in the same state directory, flushes it, and publishes it with `os.replace`. A competing writer advances the revision first, causing the stale replacement to fail with HTTP `409`; the browser then reloads the current list instead of overwriting it. Existing Todo files without a revision remain readable as revision zero.

Todo count and serialized-byte limits reuse `max_todos` and `max_todo_bytes`. The Human UI additionally bounds machine names, item IDs, content, status, and priority fields by encoded byte length and rejects duplicate IDs or malformed item shapes. A save disables machine selection and row controls until completion. Machine switches reset list state and increment a request generation, so a slow response from a previous machine cannot replace the active list. Periodic inventory refreshes do not overwrite unsaved edits, and offline or revoked workers remain visible but cannot be selected.

The browser supports filtering open and completed items, adding and removing rows, and editing content, status, and priority. The list area is height-bounded and scrollable on narrow and wide layouts. The native OpenTUI Todos screen and its exact clipping behavior remain deferred until the OpenTUI runtime is migrated.

## Audit

The **Audit** panel reads the private process-level JSONL log for one selected machine. Unlike Files and Todos, Audit data is not owned by a workspace session: the local server reads its own process log, while a remote worker serves its own log through native `query_audit` and `get_audit_entry` RPC handlers. Remote requests therefore carry no Files/Todos `session_id`, use the existing worker allowlist, require an online exact machine match, and are capped at 60 seconds. The UI never constructs remote shell commands or copies remote log files to emulate Audit access.

The query path reads a consistent bounded tail while holding the same cross-process transaction lock used by Audit append and retention. It examines at most 4 MB and returns at most 2,000 coalesced rows. Malformed JSONL lines are skipped. Stored `tool_call_start` and `tool_call_end` events remain explicit on disk for retention integrity, while the Human UI query pairs them by `call_id` (or a legacy tool/node/session key), preserves unpaired rows, and folds semantic `parent_call_id` events into the displayed call without deleting their source records. Routine `auth_ok` events are hidden so polling the authenticated UI does not create an ever-growing visible feedback loop.

Lists require `shell:read`; selecting a remote machine additionally requires `remote:use`. Full details are authorized again based on the actual operation: file mutations require `shell:write`, shell and job activity require `shell:execute`, shared-file activity requires `file:share`, Git writes require `git:write`, and remote activity requires `remote:use`. Unknown operation types require the complete supported scope set rather than guessing a weaker permission. This second check prevents a read-only token from using the list endpoint to retrieve command, mutation, sharing, or remote-operation payloads.

The list response is metadata-only: it includes stable identifiers, timestamps, operation, tool, status, duration, session, and lifecycle counts, but excludes `input`, `output`, `error`, and child-event payloads. Free-text search is limited to the same summary metadata, so a read-only token cannot use match/no-match behavior to probe protected payload content. The browser can also filter by operation, event text, session, order, and result limit. Machine and detail requests carry independent generation guards, so a slow response from a previous worker or selection cannot overwrite the active panel. Inventory refreshes preserve an online selection and fall back to local when a worker becomes unavailable. Both the list and detail areas are height-bounded and scrollable on narrow and wide layouts.

Audit fields are already normalized through the shared portability, byte-budget, and credential-redaction boundary before they reach the JSONL log. The browser renders details only through `textContent` inside a `<pre>` element; stored HTML, SVG, or script-like text is never interpreted as active markup. The native OpenTUI Audit screen, lightweight syntax highlighting, and any optional external payload side store remain separate follow-up work.

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
