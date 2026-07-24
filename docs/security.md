# Security

`local-shell-mcp` exposes shell execution to an AI client. Treat it as a high-risk administrative interface.

## Recommended deployment

- Run inside a disposable container or VM.
- Expose public deployments through HTTPS with `LOCAL_SHELL_MCP_AUTH_MODE=oauth`.
- Do not mount the Docker socket.
- Do not mount host root.
- Do not mount unrestricted SSH keys or all of `~/.ssh`.
- Use single-repository deploy keys or short-lived GitHub App installation tokens.
- Leave `LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=false` by default.
- Review audit logs after each session, then rotate or discard them with the rest of the short-lived state.

Cloudflare Tunnel is a convenient public transport. Cloudflare Access is optional and is not the built-in authentication layer.

## OAuth security

The built-in OAuth implementation is designed for a single local operator connecting an MCP client, such as ChatGPT, to a high-risk shell server. It is not a general-purpose multi-user identity provider. Keep `LOCAL_SHELL_MCP_AUTH_MODE=oauth` for public HTTP deployments and use `LOCAL_SHELL_MCP_AUTH_MODE=none` only for trusted local testing.

### Standards alignment

The HTTP OAuth flow follows the security boundaries required by the [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization):

- The MCP endpoint acts as an OAuth protected resource and advertises its authorization server through [OAuth 2.0 Protected Resource Metadata](https://datatracker.ietf.org/doc/html/rfc9728).
- `WWW-Authenticate` challenges include the RFC 9728 `resource_metadata` parameter so clients can discover the protected-resource metadata URL before starting the authorization flow.
- Metadata for path-based resources follows RFC 9728 well-known URL construction. For the default resource `https://example.com/mcp`, the metadata URL is `https://example.com/.well-known/oauth-protected-resource/mcp`, not `https://example.com/mcp/.well-known/oauth-protected-resource`.
- Authorization-server metadata is served according to [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414), including authorization, token, and dynamic-registration endpoints.
- Clients must send the [RFC 8707](https://datatracker.ietf.org/doc/html/rfc8707) `resource` parameter on both authorization and token requests. The server rejects missing or mismatched resource values.
- Access tokens are bearer tokens that must be presented in the `Authorization` header, never in the URI query string.
- Tokens are audience-bound to the canonical MCP resource and are accepted only when `iss`, `aud`, and `iat` validation succeeds.
- Authorization code exchange is protected with PKCE. The server supports `S256` and `plain` for compatibility, but clients should prefer `S256`.

### Controls implemented

- OAuth bootstrap routes, well-known metadata, health checks, remote-worker enrollment endpoints, and tokenized `/download/{token}` file links remain public; MCP and REST tool routes are protected by middleware unless `auth_mode=none` or the explicit localhost bypass applies.
- The canonical resource defaults to the `/mcp` endpoint, not merely the origin, so a token for `https://example.com/mcp` is not accepted for every service on `https://example.com`.
- The authorization request must include `response_type=code`, `client_id`, `redirect_uri`, and `resource`; the `resource` must match this server.
- Dynamically registered clients bind authorization codes to registered redirect URIs. Token exchange must present the same `client_id`, `redirect_uri`, `resource`, and PKCE verifier.
- Authorization codes are short-lived, one-time-use in-memory records. Reusing a code returns `invalid_grant`.
- Access tokens are signed locally with a randomly generated secret stored in `state_dir/oauth-jwt-secret` with mode `0600`. Initialization is serialized across processes, and existing non-placeholder secrets shorter than 32 UTF-8 bytes are rejected rather than silently reused. Token lifetime is controlled by `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S`.
- The local approval form escapes reflected fields before rendering HTML and can require `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` before issuing authorization codes.
- Failed PIN attempts, client registration, code issuance, token issuance, invalid bearer tokens, and successful authenticated requests are audited.

### Operational requirements

- Serve public deployments over HTTPS and set `LOCAL_SHELL_MCP_BASE_URL` to the externally visible origin. This keeps metadata, issuer, resource, redirect, and transport allowlist calculations stable behind a tunnel or reverse proxy.
- When OAuth and `LOCAL_SHELL_MCP_BASE_URL` are configured together, startup requires `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` to be a non-placeholder value of at least 8 characters. Use a substantially longer random value in production and treat it as an approval secret, not as a user account password.
- Keep `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST=false` for shared hosts or any environment where local processes are not fully trusted.
- Keep the state directory private. It contains the JWT signing secret and may coexist with audit logs that include sensitive request context.
- Prefer short access-token lifetimes for public deployments. There is no refresh-token flow and no server-side token revocation list, so token expiry is the primary recovery mechanism after bearer-token disclosure.
- Review audit logs and rotate the state directory when moving a server between trust domains.

### Known limits

- Pending dynamic client registrations remain in memory and expire according to `oauth_client_ttl_s`. A client is persisted in the configured state directory only after the local user approves its first authorization.
- Approved client registrations do not use the pending-registration TTL and survive service restarts. Authorization codes remain in memory and are invalidated by process restart.
- Dynamic client registration is intentionally permissive to support MCP client onboarding. Persistence happens only after approval at the local authorization form with the configured admin PIN.
- The authorization server and resource server are co-hosted. This implementation does not fetch third-party authorization-server metadata and does not pass inbound MCP bearer tokens to upstream APIs.
- Bearer tokens are not proof-of-possession tokens. Anyone who obtains a valid token can use it until expiry.
- Metadata is unsigned. Clients should use HTTPS and validate the metadata resource value and issuer before trusting it.

## Agent Bridge credentials and upstream OAuth

Agent Bridge authentication is separate from the built-in OAuth server that protects this `local-shell-mcp` deployment. It authenticates the control server as a client of configured upstream MCP servers.

- Public manifest files may contain literal `env` and `headers` for compatibility, but new credentials should use structured secret references and `auth.mode="secret"`. Secret references are resolved only immediately before transport startup.
- Private values, OAuth tokens, dynamic client information, absolute expiry timestamps, and discovered authorization-server metadata are stored under `state_dir/agent_auth`. The store is versioned and size-bounded, uses a cross-process lock and atomic replacement, and is owner-only (`0700` directory and `0600` files on POSIX). Corrupt or unsupported data fails explicitly and is not reset automatically.
- `local-shell-mcp mcp secret set ... --stdin` is the only secret-value input surface. Values are not accepted as command arguments, printed by list/status commands, serialized into the public manifest, or returned through MCP tools.
- Upstream OAuth uses the MCP SDK's protected-resource and authorization-server discovery, PKCE, state validation, dynamic client registration, refresh, and HTTP authentication. The interactive CLI binds a one-shot callback to a random `127.0.0.1` port. Normal server operation is noninteractive: it may refresh stored credentials, but a new authorization requirement fails immediately with instructions to run the CLI.
- OAuth logout attempts the advertised revocation endpoint before deleting local credentials. The command distinguishes successful, unsupported, and failed remote revocation; local state is cleared even when revocation is unsupported or fails.
- Agent Bridge status exposes only mode, authorization state, expiry/status metadata, counts, and redacted errors. Administrative secret names are available only to the local `mcp secret list` command. Credential-store changes participate in the dynamic registry fingerprint so updates become visible without restart.
- Secret-based stdio servers receive values in their child environment; HTTP/SSE servers receive them in request headers. OAuth and static secrets therefore grant the upstream server access to those credentials. Configure only trusted upstreams and use narrowly scoped, revocable credentials.

## Session environment disclosure boundary

`session_start` and `session_change_cwd` return a bounded `environment` object so clients can choose tools without arbitrary shell inspection. It is an explicit allowlist, not a serialization of `Settings`, `os.environ`, process arguments, or executable paths.

- Runtime fields contain normalized versions/platform tokens only. Worker identity contains package/bundle versions and a normalized service kind/status, never bundle digests, join tokens, service definitions, or command lines.
- Tool probes run only allowlisted version commands, concurrently, with independent 1.5-second timeouts and bounded output. Responses expose an extracted version token and safe source category, not full executable paths, stdout/stderr, or exception text. Missing, timed-out, and failed probes are not marked available.
- Capability and policy fields include only values needed for tool selection. They exclude environment-variable values, OAuth/admin secrets, Agent Bridge server names, command/path denylists, state/config directories, audit contents, and other private configuration. OAuth capability changes are represented only as configured/authorized server counts.
- Remote orientation is produced by the worker and validated as the same typed response before the controller rebinds its public session id and machine name. Remote cwd changes refresh worker-side Git, instructions, environment, and canonical workdir instead of substituting controller-local information.
- Tool probes are briefly cached, but cwd-sensitive orientation and dynamic capability/policy fields are rebuilt for each session response. Collection failures degrade to normalized unavailable/error fields rather than failing session creation or returning raw diagnostics.

## Inbound HTTP request limits

All HTTP-mode applications apply `max_http_request_bytes` before REST, MCP, OAuth, download, or remote-worker route parsing. The default is 16,000,000 bytes; set it to `0` only when another trusted front end enforces an equivalent or stricter limit. The middleware rejects oversized requests with HTTP 413 and a stable JSON error before buffering more than the configured budget.

Both declared and observed sizes are enforced. A `Content-Length` above the limit is rejected without reading the body, while chunked requests, missing lengths, invalid lengths, and misleading smaller lengths are counted from actual ASGI body messages. Accepted bodies are replayed with identical bytes to downstream form, JSON, FastAPI, and MCP parsers. Once buffered request messages are consumed, receive calls continue to the live connection so streaming responses and MCP disconnect handling remain intact.

When OAuth authentication is enabled, protected MCP and REST routes authenticate before the body limiter reads an unauthenticated request. Public OAuth bootstrap and remote enrollment routes remain subject to the shared limit. Dynamic OAuth client registration also retains its stricter `oauth_registration_max_body_bytes` limit. Rejections are audited with method, path, declared/observed sizes, and the configured limit, but never with body contents; audit failure does not prevent the 413 response.

## Full-control mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTROL=true` is an explicit full-control mode. It disables built-in command and path denylists, but MCP safety annotations remain conservative and continue to identify destructive or open-world tools.

In the Docker image, the entrypoint normally creates a non-root `agent` user at container startup. By default, its UID/GID are detected from the mounted `/workspace` owner so bind-mounted files stay writable by the host user. Set `DOCKER_AGENT_UID` or `DOCKER_AGENT_GID` only to override that detection. Set `DOCKER_RUN_AS_ROOT=true` only when the server process itself must run as root in a disposable container or VM.

## Browser Human UI policy

The browser Human UI loads scripts only from the configured origin. Its Content Security Policy permits inline styles required by xterm's runtime layout and narrowly permits `wasm-unsafe-eval` for the bundled xterm Image Addon Sixel decoder; it never enables general `unsafe-eval` or external script origins. OAuth `401` responses clear an invalid tab token, while `403` scope failures preserve the valid token and expose only the bounded missing-scope error.

## Tokenized file download links

`create_file_link` creates a public `/download/{token}` URL for an immutable creation-time snapshot of one regular file in an explicit local or remote session. Creating, listing, and revoking links remain protected tool operations; only the generated URL is public. Remote files are copied to the control server through the validated transfer-chunk protocol before the link is registered. Changing, deleting, or replacing the original local or remote file does not retarget an existing link.

Snapshots, primary/backup metadata, and the cross-process lock are stored privately under `state_dir`. Snapshot identity, size, and SHA-256 are checked before serving. Expired, revoked, exhausted, malformed, orphaned, and stale interrupted-transfer artifacts are removed. A corrupt primary store is recovered from its backup; if both copies are invalid, the service refuses to silently reset link state.

Browser responses use `attachment` disposition by default. Set `inline=true` only when browser rendering is needed. Inline responses add `Content-Security-Policy: sandbox`; all responses add `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `Cache-Control: private, no-store`. MIME type is inferred from the original source filename first and the optional display filename second. These controls reduce browser risk but do not make untrusted active content harmless outside the sandboxed response.

Treat generated URLs as bearer secrets: anyone with the URL can read the snapshot until the link expires, is revoked, or reaches its configured download-count limit.

Operational guidance:

- Set `LOCAL_SHELL_MCP_BASE_URL` for public deployments so generated links use the externally reachable HTTPS origin.
- Use short TTLs for sensitive artifacts and prefer `max_downloads=1` for one-time handoff.
- Keep `inline=false` unless the user explicitly needs in-browser rendering.
- Set `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` to bound both local copies and remote transfers.
- Keep `state_dir` private because it contains the snapshot bytes as well as link metadata.
- Disable the feature with `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED=false` when public artifact URLs are not needed.
- Remember that audit logs record link creation, revocation, and serving events, but the tokenized URL itself should still be treated as sensitive until expiry.

## Session-to-session transfers

`session_copy` moves files and directories between explicit local or remote sessions. Local copies, same-worker copies, and bounded JSON/base64 worker RPC remain available. When a configured public controller origin, payload threshold, and worker capability permit it, large copies use a private resumable HTTP gateway without adding a public ticket tool.

The URL contains only a non-secret object identifier. A separate short-lived Authorization capability is stored only as a SHA-256 hash and is bound to the registered worker identity, upload/download direction, source and destination session ids, expected size and digest, cursor, expiry, nonce, and one active claim. The worker accepts only the controller's exact origin and rejects redirects, userinfo, query strings, fragments, malformed paths, and credential-bearing URLs. Capabilities and private absolute source paths are excluded from metadata, logs, exceptions, process arguments, and service definitions.

Local sources are copied through a no-follow stable file handle into an owner-private immutable spool before they are served. POSIX opens use `O_NOFOLLOW`; Windows opens the directory entry with `FILE_FLAG_OPEN_REPARSE_POINT` and rejects every reparse point before converting the native handle to a Python file descriptor. Remote uploads use bounded `Content-Range` chunks and a per-chunk SHA-256; completed chunks are accepted again only as an exact durable replay. Downloads require bounded `Range` requests and read only the immutable spool. Cursor, whole-object size and SHA-256, platform-native file identity, a persisted ctime/mtime generation, and destination transaction metadata all validate before publication. The generation is refreshed after every durable append or rollback, so inode/file-id reuse and same-size replacements do not silently preserve authority. Append/fsync failures truncate back to the last committed cursor.

Controller transfer metadata and spools live under `state_dir/remote_transfers` with private permissions, active-count and aggregate-byte quotas, expiry cleanup, and no symlink following. Cross-worker copies stage through that controller spool instead of giving one worker network authority over the other. A restarted controller can discard a stale process claim and resume validated state; each successful authenticated request extends only the current short-lived grant.

A file destination is never published until its transfer metadata, contiguous received ranges, final size, temporary-file identity, and SHA-256 all validate. `overwrite=false` is checked again at commit time, and a final symbolic link is replaced as a directory entry rather than followed to its target. Foreground failure and cancellation revoke capabilities and remove private partial state. A managed job failure revokes capabilities but retains validated progress for the same durable job id; retry rotates fresh capabilities and resumes from the authoritative cursor.

Directory copies are packed without symbolic links or special files, validated before extraction, and expanded into a sibling staging directory. The archive entry count is limited by `max_transfer_archive_entries`, while declared regular-file bytes are limited by `max_transfer_unpacked_bytes`. Only after staging succeeds is the old destination moved to a backup and the staged tree committed; commit failure restores the backup. Cleanup failures after a successful commit are reported separately and do not misreport the copy as rolled back.

Operational notes:

- Keep the archive, active-transfer, and spool-byte limits appropriate for available disk space and inode budget.
- A directory replacement is transactional with rollback, but it is not an atomic exchange on every supported platform; concurrent readers can briefly observe the rename boundary.
- Shared request-body buffering is bypassed only for the exact private transfer `PUT` route; the route enforces its own chunk limit and all other HTTP paths retain the generic request limit.
- Treat a compromised remote worker as able to provide malicious transfer data; the control side still validates authorization, offsets, sizes, checksums, archive paths, member types, and resource limits before commit.

## Remote worker identity and user services

Remote enrollment invitations are one-time bearer capabilities. Prefer `worker enroll/connect --invite-stdin` or the generated join command, avoid copying invites into durable scripts, and revoke a worker whose state directory may be compromised. The private worker identity stores the controller origin, assigned name, access token, and canonical workdir; keep the entire worker state directory owner-private.

Linux systemd-user units and macOS launchd plists invoke a stable private launcher plus `worker run`. They do not contain the invitation, access token, controller URL, or worker name. The launcher derives the state directory from its own path, prefers the verified installed runtime, and reads identity only inside the worker process. Windows service installation is deliberately unsupported rather than emulated with an untracked detached process.

Service lifecycle commands are local CLI operations, not MCP tools. A controller can still request a verified idle-time runtime upgrade through the existing authenticated worker channel, so a trusted controller has authority to replace worker code. Automatic and manual updates enforce same-origin URLs and redirects, bounded downloads/extraction, version/digest checks, safe archive members, atomic replacement, rollback, and credential-free re-exec. The single-instance lock is retained across re-exec so a competing manual process cannot consume jobs during handoff.

`worker logs` can contain tool diagnostics, paths, and application output. Systemd reads the user journal; launchd writes an owner-private bounded file. Treat both as sensitive and avoid forwarding them to systems that are not trusted for worker command output.

## Audit log handling

Audit records preserve non-sensitive tool inputs, outputs, nested errors, file contents, and command output within configured bounds. Credential-like keys and free-form text are redacted on a best-effort basis before any externalization, and tokenized download URLs are masked. Small sanitized values remain inline; larger accepted values are stored as deterministic gzip-compressed canonical JSON under the private `audit_log/payloads` directory and represented in JSONL by bounded content-addressed references. Values above the per-value limit remain explicit omissions.

Payload objects use private atomic replacement and are read through no-follow regular-file handles. Full recovery verifies retention, compressed/decompressed bounds, canonical byte count, digest, UTF-8, and JSON. JSONL and referenced payload quotas are enforced inside the same cross-process transaction while preserving completed tool-call pairs. Corrupt, missing, or expired payloads never return raw path or decompression diagnostics.

The session-bound `audit_tail` tool and Human UI lists require `audit:read`. Resolving one retained reference additionally requires `audit:full` and a stable entry id; Human UI detail retains operation-sensitive shell/file/share/Git/remote checks. The current `audit_tail` call is excluded by exact lifecycle id rather than hiding all audit-query history.

Treat `/workspace/.local-shell-mcp/audit_log/` as sensitive session state, not as a sanitized telemetry stream. Best-effort redaction does not prove that unknown secret formats or application-sensitive data are absent. Keep JSONL and payload objects in the controlled state directory, use the event/log/payload/retention limits for short-term retention, and avoid uploading either to third-party systems unless they are trusted for the same data.

## Threats considered

- Prompt injection in repository files.
- Malicious command execution by an over-capable model.
- Secret exfiltration from mounted files or environment variables.
- Host takeover via Docker socket or privileged mounts.
- Accidental destructive commands.

## Reporting

Open an issue or contact the maintainer privately if this is used in a sensitive environment.
