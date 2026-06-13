"""Implement the OAuth metadata, registration, authorization, token, and bearer-token validation flow used by HTTP mode."""

from __future__ import annotations

import hmac
import html as html_lib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import jwt
from authlib.oauth2.rfc6749.errors import (
    InvalidGrantError,
    InvalidRequestError,
    OAuth2Error,
    UnsupportedGrantTypeError,
)
from authlib.oauth2.rfc7636.challenge import (
    CODE_CHALLENGE_PATTERN,
    CODE_VERIFIER_PATTERN,
    compare_plain_code_challenge,
    compare_s256_code_challenge,
)
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)

from ..audit import audit
from ..config.settings import get_settings
from .oauth_models import _CLIENTS, _CODES, AuthCode, OAuthClient
from .oauth_urls import (
    _default_scope,
    _normalize_resource,
    _scopes,
    issuer_url,
    public_base_url,
    resource_url,
)


def _jwt_secret() -> str:
    """Return a configured or persisted signing secret for local bearer tokens."""
    settings = get_settings()
    secret_path = settings.state_dir / "oauth-jwt-secret"
    try:
        secret = secret_path.read_text(encoding="utf-8").strip()
        if secret:
            return secret
    except FileNotFoundError:
        pass

    settings.state_dir.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    secret_path.write_text(secret + "\n", encoding="utf-8")
    secret_path.chmod(0o600)
    return secret


def protected_resource_metadata(request: Request) -> dict[str, Any]:
    """Build RFC-style protected-resource metadata for MCP clients discovering authorization servers."""
    return {
        "resource": resource_url(request),
        "authorization_servers": [issuer_url(request)],
        "scopes_supported": _scopes(),
        "resource_documentation": f"{public_base_url(request)}/docs",
    }


def authorization_server_metadata(request: Request) -> dict[str, Any]:
    """Build OAuth authorization-server metadata for dynamic clients and PKCE code flow."""
    issuer = issuer_url(request)
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256", "plain"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": _scopes(),
        "authorization_response_iss_parameter_supported": True,
        "resource_parameter_supported": True,
    }


def _json(data: dict, status_code: int = 200) -> JSONResponse:
    """Return compact JSON responses with the media type expected by OAuth metadata clients."""
    return JSONResponse(
        data, status_code=status_code, headers={"Cache-Control": "no-store"}
    )


def _oauth_error(exc: OAuth2Error, status_code: int = 400) -> JSONResponse:
    """Serialize Authlib OAuth errors in the RFC6749 JSON shape."""
    body = {"error": exc.error}
    if exc.description:
        body["error_description"] = exc.description
    return _json(body, status_code=status_code)


def _invalid_request(description: str) -> JSONResponse:
    """Return an Authlib-backed invalid_request response."""
    return _oauth_error(InvalidRequestError(description=description))


def _invalid_grant(description: str) -> JSONResponse:
    """Return an Authlib-backed invalid_grant response."""
    return _oauth_error(InvalidGrantError(description=description))


async def oauth_protected_resource(request: Request) -> JSONResponse:
    """Serve protected-resource metadata from the well-known OAuth endpoint."""
    return _json(protected_resource_metadata(request))


async def oauth_server_metadata(request: Request) -> JSONResponse:
    """Serve authorization-server metadata from the well-known OAuth endpoint."""
    return _json(authorization_server_metadata(request))


async def oauth_register(request: Request) -> JSONResponse:
    """Accept dynamic client registration and persist the issued client identifier."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    client_id = "local-shell-mcp-" + secrets.token_urlsafe(24)
    redirect_uris = [
        str(x) for x in body.get("redirect_uris", []) if isinstance(x, str)
    ]
    client = OAuthClient(
        client_id=client_id,
        redirect_uris=redirect_uris,
        client_name=body.get("client_name")
        if isinstance(body.get("client_name"), str)
        else None,
    )
    _CLIENTS[client_id] = client
    audit(
        "oauth_client_registered",
        client_id=client_id,
        redirect_uris=redirect_uris,
    )
    return _json(
        {
            "client_id": client_id,
            "client_id_issued_at": client.created_at,
            "client_name": client.client_name or "ChatGPT",
            "redirect_uris": redirect_uris,
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        status_code=201,
    )


def _validate_authorize_params(params: dict[str, str]) -> str | None:
    """Validate authorization request parameters before rendering the consent form or redirecting."""
    if params.get("response_type") != "code":
        return "Only response_type=code is supported"
    if not params.get("client_id"):
        return "Missing client_id"
    if not params.get("redirect_uri"):
        return "Missing redirect_uri"
    if not params.get("resource"):
        return "Missing resource"
    if _normalize_resource(params["resource"]) != resource_url():
        return "resource does not match this MCP server"
    client = _CLIENTS.get(params["client_id"])
    if (
        client
        and client.redirect_uris
        and params["redirect_uri"] not in client.redirect_uris
    ):
        return "redirect_uri is not registered for this client"
    challenge = params.get("code_challenge")
    if challenge and not CODE_CHALLENGE_PATTERN.match(challenge):
        return "Invalid code_challenge"
    method = params.get("code_challenge_method")
    if method and method not in {"S256", "plain"}:
        return "Unsupported code_challenge_method"
    return None


def _hidden_inputs(params: dict[str, str]) -> str:
    """Preserve validated authorization parameters as hidden fields in the approval form."""

    return "\n".join(
        f'<input type="hidden" name="{html_lib.escape(k, quote=True)}" value="{html_lib.escape(v, quote=True)}" />'
        for k, v in params.items()
    )


def _authorize_form(
    params: dict[str, str], error: str | None = None
) -> HTMLResponse:
    """Render the local approval form used before issuing an authorization code."""
    settings = get_settings()
    scope = params.get("scope") or _default_scope()
    resource = params.get("resource") or resource_url()
    error_html = (
        f'<p style="color:#b00020">{html_lib.escape(error)}</p>'
        if error
        else ""
    )
    pin_hint = "Enter LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN to approve this ChatGPT connector."
    if not settings.oauth_admin_pin:
        pin_hint = "No admin PIN is configured. Click Approve to continue. Set LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN before exposing this publicly."
    html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>Authorize local-shell-mcp</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 720px; margin: 48px auto; line-height: 1.45;">
  <h1>Authorize local-shell-mcp</h1>
  <p>This grants ChatGPT access to tools that can execute shell commands inside the configured container workspace.</p>
  <p><strong>Resource:</strong> {html_lib.escape(resource)}</p>
  <p><strong>Scopes:</strong> {html_lib.escape(scope)}</p>
  {error_html}
  <form method="post" action="/oauth/authorize">
    {_hidden_inputs(params)}
    <label>Admin PIN<br><input type="password" name="pin" autofocus style="width: 320px; padding: 8px;" /></label>
    <p style="color:#555">{html_lib.escape(pin_hint)}</p>
    <button type="submit" style="padding: 8px 14px;">Approve</button>
  </form>
</body>
</html>"""
    return HTMLResponse(html)


def _make_redirect(
    redirect_uri: str, query: dict[str, str]
) -> RedirectResponse:
    """Append authorization response parameters to a redirect URI."""
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(
        f"{redirect_uri}{sep}{urlencode(query)}", status_code=302
    )


async def oauth_authorize_get(request: Request) -> Response:
    """Validate authorization input and render the approval form for the local user."""
    params = {k: v for k, v in request.query_params.items()}
    error = _validate_authorize_params(params)
    if error:
        return _authorize_form(params, error=error)
    return _authorize_form(params)


async def oauth_authorize_post(request: Request) -> Response:
    """Issue an authorization code after form approval and redirect the client back."""
    form = await request.form()
    params = {k: str(v) for k, v in form.items() if k != "pin"}
    error = _validate_authorize_params(params)
    if error:
        return _authorize_form(params, error=error)

    settings = get_settings()
    expected_pin = settings.oauth_admin_pin
    submitted_pin = str(form.get("pin") or "")
    if expected_pin and not hmac.compare_digest(submitted_pin, expected_pin):
        audit("oauth_pin_failed", client_id=params.get("client_id"))
        return _authorize_form(params, error="Invalid admin PIN")

    code = secrets.token_urlsafe(32)
    auth_code = AuthCode(
        code=code,
        client_id=params["client_id"],
        redirect_uri=params["redirect_uri"],
        scope=params.get("scope") or _default_scope(),
        resource=_normalize_resource(params["resource"]),
        code_challenge=params.get("code_challenge"),
        code_challenge_method=params.get("code_challenge_method"),
    )
    _CODES[code] = auth_code
    audit(
        "oauth_code_issued",
        client_id=auth_code.client_id,
        resource=auth_code.resource,
    )
    query = {"code": code, "iss": issuer_url(request)}
    if params.get("state"):
        query["state"] = params["state"]
    return _make_redirect(params["redirect_uri"], query)


def _verify_pkce(code_obj: AuthCode, verifier: str | None) -> bool:
    """Validate PKCE using Authlib's RFC7636 challenge helpers."""
    if not code_obj.code_challenge:
        return verifier is None
    if not verifier or not CODE_VERIFIER_PATTERN.match(verifier):
        return False
    method = code_obj.code_challenge_method or "plain"
    if method == "S256":
        return compare_s256_code_challenge(verifier, code_obj.code_challenge)
    return compare_plain_code_challenge(verifier, code_obj.code_challenge)


def issue_access_token(
    *, client_id: str, scope: str, resource: str, subject: str = "local-user"
) -> str:
    """Create a signed bearer token for an approved client, scope, resource, and subject."""
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": issuer_url(),
        "sub": subject,
        "aud": resource,
        "iat": now,
        "client_id": client_id,
        "scope": scope,
    }
    if settings.oauth_access_token_ttl_s > 0:
        payload["exp"] = now + settings.oauth_access_token_ttl_s
    return jwt.encode(payload, _jwt_secret(), algorithm="HS256")


async def oauth_token(request: Request) -> JSONResponse:
    """Exchange an authorization code for an access token after client, redirect, expiry, and PKCE checks."""
    form = await request.form()
    grant_type = str(form.get("grant_type") or "")
    if grant_type != "authorization_code":
        return _oauth_error(UnsupportedGrantTypeError(grant_type=grant_type))
    code = str(form.get("code") or "")
    client_id = str(form.get("client_id") or "")
    redirect_uri = str(form.get("redirect_uri") or "")
    verifier = str(form.get("code_verifier") or "") or None
    resource = str(form.get("resource") or "")
    if not resource:
        return _invalid_request("Missing resource")
    code_obj = _CODES.get(code)
    if not code_obj or code_obj.used:
        return _invalid_grant("Unknown or used code")
    if int(time.time()) - code_obj.created_at > get_settings().oauth_code_ttl_s:
        return _invalid_grant("Expired code")
    if code_obj.client_id != client_id or code_obj.redirect_uri != redirect_uri:
        return _invalid_grant("Client or redirect mismatch")
    if _normalize_resource(resource) != _normalize_resource(code_obj.resource):
        return _invalid_grant("Resource mismatch")
    if not _verify_pkce(code_obj, verifier):
        return _invalid_grant("PKCE verification failed")
    code_obj.used = True
    token = issue_access_token(
        client_id=client_id, scope=code_obj.scope, resource=code_obj.resource
    )
    audit("oauth_token_issued", client_id=client_id, resource=code_obj.resource)
    body: dict[str, Any] = {
        "access_token": token,
        "token_type": "Bearer",
        "scope": code_obj.scope,
    }
    if get_settings().oauth_access_token_ttl_s > 0:
        body["expires_in"] = get_settings().oauth_access_token_ttl_s
    return _json(body)


def validate_bearer_token(
    token: str, request: Request | None = None
) -> dict[str, Any]:
    """Decode and validate issuer, audience, resource, and scope claims for incoming bearer tokens."""
    return jwt.decode(
        token,
        _jwt_secret(),
        algorithms=["HS256"],
        audience=resource_url(request),
        issuer=issuer_url(request),
        options={"require": ["iat", "aud", "iss"]},
    )
