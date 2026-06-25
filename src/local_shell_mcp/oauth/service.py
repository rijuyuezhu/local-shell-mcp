"""Authlib-backed OAuth service operations.

Security model: see ``docs/security.md#oauth-security``. This module keeps
project-specific MCP policy explicit while moving OAuth request validation and
code issuance out of Starlette route handlers.
"""

import secrets
from dataclasses import dataclass
from typing import NoReturn

from authlib.oauth2.rfc6749.errors import InvalidRequestError, OAuth2Error
from authlib.oauth2.rfc7636.challenge import CODE_CHALLENGE_PATTERN

from ..audit import audit
from .adapters import LocalOAuth2Request, LocalOAuthClient
from .models import _CLIENTS, _CODES, AuthCode
from .urls import _normalize_resource, issuer_url, resource_url


@dataclass(frozen=True)
class AuthorizationRequest:
    """Validated authorization-code request data."""

    oauth_request: LocalOAuth2Request
    client: LocalOAuthClient
    params: dict[str, str]
    scope: str
    resource: str

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
    query: dict[str, str]
    code: AuthCode


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
