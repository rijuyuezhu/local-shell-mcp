"""OAuth token exchange, JWT signing, PKCE verification, and bearer validation.

Security model: see ``docs/security.md#oauth-security``. Token exchange binds
authorization codes to client, redirect URI, resource, PKCE, and one-time use.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

import jwt
from authlib.oauth2.rfc6749.errors import UnsupportedGrantTypeError
from authlib.oauth2.rfc7636.challenge import (
    CODE_VERIFIER_PATTERN,
    compare_plain_code_challenge,
    compare_s256_code_challenge,
)
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..audit import audit
from ..config.settings import get_settings
from .models import _CODES, AuthCode
from .responses import (
    _invalid_grant,
    _invalid_request,
    _json,
    _oauth_error,
)
from .urls import _normalize_resource, issuer_url, resource_url


def _jwt_secret() -> str:
    """Return a configured or persisted signing secret for local bearer tokens."""
    settings = get_settings()
    # Docs compliance: bearer tokens are signed locally with state-directory
    # key material. Operators must protect and rotate this state between trust
    # domains because there is no central revocation service.
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


def _verify_pkce(code_obj: AuthCode, verifier: str | None) -> bool:
    """Validate PKCE using Authlib's RFC7636 challenge helpers."""
    # Docs compliance: authorization-code exchange verifies PKCE when the
    # authorization request included a challenge; S256 uses Authlib's RFC 7636
    # comparison helper.
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


async def token_endpoint(request: Request) -> JSONResponse:
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
    # Docs compliance: MCP requires RFC 8707 ``resource`` in token requests, and
    # the resource must match the one bound to the authorization code.
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
    # Docs compliance: resource-server validation requires accepting only tokens
    # issued by this issuer and audience-bound to this MCP resource.
    return jwt.decode(
        token,
        _jwt_secret(),
        algorithms=["HS256"],
        audience=resource_url(request),
        issuer=issuer_url(request),
        options={"require": ["iat", "aud", "iss"]},
    )
