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

`session_copy` moves files and directories between explicit local or remote sessions through the existing bounded worker RPC chunk protocol. A file destination is never published until its transfer metadata, received byte ranges, final size, temporary-file identity, and optional SHA-256 all validate. `overwrite=false` is checked again at commit time, and a final symbolic link is replaced as a directory entry rather than followed to its target.

Directory copies are packed without symbolic links or special files, validated before extraction, and expanded into a sibling staging directory. The archive entry count is limited by `max_transfer_archive_entries`, while declared regular-file bytes are limited by `max_transfer_unpacked_bytes`. Only after staging succeeds is the old destination moved to a backup and the staged tree committed; commit failure restores the backup. Cleanup failures after a successful commit are reported separately and do not misreport the copy as rolled back.

Cancellation and failures trigger best-effort destination abort plus source/destination scratch cleanup. Temporary archives are subject to the general count/byte budgets only after a 24-hour grace period, so a concurrent active transfer is not removed merely because another transfer starts. Per-path mutation locks use a bounded in-memory registry and a fixed set of cross-process lock shards under `state_dir`.

Operational notes:

- Keep the archive entry and unpacked-byte limits appropriate for the available disk space and inode budget.
- A directory replacement is transactional with rollback, but it is not an atomic exchange on every supported platform; concurrent readers can briefly observe the rename boundary.
- The HTTP streaming protocol used by upstream is intentionally not exposed. The fork retains its authenticated worker control channel and explicit-session chunk RPCs.
- Treat a compromised remote worker as able to provide malicious transfer data; the control side still validates offsets, sizes, checksums, archive paths, member types, and resource limits before commit.

## Audit log handling

Audit records preserve non-sensitive tool inputs, outputs, nested errors, file contents, and command output within the configured per-event budget. Credential-like keys and free-form text are redacted on a best-effort basis, tokenized download URLs are masked, and oversized events become marked previews. Unknown secret formats and sensitive application data can still remain.

Treat `/workspace/.local-shell-mcp/audit_log/audit.jsonl` as sensitive session state, not as a sanitized telemetry stream. Keep it in the controlled workspace/state directory, rely on `max_audit_event_bytes` and `max_audit_log_bytes` for short-term retention, and avoid uploading it to third-party log aggregation unless that system is trusted for the same secrets.

## Threats considered

- Prompt injection in repository files.
- Malicious command execution by an over-capable model.
- Secret exfiltration from mounted files or environment variables.
- Host takeover via Docker socket or privileged mounts.
- Accidental destructive commands.

## Reporting

Open an issue or contact the maintainer privately if this is used in a sensitive environment.
