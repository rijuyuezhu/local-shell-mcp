# OAuth library-backed refactor plan

Status: active temporary implementation plan. This file is the single source of truth for the OAuth refactor work on branch `refactor/oauth-lib-simplify`, based on branch `human` at commit `495c98e fix: close oauth hardening gaps`.

This plan is intentionally temporary and should be deleted before the final PR is merged unless the user asks to keep a permanent design note.

## Goal

Refactor the OAuth implementation so route handlers stop hand-building protocol request parsing, redirect responses, token validation, and OAuth errors. The implementation should lean much more heavily on existing libraries while preserving local-shell-mcp's MCP-specific behavior.

The concrete target is:

```text
Starlette route handlers
  -> thin request/response adapters
  -> Authlib-backed OAuth service layer
  -> project state stores and MCP-specific policy hooks
```

The outcome should be simpler code with the same externally observable behavior for ChatGPT/MCP clients.

## Non-goals

Do not turn this into a new OAuth product or a full identity provider. Do not add persistent client/token storage unless needed to preserve existing behavior. Do not change the local single-user admin-PIN approval model. Do not change public-route security semantics, audit behavior, MCP tool scope semantics, generated tool metadata, or connector compatibility.

Do not introduce Django or a second web framework. Do not replace FastAPI/Starlette app construction. Do not use Authlib in a way that creates a larger, harder-to-understand abstraction than the code it replaces.

## Current branch and working assumptions

- Workdir: `/workspace/local-shell-mcp-human`.
- Base branch for this attempt: `human`.
- Current work branch: `refactor/oauth-lib-simplify`.
- Current OAuth hardening base commit: `495c98e`.
- Existing direct dependencies already include `authlib>=1.7.2`, `fastapi>=0.136.3`, `httpx>=0.28.1`, `pydantic>=2.13.4`, `pyjwt>=2.13.0`, and `python-multipart>=0.0.32`.
- Because Authlib is already a direct dependency, prefer using it more deeply before adding a second OAuth dependency.

## Library choices

### Use Authlib more broadly

Authlib is already present and should be the main OAuth protocol library for this refactor.

Use these Authlib pieces where they reduce hand-written OAuth code:

- `authlib.oauth2.rfc6749.OAuth2Request` for framework-neutral OAuth request objects.
- `authlib.oauth2.rfc6749.authorization_server.AuthorizationServer` where the adapter cost stays reasonable.
- `authlib.oauth2.rfc6749.grants.AuthorizationCodeGrant` for authorization-code grant validation and token exchange behavior where feasible.
- `authlib.oauth2.rfc6749.ClientMixin` for the dynamic client wrapper.
- `authlib.oauth2.rfc6750.BearerTokenValidator` and `authlib.oauth2.rfc6749.resource_protector.ResourceProtector` for bearer-token resource-server validation if this can preserve the current challenge shape and audit behavior cleanly.
- Authlib RFC 7636 helpers for PKCE challenge/verifier syntax and comparison. These are already used and should remain centralized.
- Authlib OAuth error classes for RFC-style JSON errors. These are already partly used and should become the only path for OAuth JSON error payloads.
- `authlib.oauth2.rfc8414.AuthorizationServerMetadata` only if it simplifies metadata validation/construction without obscuring the current explicit fields. Metadata documents are short; do not force this if it adds ceremony.

Important caveat: Authlib does not provide a drop-in Starlette/FastAPI provider router here. Its framework-neutral `AuthorizationServer` requires project implementations for client lookup, token generation, code storage, grant subclasses, and request/response adapters. Treat Authlib as a protocol engine, not as an app replacement.

### Keep Starlette/FastAPI for HTTP adapters

Use Starlette utilities instead of manual URL string splicing:

- Use `starlette.datastructures.URL` and `URL.include_query_params()` for redirect query merging.
- Keep `starlette.responses.RedirectResponse`, `JSONResponse`, and `HTMLResponse` for outbound responses.
- Keep FastAPI/Starlette `Request` as the route boundary, but convert it quickly into service-layer input models or Authlib `OAuth2Request`.

### Avoid new URL/HTTP dependencies unless justified

Do not add `yarl`, `furl`, `requests-oauthlib`, or another URL/HTTP helper just to avoid a few lines of parsing. Starlette already provides URL helpers, and the project already depends on it. Add a new dependency only if it removes a meaningful amount of security-sensitive parsing and does not duplicate existing dependencies.

### PyJWT versus Authlib JOSE/JWS

Do not switch JWT signing to `authlib.jose` during the first slice. Local inspection shows `authlib.jose` is deprecated in the installed Authlib and suggests `joserfc`. Adding `joserfc` only for HS256 encode/decode is optional and should be evaluated after the route/service refactor. Keeping PyJWT is acceptable because it is already a direct dependency and the current code uses it narrowly.

If a later slice replaces PyJWT, prefer adding `joserfc` rather than using deprecated `authlib.jose` APIs.

## Current pain points to remove

### `src/local_shell_mcp/oauth/authorization.py`

Current problems:

- `_validate_authorize_params()` manually checks OAuth request fields and returns strings.
- `_make_redirect()` manually splits, merges, encodes, and reconstructs redirect URIs via `urllib.parse`.
- `authorize_get()` and `authorize_post()` mix HTTP form/query parsing, OAuth validation, admin-PIN policy, code issuance, audit, and redirect creation.
- The local approval HTML rendering is fine to keep, but it should consume a validated request object instead of raw dicts wherever possible.

Refactor target:

- Keep `authorize_get()` / `authorize_post()` as thin route functions.
- Move request validation and code issuance into an Authlib-aware service module.
- Replace `_make_redirect()` with a Starlette URL helper, likely:

```python
location = str(URL(redirect_uri).include_query_params(**query))
return RedirectResponse(location, status_code=302)
```

- Preserve the existing redirect-query behavior: existing redirect URI query params remain and OAuth response params are appended.
- Preserve existing error text expected by tests unless there is a strong reason to update tests.

### `src/local_shell_mcp/oauth/tokens.py`

Current problems:

- `token_endpoint()` manually parses every form field and performs the grant validation inline.
- Code pruning, expiry, one-time use, client binding, redirect binding, resource binding, PKCE verification, token issuance, audit, and JSON response construction are all in one route function.
- `_verify_pkce()` already uses Authlib but should be contained inside the grant/service layer.
- `validate_bearer_token()` is a raw PyJWT decode helper and the middleware catches PyJWT exceptions directly.

Refactor target:

- Keep `token_endpoint()` as a thin route function.
- Introduce a token exchange service that returns either a typed token response or raises an Authlib OAuth error.
- Use Authlib grant primitives where practical:
  - Either subclass `AuthorizationCodeGrant` with current in-memory stores, or
  - Implement a smaller Authlib-compatible service using `OAuth2Request`, `ClientMixin`, OAuth error classes, and PKCE helpers if full grant integration creates too much adapter code.
- Preserve all current binding checks:
  - grant type must be `authorization_code`;
  - `resource` is required;
  - authorization code exists, is unused, and is unexpired;
  - client id matches;
  - redirect URI matches;
  - normalized requested resource matches the code-bound resource;
  - PKCE verifier matches;
  - code is single-use;
  - token response remains no-store JSON and includes `expires_in` only when configured TTL is positive.

### `src/local_shell_mcp/oauth/middleware.py`

Current problems:

- `_extract_token()` manually parses the Authorization header.
- `_bearer_challenge()` manually builds a WWW-Authenticate header.
- `_verify_oauth()` catches PyJWT-specific errors instead of OAuth-level validation errors.
- Scope enforcement is project-specific but could be represented closer to resource-server validation.

Refactor target:

- Evaluate `ResourceProtector` + custom `BearerTokenValidator` first.
- Preserve current 401 behavior exactly unless tests are intentionally updated:

```text
WWW-Authenticate: Bearer resource_metadata="<protected-resource-metadata-url>"
WWW-Authenticate: Bearer resource_metadata="<protected-resource-metadata-url>", error="invalid_token"
```

- Keep `OAUTH_CLAIMS` and `require_oauth_scopes()` because MCP tool handlers depend on current request context.
- If Authlib's `ResourceProtector` makes challenge headers harder to control, use Authlib's `BearerTokenValidator` shape as the validation boundary but keep project-owned challenge construction.
- Hide PyJWT exception types behind a project `OAuthTokenError` or Authlib `InvalidTokenError` equivalent so middleware is not tied to the JWT implementation.

### `src/local_shell_mcp/oauth/registration.py`

Current problems:

- Dynamic client registration manually validates JSON shape and redirect URI policy.
- Redirect URI parsing uses `urllib.parse.urlparse` directly.

Refactor target:

- Keep the endpoint behavior but move validation into a service/model function.
- Consider a `RegisteredClient` wrapper implementing Authlib `ClientMixin` from the existing `OAuthClient` dataclass.
- Continue enforcing current redirect policy:
  - HTTPS with netloc is allowed;
  - HTTP is allowed only for loopback hosts `127.0.0.1`, `::1`, `localhost`;
  - custom private-use schemes must include `.` and have no netloc, e.g. `com.example.app:/oauth2redirect`;
  - `javascript:`, `data:`, missing schemes, and `ftp://...` are rejected.
- Do not weaken redirect URI rules to match generic Authlib defaults.

### `src/local_shell_mcp/oauth/metadata.py` and `urls.py`

Current code is short and explicit. Do not over-abstract it.

Possible improvement:

- If Authlib's RFC 8414 metadata model validates the existing authorization-server metadata without adding noise, use it at the service boundary.
- Keep canonical `base_url`, `issuer_url`, and `resource_url` logic project-owned because it intentionally ignores untrusted Host/X-Forwarded headers.

## Proposed new internal modules

The exact filenames may change during implementation, but the shape should be close to this:

```text
src/local_shell_mcp/oauth/service.py
  OAuthService
  validate_authorization_request(...)
  approve_authorization_request(...)
  exchange_authorization_code(...)

src/local_shell_mcp/oauth/adapters.py
  form/query -> OAuth2Request conversion
  Authlib/client wrapper types
  Starlette response helpers

src/local_shell_mcp/oauth/bearer.py
  LocalBearerToken
  LocalBearerTokenValidator
  bearer challenge/error translation
```

Keep modules small. If one file grows beyond making the current code simpler, split it.

## Public behavior that must remain stable

Keep these observable behaviors unless a test is intentionally changed with a clear note in this plan first:

- Public OAuth discovery routes remain public and full-route matched only.
- Protected MCP/tool routes remain protected when `auth_mode=oauth`.
- `auth_bypass_localhost` remains off by default and docs/config examples remain consistent.
- Authorization endpoint supports `response_type=code` only.
- Dynamic registration returns `token_endpoint_auth_method: none`.
- PKCE is required for authorization approval.
- Both `S256` and `plain` remain advertised and accepted unless the user explicitly asks to harden to S256-only.
- RFC 8707 `resource` is required for authorization and token exchange.
- Token audience remains bound to canonical `/mcp` resource by default.
- Issuer/resource/base URL generation does not trust request Host headers.
- Admin PIN is required before code issuance; missing PIN config must not issue a code.
- Approval UI still escapes reflected fields and hidden inputs.
- Authorization response includes `code`, `iss`, and optional `state`.
- Redirect URI existing query parameters are preserved when appending OAuth response parameters.
- Auth codes remain one-time and expire by `oauth_code_ttl_s`.
- Access tokens expire by default when `oauth_access_token_ttl_s > 0`.
- Token response remains no-store JSON.
- WWW-Authenticate challenge includes `resource_metadata`.
- Tool scope failures remain 403 with `Missing required OAuth scope: <scope>`.
- No raw download token or `/download/<token>` URL is added to audit logs.

## Test inventory to protect during refactor

The most relevant existing tests are in:

- `tests/test_mcp_chatgpt_compat.py`
  - dynamic registration, authorization, token exchange, PKCE, resource binding, scope enforcement, admin PIN, redirect query preservation, HTML escaping, token expiry.
- `tests/test_mcp_app.py`
  - public OAuth route mounting, protected-resource metadata challenge, route protection.
- `tests/test_http_validation.py`
  - public OAuth routes and canonical metadata URLs.
- `tests/test_declarative_tools.py`
  - direct MCP handler scope enforcement via `OAUTH_CLAIMS`.

Add focused unit tests only where they lock down new adapter/service behavior and replace brittle route-level implementation assertions. Do not delete coverage just because internals move.

## Implementation slices

### Slice 1: Plan and baseline

- Create this plan file under `docs/temp/`.
- Confirm branch and working tree.
- Run a narrow baseline if useful:

```bash
uv run pytest tests/test_mcp_chatgpt_compat.py tests/test_mcp_app.py tests/test_http_validation.py tests/test_declarative_tools.py
```

### Slice 2: Response and redirect helpers

Goal: remove hand-built redirect query merging and centralize OAuth response creation.

Tasks:

- Add a helper such as `oauth_redirect(redirect_uri: str, query: Mapping[str, str]) -> RedirectResponse` using Starlette `URL.include_query_params()`.
- Move JSON/no-store and OAuth error serialization into a stable public helper name instead of underscore-only helpers where the service layer needs them.
- Replace `_make_redirect()` call sites and update tests importing `_make_redirect()`.
- Keep behavior for preserving existing redirect query params.

Validation:

```bash
uv run pytest tests/test_mcp_chatgpt_compat.py -k 'redirect or authorize'
```

### Slice 3: Authlib-backed client and authorization request service

Goal: make authorization request validation library-shaped and keep route functions thin.

Tasks:

- Add an Authlib `ClientMixin` wrapper around `OAuthClient`.
- Add a normalized request object or use Authlib `OAuth2Request` for query/form data.
- Move authorization validation out of `authorization.py` into service code.
- Keep the approval form renderer in `authorization.py`, but pass it already-normalized/validated display data when feasible.
- Move code issuance into service code.
- Keep admin PIN check project-owned and explicit.

Preferred route shape:

```python
async def authorize_get(request: Request) -> Response:
    result = oauth_service.prepare_authorization(request)
    return render_authorization_form(result)

async def authorize_post(request: Request) -> Response:
    result = await oauth_service.approve_authorization(request)
    if result.error:
        return render_authorization_form(...)
    return oauth_redirect(result.redirect_uri, result.redirect_params)
```

Validation:

```bash
uv run pytest tests/test_mcp_chatgpt_compat.py -k 'authorize or pin or pkce or redirect'
```

### Slice 4: Authlib-backed token exchange

Goal: remove inline token endpoint grant validation.

Tasks:

- Convert Starlette form data to `OAuth2Request` or an Authlib-compatible request object.
- Implement either:
  - an `AuthorizationCodeGrant` subclass backed by `_CLIENTS` and `_CODES`, or
  - a smaller Authlib-shaped token exchange service using `OAuth2Request`, `ClientMixin`, OAuth error classes, and RFC 7636 helpers.
- Keep `_prune_codes()` behavior or move it into the service unchanged.
- Keep token issuance separate from grant validation.
- Hide PyJWT behind `issue_access_token()` and `validate_bearer_token()` or a new token codec class.

Decision rule:

Use full `AuthorizationCodeGrant` only if it clearly deletes more code than it adds. If implementing the grant subclass requires duplicating project policy in many override methods, use the smaller service and document the reason in this file before coding further.

Validation:

```bash
uv run pytest tests/test_mcp_chatgpt_compat.py -k 'token or flow or pkce or code or expire'
```

### Slice 5: Resource server / bearer validation

Goal: move bearer parsing and validation toward Authlib's resource-server abstractions without losing MCP-specific challenge headers.

Tasks:

- Implement `LocalBearerToken` with the methods expected by Authlib `BearerTokenValidator`: `get_scope()`, `is_expired()`, `is_revoked()`.
- Implement `LocalBearerTokenValidator.authenticate_token()` by decoding the local bearer token and validating issuer/audience/resource.
- Use Authlib `BearerTokenValidator.validate_token()` or `ResourceProtector.validate_request()` for scope checking where practical.
- Keep `OAUTH_CLAIMS` as the project context boundary.
- Keep `WWW-Authenticate` header construction project-owned if Authlib cannot express `resource_metadata` cleanly.
- Translate Authlib validation failures into the existing 401 response shape and audit event.

Validation:

```bash
uv run pytest tests/test_mcp_chatgpt_compat.py -k 'scope or token or flow'
uv run pytest tests/test_mcp_app.py tests/test_declarative_tools.py
```

### Slice 6: Dynamic registration cleanup

Goal: make registration validation reusable and less route-bound.

Tasks:

- Move JSON extraction/validation into a small service function.
- Keep redirect URI policy unchanged.
- Consider using Starlette `URL` for parse/readability if it handles custom schemes correctly; otherwise keep `urllib.parse.urlparse` because custom private-use schemes are security-sensitive.
- Return registration response through the central OAuth JSON helper.

Validation:

```bash
uv run pytest tests/test_mcp_chatgpt_compat.py -k 'registration or redirect_uri'
```

### Slice 7: Full validation and cleanup

Run:

```bash
uv run pytest
uv run ruff check .
uv run pyright
```

Then inspect:

```bash
git diff --stat
git diff -- src/local_shell_mcp/oauth tests docs/temp/oauth-library-refactor-plan.md pyproject.toml uv.lock
git status -sb
```

Commit only after tests pass and generated files, if any, are included.

## Commit strategy

Prefer small commits by slice:

1. `docs: plan oauth library refactor`
2. `refactor: centralize oauth responses and redirects`
3. `refactor: move authorization validation into service`
4. `refactor: move token exchange into oauth service`
5. `refactor: use authlib bearer validation`
6. `refactor: simplify oauth registration validation`

If a slice becomes too invasive, stop and update this plan with the reason before continuing.

## Design constraints for implementation

- Route functions should be thin and mostly about Starlette request/response plumbing.
- Project policy should be explicit and testable. Do not bury admin PIN, canonical resource, or MCP route behavior inside Authlib overrides where future maintainers cannot find it.
- Authlib adapters should be named clearly and kept near OAuth code.
- Prefer typed dataclasses for service results and validated inputs over passing raw `dict[str, str]` across layers.
- Avoid new public underscores being imported by tests. If tests need helper access, expose stable internal names or test through routes.
- Preserve existing audit event names unless a behavior intentionally changes.
- Do not log bearer tokens, auth codes, redirect URLs containing secrets, download tokens, or admin PIN values.

## Open implementation questions

Answer these during the relevant slice and record decisions here:

1. Does full `AuthorizationCodeGrant` integration delete enough code to justify the adapter/subclass surface?
   - Current default: try a small prototype; fall back to an Authlib-shaped service if full grant integration is more verbose.
2. Can `ResourceProtector` preserve the exact `WWW-Authenticate` header with `resource_metadata`?
   - Current default: use `BearerTokenValidator` validation semantics and keep challenge construction project-owned if needed.
3. Should PyJWT remain after the refactor?
   - Current default: keep it for now. Consider `joserfc` only after endpoint/middleware simplification is complete.
4. Should custom private-use redirect URI parsing use Starlette `URL`?
   - Current default: keep `urllib.parse.urlparse` for redirect policy unless Starlette behavior is verified for `com.example.app:/oauth2redirect` and `ftp://...`.

## Implementation decisions recorded during this refactor

- Slice 2 centralized OAuth JSON/error responses in `responses.py` and replaced manual authorization redirect URL reconstruction with Starlette `URL.include_query_params()`.
- Slice 3 added `adapters.py` and `service.py`; authorization request validation now uses Authlib-shaped `LocalOAuth2Request` and `LocalOAuthClient`, while admin PIN and approval HTML remain explicit route/UI policy.
- Slice 4 uses an Authlib-shaped service instead of full `AuthorizationCodeGrant`. Full grant subclassing was not used because preserving local MCP resource binding, admin-PIN approval, process-local client/code stores, exact legacy error text, and public-client PKCE behavior would require enough overrides that it would not simplify the code.
- Slice 4 added `token_codec.py` to keep local JWT signing/validation separate from token exchange service logic. `tokens.py` remains a thin Starlette endpoint plus compatibility exports for existing tests/callers.
- Slice 5 added `bearer.py` with Authlib resource-server validation. Middleware delegates Authorization header parsing and credential validation to that module while keeping project-owned challenge headers and request context.
- Slice 6 moved dynamic registration payload checks, redirect policy, client creation, and audit into `service.py`; `registration.py` is now a thin JSON adapter.


## Layered package layout decision

The OAuth package should not remain as flat endpoint/service files. Keep the public OAuth behavior unchanged, but move implementation into layered subpackages:

```text
src/local_shell_mcp/oauth/
  core/       project OAuth state, policy, URL helpers, scopes, and service operations
  http/       Starlette/FastAPI route handlers, middleware, responses, and templates
  protocol/   Authlib/PyJWT adapters and local credential codec
```

Import direction should stay one-way where practical:

```text
oauth.http -> oauth.core -> oauth.protocol
oauth.http -> oauth.protocol only for resource-server middleware where needed
oauth.protocol -> oauth.core only for small data/URL/scope helpers
```

Do not keep root-level compatibility shims for the moved modules in this branch; update internal imports and tests to the layered paths so the tree itself communicates the architecture.

Package `__init__.py` files should carry layer-level docstrings that describe each layer's responsibility, even though the current public-docstrings test skips `__init__.py`.

## Definition of done

- OAuth routes are thinner than before and no longer contain most protocol validation logic.
- Authlib is used for more than isolated PKCE/error helpers; it backs client/grant/request and/or bearer validation semantics.
- Starlette URL helpers replace manual redirect query reconstruction.
- Current OAuth compatibility/security tests pass.
- Full `uv run pytest`, `uv run ruff check .`, and `uv run pyright` pass.
- This plan accurately reflects the final implementation decisions before the temporary file is deleted or the PR is finalized.
