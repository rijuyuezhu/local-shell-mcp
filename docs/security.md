# Security

`local-shell-mcp` exposes shell execution to an AI client. Treat it as a high-risk administrative interface.

## Recommended deployment

- Run inside a disposable container or VM.
- Expose public deployments through HTTPS with `LOCAL_SHELL_MCP_AUTH_MODE=oauth`.
- Do not mount the Docker socket.
- Do not mount host root.
- Do not mount unrestricted SSH keys or all of `~/.ssh`.
- Use single-repository deploy keys or short-lived GitHub App installation tokens.
- Leave `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=false` by default.
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
- Access tokens are signed locally with a secret stored in `state_dir/oauth-jwt-secret` with mode `0600`, and token lifetime is controlled by `LOCAL_SHELL_MCP_OAUTH_ACCESS_TOKEN_TTL_S`.
- The local approval form escapes reflected fields before rendering HTML and can require `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` before issuing authorization codes.
- Failed PIN attempts, client registration, code issuance, token issuance, invalid bearer tokens, and successful authenticated requests are audited.

### Operational requirements

- Serve public deployments over HTTPS and set `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` to the externally visible origin. This keeps metadata, issuer, resource, redirect, and transport allowlist calculations stable behind a tunnel or reverse proxy.
- Set `LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN` before exposing the server beyond localhost. Treat the PIN as an approval secret, not as a user account password.
- Keep `LOCAL_SHELL_MCP_AUTH_BYPASS_LOCALHOST=false` for shared hosts or any environment where local processes are not fully trusted.
- Keep the state directory private. It contains the JWT signing secret and may coexist with audit logs that include sensitive request context.
- Prefer short access-token lifetimes for public deployments. There is no refresh-token flow and no server-side token revocation list, so token expiry is the primary recovery mechanism after bearer-token disclosure.
- Review audit logs and rotate the state directory when moving a server between trust domains.

### Known limits

- Dynamic clients and authorization codes are in-memory; process restart drops registrations and pending codes.
- Dynamic client registration is intentionally permissive to support MCP client onboarding. Approval happens at the local authorization form and optional admin PIN, not at registration time.
- The authorization server and resource server are co-hosted. This implementation does not fetch third-party authorization-server metadata and does not pass inbound MCP bearer tokens to upstream APIs.
- Bearer tokens are not proof-of-possession tokens. Anyone who obtains a valid token can use it until expiry.
- Metadata is unsigned. Clients should use HTTPS and validate the metadata resource value and issuer before trusting it.

## Full-container mode

`LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` is an explicit full-control mode. It disables built-in command and path denylists and adds auto-approval hints for command-capable tools.

In the Docker image, the server still normally runs as the `agent` user after entrypoint setup; that user has passwordless `sudo` for commands that intentionally need root. Set `DOCKER_RUN_AS_ROOT=true` only when the server process itself must run as root in a disposable container or VM.

## Tokenized file download links

`create_file_link` creates public `/download/{token}` URLs for regular files under the workspace. Creating, listing, and revoking links remain protected tool operations; only the generated download URL is public. Treat generated URLs as bearer secrets: anyone with the URL can download the file until the link expires, is revoked, reaches its configured download-count limit, or the target file disappears.

Operational guidance:

- Set `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` for public deployments so generated links use the externally reachable HTTPS origin.
- Use short TTLs for sensitive artifacts and prefer `max_downloads=1` for one-time handoff.
- Set `LOCAL_SHELL_MCP_FILE_DOWNLOAD_MAX_FILE_BYTES` if large artifact downloads could exhaust bandwidth or storage-backed response capacity.
- Disable the feature with `LOCAL_SHELL_MCP_FILE_DOWNLOAD_ENABLED=false` when public artifact URLs are not needed.
- Remember that audit logs record link creation, revocation, and serving events, but the tokenized URL itself should still be treated as sensitive until expiry.

## Audit log handling

Audit records are intentionally complete and may include tool inputs, tool outputs, file contents, command output, OAuth claims, bearer-token-derived authentication context, and other sensitive values visible to the server.

Treat `/workspace/.local-shell-mcp/audit.jsonl` as sensitive session state, not as a sanitized telemetry stream. Keep it in the controlled workspace/state directory, rely on the configured size cap for short-term retention, and avoid uploading it to third-party log aggregation unless that system is trusted for the same secrets.

## Threats considered

- Prompt injection in repository files.
- Malicious command execution by an over-capable model.
- Secret exfiltration from mounted files or environment variables.
- Host takeover via Docker socket or privileged mounts.
- Accidental destructive commands.

## Reporting

Open an issue or contact the maintainer privately if this is used in a sensitive environment.
