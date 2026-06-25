"""Authlib-backed OAuth service operations.

Security model: see ``docs/security.md#oauth-security``. This module keeps
project-specific MCP policy explicit while moving OAuth request validation and
code issuance out of Starlette route handlers.
"""

import secrets
import time
from dataclasses import dataclass
from typing import Any, NoReturn
from urllib.parse import urlparse

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

from ...audit import audit
from ..protocol.adapters import LocalOAuth2Request, LocalOAuthClient
from ..protocol.token_codec import issue_access_token
from .models import _CLIENTS, _CODES, AuthCode, OAuthClient
from .urls import _normalize_resource, issuer_url, resource_url

LOOPBACK_REDIRECT_HOSTS = {"127.0.0.1", "::1", "localhost"}
BLOCKED_REDIRECT_SCHEMES = {"javascript", "data"}
REGISTRATION_REDIRECT_ERROR = (
    "redirect_uris must be https, loopback http, or custom private-use URIs"
)


@dataclass(frozen=True)
class AuthorizationRequest:
    """Validated authorization-code request data."""

    oauth_request: LocalOAuth2Request
    """Authlib-shaped request adapter for the authorization request."""

    client: LocalOAuthClient
    """Authlib client adapter for the registered dynamic client."""

    params: dict[str, str]
    """Validated authorization request parameters."""

    scope: str
    """Normalized approved scope string."""

    resource: str
    """Normalized MCP resource URL bound to the authorization code."""

    @property
    def client_id(self) -> str:
        """Return the validated client identifier."""
        return self.client.get_client_id()

    @property
    def redirect_uri(self) -> str:
        """Return the validated redirect URI."""
        return self.params["redirect_uri"]

    @property
    def state(self) -> str | None:
        """Return optional client state."""
        return self.params.get("state")


@dataclass(frozen=True)
class AuthorizationResponse:
    """Authorization-code response values for the redirect adapter."""

    redirect_uri: str
    """Registered client redirect URI that receives the authorization response."""

    query: dict[str, str]
    """OAuth response parameters appended to the redirect URI."""

    code: AuthCode
    """Stored authorization code object for the issued code."""


@dataclass(frozen=True)
class TokenResponse:
    """Token endpoint response values after authorization-code exchange."""

    access_token: str
    """Signed bearer credential returned to the OAuth client."""

    token_type: str
    """OAuth token type value returned by the token endpoint."""

    scope: str
    """Scope string granted to the issued credential."""

    expires_in: int | None
    """Lifetime in seconds when the local credential has a configured TTL."""


def oauth_error_message(exc: OAuth2Error) -> str:
    """Return a user-facing message for local approval UI errors."""
    return str(exc.description or exc.error or "invalid_request")


def _invalid_authorization_request(description: str) -> InvalidRequestError:
    """Create an Authlib invalid_request error with legacy UI text."""
    return InvalidRequestError(description=description)


def _required_param(params: dict[str, str], key: str) -> str:
    """Return a required authorization parameter or raise an OAuth error."""
    value = params.get(key)
    if value:
        return value
    _raise_invalid(f"Missing {key}")


def _raise_invalid(description: str) -> NoReturn:
    """Raise an Authlib invalid_request error while satisfying type checkers."""
    raise _invalid_authorization_request(description)


def _is_private_use_redirect_scheme(parsed_scheme: str, netloc: str) -> bool:
    """Return whether a non-HTTP redirect scheme is private-use style."""
    return "." in parsed_scheme and not netloc


def _is_allowed_redirect_uri(uri: str) -> bool:
    """Accept HTTPS, loopback HTTP, and custom private-use redirect URIs."""
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    if not scheme or scheme in BLOCKED_REDIRECT_SCHEMES:
        return False
    if scheme == "https":
        return bool(parsed.netloc)
    if scheme == "http":
        return parsed.hostname in LOOPBACK_REDIRECT_HOSTS
    return _is_private_use_redirect_scheme(scheme, parsed.netloc)


def register_dynamic_client(body: Any) -> OAuthClient:
    """Validate dynamic client registration payload and persist a local client."""
    if not isinstance(body, dict):
        raise InvalidRequestError(
            description="Registration payload must be a JSON object"
        )
    raw_redirect_uris = body.get("redirect_uris")
    if not isinstance(raw_redirect_uris, list):
        raise InvalidRequestError(
            description="redirect_uris must be a non-empty list"
        )
    redirect_uris = [
        value.strip()
        for value in raw_redirect_uris
        if isinstance(value, str) and value.strip()
    ]
    if len(redirect_uris) != len(raw_redirect_uris) or not redirect_uris:
        raise InvalidRequestError(
            description="redirect_uris must contain non-empty strings"
        )
    if any(not _is_allowed_redirect_uri(uri) for uri in redirect_uris):
        raise InvalidRequestError(description=REGISTRATION_REDIRECT_ERROR)

    # Docs compliance: dynamic registration is intentionally low-friction, but
    # issues opaque client IDs and relies on later local approval before token
    # issuance.
    client_id = "local-shell-mcp-" + secrets.token_urlsafe(24)
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
    return client


def validate_authorization_request(
    params: dict[str, str],
) -> AuthorizationRequest:
    """Validate authorization request parameters with Authlib-shaped adapters."""
    oauth_request = LocalOAuth2Request("GET", "authorize", params)
    request_params = oauth_request.params
    if request_params.get("response_type") != "code":
        _raise_invalid("Only response_type=code is supported")

    client_id = _required_param(request_params, "client_id")
    redirect_uri = _required_param(request_params, "redirect_uri")
    resource = _required_param(request_params, "resource")

    # Docs compliance: MCP clients must send RFC 8707 ``resource`` and it must
    # match this server before a code can be issued.
    normalized_resource = _normalize_resource(resource)
    if normalized_resource != resource_url():
        _raise_invalid("resource does not match this MCP server")

    client_record = _CLIENTS.get(client_id)
    if client_record is None:
        _raise_invalid("Unknown client_id")
    client = LocalOAuthClient(client_record)

    if not client.check_response_type(request_params["response_type"]):
        _raise_invalid("Only response_type=code is supported")
    if not client.check_redirect_uri(redirect_uri):
        _raise_invalid("redirect_uri is not registered for this client")

    try:
        scope = client.get_allowed_scope(request_params.get("scope"))
    except ValueError as exc:
        raise _invalid_authorization_request(str(exc)) from exc

    # Docs compliance: public clients must bind authorization codes with PKCE.
    challenge = request_params.get("code_challenge")
    if not challenge:
        _raise_invalid("Missing code_challenge")
    if not CODE_CHALLENGE_PATTERN.match(challenge):
        _raise_invalid("Invalid code_challenge")
    method = request_params.get("code_challenge_method")
    if method and method not in {"S256", "plain"}:
        _raise_invalid("Unsupported code_challenge_method")

    return AuthorizationRequest(
        oauth_request=oauth_request,
        client=client,
        params=dict(request_params),
        scope=scope,
        resource=normalized_resource,
    )


def issue_authorization_response(
    request: AuthorizationRequest,
) -> AuthorizationResponse:
    """Issue and store a one-time authorization code for a validated request."""
    code = secrets.token_urlsafe(32)
    auth_code = AuthCode(
        code=code,
        client_id=request.client_id,
        redirect_uri=request.redirect_uri,
        scope=request.scope,
        resource=request.resource,
        code_challenge=request.params.get("code_challenge"),
        code_challenge_method=request.params.get("code_challenge_method"),
    )
    _CODES[code] = auth_code
    audit(
        "oauth_code_issued",
        client_id=auth_code.client_id,
        resource=auth_code.resource,
    )

    query = {"code": code, "iss": issuer_url()}
    if request.state:
        query["state"] = request.state
    return AuthorizationResponse(
        redirect_uri=request.redirect_uri,
        query=query,
        code=auth_code,
    )


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


def _auth_code_expired(code_obj: AuthCode, *, now: int, ttl_s: int) -> bool:
    """Return whether an authorization code is past its configured TTL."""
    return now - code_obj.created_at > ttl_s


def _prune_codes(*, now: int | None = None, keep: str | None = None) -> None:
    """Remove used or expired authorization codes from the in-memory store."""
    from ...config.settings import get_settings

    settings = get_settings()
    current_time = int(time.time()) if now is None else now
    for code, code_obj in list(_CODES.items()):
        if code == keep:
            continue
        if code_obj.used or _auth_code_expired(
            code_obj, now=current_time, ttl_s=settings.oauth_code_ttl_s
        ):
            _CODES.pop(code, None)


def exchange_authorization_code(params: dict[str, str]) -> TokenResponse:
    """Exchange an authorization code for a bearer token after Authlib-shaped validation."""
    from ...config.settings import get_settings

    oauth_request = LocalOAuth2Request("POST", "token", params)
    request_params = oauth_request.params
    grant_type = request_params.get("grant_type") or ""
    if grant_type != "authorization_code":
        raise UnsupportedGrantTypeError(grant_type=grant_type)

    resource = request_params.get("resource") or ""
    # Docs compliance: MCP requires RFC 8707 ``resource`` in token requests, and
    # the resource must match the one bound to the authorization code.
    if not resource:
        raise InvalidRequestError(description="Missing resource")

    code = request_params.get("code") or ""
    client_id = request_params.get("client_id") or ""
    redirect_uri = request_params.get("redirect_uri") or ""
    verifier = request_params.get("code_verifier") or None

    _prune_codes()
    code_obj = _CODES.get(code)
    if not code_obj or code_obj.used:
        raise InvalidGrantError(description="Unknown or used code")

    settings = get_settings()
    if _auth_code_expired(
        code_obj, now=int(time.time()), ttl_s=settings.oauth_code_ttl_s
    ):
        raise InvalidGrantError(description="Expired code")
    if code_obj.client_id != client_id or code_obj.redirect_uri != redirect_uri:
        raise InvalidGrantError(description="Client or redirect mismatch")
    if _normalize_resource(resource) != _normalize_resource(code_obj.resource):
        raise InvalidGrantError(description="Resource mismatch")
    if not _verify_pkce(code_obj, verifier):
        raise InvalidGrantError(description="PKCE verification failed")

    code_obj.used = True
    credential = issue_access_token(
        client_id=client_id, scope=code_obj.scope, resource=code_obj.resource
    )
    audit("oauth_token_issued", client_id=client_id, resource=code_obj.resource)
    expires_in = (
        settings.oauth_access_token_ttl_s
        if settings.oauth_access_token_ttl_s > 0
        else None
    )
    return TokenResponse(
        access_token=credential,
        token_type="Bearer",
        scope=code_obj.scope,
        expires_in=expires_in,
    )
